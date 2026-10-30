"""Tenant-scoped estimates, simulated invoices, adjustments, and reconciliation."""

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from chartground.platform_m2.database import Attempt, Organization, Run

from .costing import (decimal_value, estimate_attempt_cost, money, money_text,
                      partner_terms_for, pricing_plan_for, rate_card_for, timestamp)
from .models import Invoice, InvoiceLine


def _in_period(value, start, end):
    moment = timestamp(value)
    return timestamp(start) <= moment < timestamp(end)


def _sum_known(values):
    values = list(values)
    return None if any(value is None for value in values) else sum(values, Decimal("0"))


def _serialize_line(line):
    return {
        "line_key": line["line_key"], "line_type": line["line_type"],
        "run_id": line.get("run_id"), "attempt_id": line.get("attempt_id"),
        "description": line["description"], "upstream_cost": money_text(line.get("upstream_cost")),
        "customer_charge": money_text(line.get("customer_charge")), "waived": bool(line.get("waived")),
        "rate_card_version": line.get("rate_card_version"), "pricing_plan_version": line["pricing_plan_version"],
        "details": line.get("details", {}),
    }


def invoice_payload(invoice, lines):
    return {
        "invoice_id": invoice.id,
        "organization_id": invoice.organization_id,
        "invoice_type": invoice.invoice_type,
        "reporting_period": {"start": invoice.reporting_period_start, "end": invoice.reporting_period_end},
        "status": invoice.status,
        "currency": invoice.currency,
        "pricing_plan_version": invoice.pricing_plan_version,
        "partner_terms_version": invoice.partner_terms_version,
        "correction_of_invoice_id": invoice.correction_of_invoice_id,
        "estimated_upstream_cost": invoice.estimated_upstream_cost,
        "illustrative_customer_charge": invoice.customer_charge,
        "simulated_partner_payout": invoice.partner_payout,
        "simulated_gross_margin": invoice.gross_margin,
        "pricing_snapshot": invoice.pricing_snapshot,
        "created_at": invoice.created_at,
        "lines": [{
            "line_key": line.line_key, "line_type": line.line_type, "run_id": line.run_id,
            "attempt_id": line.attempt_id, "description": line.description,
            "upstream_cost": line.upstream_cost, "customer_charge": line.customer_charge,
            "waived": bool(line.waived), "rate_card_version": line.rate_card_version,
            "pricing_plan_version": line.pricing_plan_version, "details": line.details,
        } for line in lines],
        "disclaimer": "Customer charges, partner payouts, and invoices are illustrative simulations. Upstream cost is an estimate from recorded Anthropic usage and documented rate cards.",
    }


