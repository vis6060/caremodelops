"""Decimal-only upstream costing from the persisted per-attempt ledger."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from .models import PartnerTerms, PricingPlan, RateCard

MILLION = Decimal("1000000")
MONEY_QUANTUM = Decimal("0.00000001")


def timestamp(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def decimal_value(value, field="value"):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError(f"Invalid decimal {field}.") from error
    if not result.is_finite():
        raise ValueError(f"Invalid decimal {field}.")
    return result


def money(value):
    return value.quantize(MONEY_QUANTUM) if value is not None else None


def money_text(value):
    return format(money(value), "f") if value is not None else None


def _effective(row, at):
    return timestamp(row.effective_from) <= at and (row.effective_to is None or at < timestamp(row.effective_to))


def rate_card_for(session, model_id, at):
    at = timestamp(at)
    rows = list(session.scalars(select(RateCard).where(RateCard.model_id == model_id)))
    matches = [row for row in rows if _effective(row, at)]
    return max(matches, key=lambda row: timestamp(row.effective_from)) if matches else None


def pricing_plan_for(session, organization_id, at):
    from .models import OrganizationPlan

    at = timestamp(at)
    assignments = list(session.scalars(select(OrganizationPlan).where(
        OrganizationPlan.organization_id == organization_id)))
    matches = [row for row in assignments if _effective(row, at)]
    if not matches:
        return None
    assignment = max(matches, key=lambda row: timestamp(row.effective_from))
    plan = session.get(PricingPlan, assignment.pricing_plan_id)
    return plan if plan is not None and _effective(plan, at) else None


def partner_terms_for(session, partner_id, at):
    if partner_id is None:
        return None
    at = timestamp(at)
    rows = list(session.scalars(select(PartnerTerms).where(PartnerTerms.partner_id == partner_id)))
    matches = [row for row in rows if _effective(row, at)]
    return max(matches, key=lambda row: timestamp(row.effective_from)) if matches else None


@dataclass(frozen=True)
class AttemptCost:
    total: Decimal | None
    input_cost: Decimal | None
    output_cost: Decimal | None
    cache_write_cost: Decimal | None
    cache_read_cost: Decimal | None
    rate_card_version: str | None
    unknown_reason: str | None


def estimate_attempt_cost(attempt, rate_card):
    """Price one M2 attempt, never a top-level aggregate or replayed request."""
    if rate_card is None:
        return AttemptCost(None, None, None, None, None, None, "No effective rate card for the reported model.")
    token_fields = ("input_tokens", "output_tokens", "cache_creation_tokens", "cache_read_tokens")
    if any(getattr(attempt, field) is None for field in token_fields):
        return AttemptCost(None, None, None, None, None, rate_card.id,
                           "One or more per-attempt token counts are unknown.")
    counts = {field: getattr(attempt, field) for field in token_fields}
    if any(not isinstance(value, int) or value < 0 for value in counts.values()):
        return AttemptCost(None, None, None, None, None, rate_card.id,
                           "One or more per-attempt token counts are invalid.")

    details = attempt.details or {}
    cache_total = counts["cache_creation_tokens"]
    five = details.get("cache_creation_5m_tokens")
    hour = details.get("cache_creation_1h_tokens")
    if five is not None or hour is not None:
        if not all(isinstance(value, int) and value >= 0 for value in (five or 0, hour or 0)):
            return AttemptCost(None, None, None, None, None, rate_card.id, "Cache-write token breakdown is invalid.")
        five, hour = five or 0, hour or 0
        if five + hour != cache_total:
            return AttemptCost(None, None, None, None, None, rate_card.id,
                               "Cache-write token breakdown does not match the attempt total.")
    elif cache_total:
        ttl = details.get("cache_write_ttl")
        if ttl not in {"5m", "1h"}:
            return AttemptCost(None, None, None, None, None, rate_card.id,
                               "Cache-write TTL is unknown; 5-minute and 1-hour rates differ.")
        five, hour = (cache_total, 0) if ttl == "5m" else (0, cache_total)
    else:
        five = hour = 0

    input_cost = Decimal(counts["input_tokens"]) * decimal_value(rate_card.input_per_million) / MILLION
    output_cost = Decimal(counts["output_tokens"]) * decimal_value(rate_card.output_per_million) / MILLION
    cache_write_cost = (
        Decimal(five) * decimal_value(rate_card.cache_write_5m_per_million) / MILLION
        + Decimal(hour) * decimal_value(rate_card.cache_write_1h_per_million) / MILLION
    )
    cache_read_cost = Decimal(counts["cache_read_tokens"]) * decimal_value(rate_card.cache_read_per_million) / MILLION
    total = input_cost + output_cost + cache_write_cost + cache_read_cost
    return AttemptCost(*(money(value) for value in (total, input_cost, output_cost, cache_write_cost, cache_read_cost)),
                       rate_card.id, None)
