"""Pure, testable calculations used by the Streamlit dashboard."""

from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


def _decimal(value):
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def summarize_usage(usage, runs):
    attempts = usage.get("attempts") or []
    token_fields = ("input_tokens", "output_tokens", "cache_creation_tokens", "cache_read_tokens")
    totals = {}
    unknown = {}
    for field in token_fields:
        values = [row.get(field) for row in attempts]
        totals[field] = sum(value for value in values if isinstance(value, int))
        unknown[field] = sum(value is None for value in values)
    return {
        "measured_request_count": len(runs),
        "measured_attempt_count": len(attempts),
        "reported_token_totals": totals,
        "unknown_token_counts": unknown,
        "run_statuses": dict(Counter(row.get("status", "unknown") for row in runs)),
        "attempt_statuses": dict(Counter(row.get("generation_status") or row.get("api_status") or "unknown"
                                         for row in attempts)),
        "models": sorted({row.get("model_id") for row in attempts if row.get("model_id")}),
        "agents": sorted({row.get("agent_id") for row in runs if row.get("agent_id")}),
        "labeling": {
            "requests_and_tokens": "Measured from the M2 request and per-attempt usage ledger.",
            "missing_tokens": "Unknown values are not converted to zero.",
        },
    }


def developer_adoption(runs, events):
    developers = defaultdict(lambda: {"requests": 0, "successful_runs": 0, "active_days": set(),
                                      "first_run_at": None, "last_run_at": None})
    for run in sorted(runs, key=lambda row: (row.get("created_at") or "", row.get("run_id") or "")):
        developer_id = run.get("developer_id")
        if not developer_id:
            continue
        row = developers[developer_id]
        row["requests"] += 1
        row["successful_runs"] += run.get("status") == "success"
        created = run.get("created_at")
        if created:
            row["active_days"].add(created[:10])
            row["first_run_at"] = row["first_run_at"] or created
            row["last_run_at"] = created
    by_developer = defaultdict(dict)
    for event in events:
        by_developer[event.get("developer_id")][event.get("event_type")] = event.get("occurred_at")
    rows = []
    for developer_id, values in sorted(developers.items()):
        lifecycle = by_developer.get(developer_id, {})
        rows.append({
            "developer_id": developer_id, "requests": values["requests"],
            "successful_runs": values["successful_runs"], "active_days": len(values["active_days"]),
            "first_run_at": values["first_run_at"], "last_run_at": values["last_run_at"],
            "onboarded_at": lifecycle.get("developer_onboarded"),
            "first_successful_api_call_at": lifecycle.get("first_successful_api_call"),
            "activated_at": lifecycle.get("developer_activated"),
        })
    onboarded = sum(row["onboarded_at"] is not None for row in rows)
    activated = sum(row["activated_at"] is not None for row in rows)
    return {
        "developers": rows,
        "onboarded_developers": onboarded,
        "activated_developers": activated,
        "activation_rate": None if onboarded == 0 else activated / onboarded,
        "retention_rate": None,
        "activation_note": "Insufficient lifecycle data." if onboarded == 0 else "Measured from recorded lifecycle events.",
        "retention_note": "Insufficient elapsed lifecycle periods; no retention rate is reported.",
    }


def monetization_summary(invoices, unit_economics):
    def total(field):
        values = [_decimal(row.get(field)) for row in invoices]
        return None if any(value is None for value in values) else sum(values, Decimal("0"))

    return {
        "estimated_upstream_cost": _decimal(unit_economics.get("estimated_upstream_cost")),
        "simulated_customer_charges": total("illustrative_customer_charge"),
        "simulated_partner_payouts": total("simulated_partner_payout"),
        "simulated_gross_margin": _decimal(unit_economics.get("simulated_gross_margin")),
        "labels": {
            "estimated_upstream_cost": "Estimated Anthropic upstream cost from recorded token usage.",
            "simulated_customer_charges": "Illustrative M3 customer charges; not actual revenue.",
            "simulated_partner_payouts": "Illustrative partner attribution; no payment was made.",
            "simulated_gross_margin": "Simulated margin; not financial reporting.",
        },
    }


def spending_summary(status, reservations, alerts, audit):
    return {
        "held_spend": _decimal(status.get("held_spend")),
        "unreconciled_requests": status.get("unreconciled_requests", 0),
        "reserved_count": sum(row.get("status") == "reserved" for row in reservations),
        "reconciled_count": sum(row.get("status") == "reconciled" for row in reservations),
        "unknown_cost_count": sum(row.get("actual_cost") is None for row in reservations),
        "alert_count": len(alerts),
        "denial_count": sum(row.get("event_type") == "preflight_denial" for row in audit),
        "labels": {
            "held_spend": "Current M4 budget hold; may be reserved, reconciled actual cost, or retained for unknown usage.",
            "actual_cost": "Actual estimated upstream cost from complete per-attempt usage.",
            "unknown_cost": "Unreconciled usage retains its reservation and is not treated as zero.",
        },
    }


def filter_by_time(rows, start, end, field="created_at"):
    start = start if isinstance(start, datetime) else datetime.fromisoformat(str(start).replace("Z", "+00:00"))
    end = end if isinstance(end, datetime) else datetime.fromisoformat(str(end).replace("Z", "+00:00"))
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    result = []
    for row in rows:
        value = row.get(field)
        if not value:
            continue
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        if start <= moment < end:
            result.append(row)
    return result