class MonetizationService:
    def __init__(self, sessions):
        self.sessions = sessions

    def _estimate(self, session, organization_id, start, end):
        start_at, end_at = timestamp(start), timestamp(end)
        if start_at >= end_at:
            raise ValueError("Reporting period end must be after start.")
        organization = session.get(Organization, organization_id)
        if organization is None:
            raise ValueError("Organization not found.")
        plan = pricing_plan_for(session, organization_id, start_at)
        if plan is None:
            raise ValueError("No effective customer pricing plan; pricing was not assumed.")
        terms = partner_terms_for(session, organization.partner_id, start_at)
        if organization.partner_id and terms is None:
            raise ValueError("No effective partner terms; revenue share was not assumed.")

        runs = [run for run in session.scalars(select(Run).where(Run.organization_id == organization_id))
                if _in_period(run.created_at, start_at, end_at)]
        run_ids = [run.id for run in runs]
        attempts = list(session.scalars(select(Attempt).where(Attempt.run_id.in_(run_ids)).order_by(Attempt.id))) if run_ids else []
        attempts_by_run = {}
        for attempt in attempts:
            attempts_by_run.setdefault(attempt.run_id, []).append(attempt)

        multiplier = decimal_value(plan.usage_multiplier, "usage_multiplier")
        response_fee = decimal_value(plan.successful_response_fee, "successful_response_fee")
        minimum = decimal_value(plan.minimum_commitment, "minimum_commitment")
        lines, rate_snapshots = [], {}
        upstream_values, customer_values = [], []

        for run in sorted(runs, key=lambda item: (item.created_at, item.id)):
            for attempt in attempts_by_run.get(run.id, []):
                model_id = (attempt.details or {}).get("model_id")
                card = rate_card_for(session, model_id, run.created_at) if model_id else None
                result = estimate_attempt_cost(attempt, card)
                if card is not None:
                    rate_snapshots[card.id] = {
                        "model_id": card.model_id, "effective_from": card.effective_from,
                        "currency": card.currency, "input_per_million": card.input_per_million,
                        "output_per_million": card.output_per_million,
                        "cache_write_5m_per_million": card.cache_write_5m_per_million,
                        "cache_write_1h_per_million": card.cache_write_1h_per_million,
                        "cache_read_per_million": card.cache_read_per_million,
                        "source_name": card.source_name, "source_url": card.source_url,
                    }
                upstream_values.append(result.total)
                successful = run.status == "success"
                customer = money(result.total * multiplier) if successful and result.total is not None else (Decimal("0") if not successful else None)
                customer_values.append(customer)
                lines.append({
                    "line_key": f"attempt:{attempt.id}", "line_type": "usage", "run_id": run.id,
                    "attempt_id": attempt.id, "description": "Recorded Claude attempt usage" if successful else "Recorded upstream usage; customer charge waived for unsuccessful response",
                    "upstream_cost": result.total, "customer_charge": customer, "waived": not successful,
                    "rate_card_version": result.rate_card_version, "pricing_plan_version": plan.id,
                    "details": {
                        "attempt_number": attempt.number, "run_status": run.status, "model_id": model_id,
                        "input_tokens": attempt.input_tokens, "output_tokens": attempt.output_tokens,
                        "cache_creation_tokens": attempt.cache_creation_tokens, "cache_read_tokens": attempt.cache_read_tokens,
                        "unknown_reason": result.unknown_reason,
                    },
                })
            if run.status == "success" and response_fee:
                customer_values.append(response_fee)
                lines.append({
                    "line_key": f"response:{run.id}", "line_type": "successful_response_fee", "run_id": run.id,
                    "description": "Illustrative successful-response platform fee", "upstream_cost": Decimal("0"),
                    "customer_charge": response_fee, "waived": False, "rate_card_version": None,
                    "pricing_plan_version": plan.id, "details": {"run_status": run.status},
                })

        upstream_total = _sum_known(upstream_values)
        subtotal = _sum_known(customer_values)
        if subtotal is not None and subtotal < minimum:
            top_up = money(minimum - subtotal)
            customer_values.append(top_up)
            lines.append({
                "line_key": "minimum-commitment", "line_type": "minimum_commitment", "description": "Illustrative committed-use minimum true-up",
                "upstream_cost": Decimal("0"), "customer_charge": top_up, "waived": False,
                "rate_card_version": None, "pricing_plan_version": plan.id,
                "details": {"minimum_commitment": money_text(minimum)},
            })
            subtotal = _sum_known(customer_values)

        partner_rate = decimal_value(terms.revenue_share_rate) if terms else Decimal("0")
        payout = money(subtotal * partner_rate) if subtotal is not None else None
        gross = money(subtotal - upstream_total - payout) if subtotal is not None and upstream_total is not None else None
        snapshot = {
            "customer_plan": {
                "id": plan.id, "code": plan.code, "effective_from": plan.effective_from,
                "usage_multiplier": plan.usage_multiplier, "successful_response_fee": plan.successful_response_fee,
                "minimum_commitment": plan.minimum_commitment, "illustrative": True,
            },
            "rate_cards": rate_snapshots,
            "partner_terms": None if terms is None else {
                "id": terms.id, "partner_id": terms.partner_id,
                "revenue_share_rate": terms.revenue_share_rate, "illustrative": True,
            },
            "unsuccessful_response_policy": "Upstream usage is retained as cost; customer usage and response fees are waived unless the run status is success.",
        }
        return {
            "organization_id": organization_id, "channel": organization.channel,
            "partner_id": organization.partner_id, "reporting_period": {"start": start_at.isoformat(), "end": end_at.isoformat()},
            "currency": plan.currency, "pricing_plan_version": plan.id,
            "partner_terms_version": terms.id if terms else None,
            "estimated_upstream_cost": money_text(upstream_total),
            "known_upstream_cost_subtotal": money_text(sum((value for value in upstream_values if value is not None), Decimal("0"))),
            "illustrative_customer_charge": money_text(subtotal),
            "simulated_partner_payout": money_text(payout), "simulated_gross_margin": money_text(gross),
            "unknown_upstream_attempts": sum(value is None for value in upstream_values),
            "pricing_snapshot": snapshot, "lines": [_serialize_line(line) for line in lines],
            "disclaimer": "Illustrative customer pricing is distinct from estimated Anthropic upstream cost.",
        }

    def estimate(self, organization_id, start, end):
        with self.sessions() as session:
            return self._estimate(session, organization_id, start, end)

    def _create_invoice_once(self, organization_id, start, end, idempotency_key):
        billing_key = f"standard:{timestamp(start).isoformat()}:{timestamp(end).isoformat()}"
        with self.sessions.begin() as session:
            existing = session.scalar(select(Invoice).where(
                Invoice.organization_id == organization_id,
                (Invoice.idempotency_key == idempotency_key) | (Invoice.billing_key == billing_key)))
            if existing is not None:
                if existing.billing_key != billing_key:
                    raise ValueError("Idempotency key already used for a different invoice request.")
                lines = list(session.scalars(select(InvoiceLine).where(InvoiceLine.invoice_id == existing.id).order_by(InvoiceLine.id)))
                return invoice_payload(existing, lines)
            estimate = self._estimate(session, organization_id, start, end)
            invoice = Invoice(
                id=str(uuid4()), organization_id=organization_id, invoice_type="standard",
                reporting_period_start=estimate["reporting_period"]["start"], reporting_period_end=estimate["reporting_period"]["end"],
                idempotency_key=idempotency_key, billing_key=billing_key, correction_of_invoice_id=None,
                status="simulated", currency=estimate["currency"], pricing_plan_version=estimate["pricing_plan_version"],
                partner_terms_version=estimate["partner_terms_version"], estimated_upstream_cost=estimate["estimated_upstream_cost"],
                customer_charge=estimate["illustrative_customer_charge"], partner_payout=estimate["simulated_partner_payout"],
                gross_margin=estimate["simulated_gross_margin"], pricing_snapshot=estimate["pricing_snapshot"],
            )
            session.add(invoice)
            session.flush()
            for data in estimate["lines"]:
                session.add(InvoiceLine(invoice_id=invoice.id, **data))
            session.flush()
            lines = list(session.scalars(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id).order_by(InvoiceLine.id)))
            return invoice_payload(invoice, lines)

    def create_invoice(self, organization_id, start, end, idempotency_key):
        try:
            return self._create_invoice_once(organization_id, start, end, idempotency_key)
        except IntegrityError as error:
            billing_key = f"standard:{timestamp(start).isoformat()}:{timestamp(end).isoformat()}"
            with self.sessions() as session:
                existing = session.scalar(select(Invoice).where(
                    Invoice.organization_id == organization_id,
                    (Invoice.idempotency_key == idempotency_key) | (Invoice.billing_key == billing_key)))
                if existing is None:
                    raise error
                if existing.billing_key != billing_key:
                    raise ValueError("Idempotency key already used for a different invoice request.") from error
                lines = list(session.scalars(select(InvoiceLine).where(InvoiceLine.invoice_id == existing.id).order_by(InvoiceLine.id)))
                return invoice_payload(existing, lines)

    def create_adjustment(self, organization_id, invoice_id, amount, reason, idempotency_key):
        adjustment = decimal_value(amount, "adjustment amount")
        if adjustment == 0:
            raise ValueError("Adjustment amount must be nonzero.")
        with self.sessions.begin() as session:
            original = session.scalar(select(Invoice).where(Invoice.id == invoice_id, Invoice.organization_id == organization_id))
            if original is None:
                raise LookupError("Invoice not found.")
            billing_key = f"adjustment:{idempotency_key}"
            existing = session.scalar(select(Invoice).where(Invoice.organization_id == organization_id,
                                                             Invoice.idempotency_key == idempotency_key))
            if existing is not None:
                if existing.correction_of_invoice_id != invoice_id:
                    raise ValueError("Idempotency key already used for a different adjustment.")
                lines = list(session.scalars(select(InvoiceLine).where(InvoiceLine.invoice_id == existing.id)))
                if not lines or decimal_value(lines[0].customer_charge) != adjustment or lines[0].description != reason:
                    raise ValueError("Idempotency key already used for a different adjustment.")
                return invoice_payload(existing, lines)
            snapshot = original.pricing_snapshot
            terms = snapshot.get("partner_terms")
            payout = money(adjustment * decimal_value(terms["revenue_share_rate"])) if terms else Decimal("0")
            gross = money(adjustment - payout)
            invoice = Invoice(
                id=str(uuid4()), organization_id=organization_id, invoice_type="adjustment",
                reporting_period_start=original.reporting_period_start, reporting_period_end=original.reporting_period_end,
                idempotency_key=idempotency_key, billing_key=billing_key, correction_of_invoice_id=original.id,
                status="simulated", currency=original.currency, pricing_plan_version=original.pricing_plan_version,
                partner_terms_version=original.partner_terms_version, estimated_upstream_cost=money_text(Decimal("0")),
                customer_charge=money_text(adjustment), partner_payout=money_text(payout), gross_margin=money_text(gross),
                pricing_snapshot=snapshot,
            )
            session.add(invoice)
            session.flush()
            line = InvoiceLine(
                invoice_id=invoice.id, line_key="adjustment", line_type="adjustment", run_id=None, attempt_id=None,
                description=reason, upstream_cost=money_text(Decimal("0")), customer_charge=money_text(adjustment),
                waived=0, rate_card_version=None, pricing_plan_version=original.pricing_plan_version,
                details={"correction_of_invoice_id": original.id},
            )
            session.add(line)
            session.flush()
            return invoice_payload(invoice, [line])

    def get_invoice(self, organization_id, invoice_id):
        with self.sessions() as session:
            invoice = session.scalar(select(Invoice).where(Invoice.id == invoice_id, Invoice.organization_id == organization_id))
            if invoice is None:
                return None
            lines = list(session.scalars(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id).order_by(InvoiceLine.id)))
            return invoice_payload(invoice, lines)

    def list_invoices(self, organization_id):
        with self.sessions() as session:
            invoices = list(session.scalars(select(Invoice).where(Invoice.organization_id == organization_id).order_by(Invoice.created_at, Invoice.id)))
            return [invoice_payload(invoice, list(session.scalars(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id).order_by(InvoiceLine.id)))) for invoice in invoices]

    def reconcile(self, organization_id, invoice_id):
        payload = self.get_invoice(organization_id, invoice_id)
        if payload is None:
            return None
        upstream = _sum_known(decimal_value(line["upstream_cost"]) if line["upstream_cost"] is not None else None for line in payload["lines"])
        customer = _sum_known(decimal_value(line["customer_charge"]) if line["customer_charge"] is not None else None for line in payload["lines"])
        attempts = [line["attempt_id"] for line in payload["lines"] if line["attempt_id"] is not None]
        return {
            "invoice_id": invoice_id, "organization_id": organization_id,
            "upstream_total_matches": money_text(upstream) == payload["estimated_upstream_cost"],
            "customer_total_matches": money_text(customer) == payload["illustrative_customer_charge"],
            "attempts_unique": len(attempts) == len(set(attempts)),
            "balanced": money_text(upstream) == payload["estimated_upstream_cost"] and money_text(customer) == payload["illustrative_customer_charge"] and len(attempts) == len(set(attempts)),
        }
