import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_mock_engine, func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chartground.platform_m2.database import Attempt, Base, Run
from chartground.platform_m2.seed import seed as seed_m2
from chartground.platform_m3.api import create_app
from chartground.platform_m3.costing import estimate_attempt_cost, rate_card_for
from chartground.platform_m3.models import Invoice, PricingPlan, RateCard
from chartground.platform_m3.seed import seed as seed_m3

KEYS = {"oncopilot": "m3-test-onco-" + "a" * 32, "radpath": "m3-test-rad-" + "b" * 32}
START = "2026-10-01T00:00:00+00:00"
END = "2026-11-01T00:00:00+00:00"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    original_connect = socket.socket.connect

    def blocked(sock, address):
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(sock, address)
        raise AssertionError("Network is forbidden in M3 tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("CHARTGROUND_M2_ALLOW_CLAUDE", "0")


def auth(org="oncopilot", idempotency=None):
    result = {"Authorization": "Bearer " + KEYS[org]}
    if idempotency:
        result["Idempotency-Key"] = idempotency
    return result


@pytest.fixture
def platform(tmp_path):
    url = "sqlite:///" + (tmp_path / "m3.sqlite3").as_posix()
    app = create_app(url, adapter=lambda _: None, seed_defaults=False)
    seed_m2(app.state.sessions, KEYS)
    seed_m3(app.state.sessions)
    with TestClient(app) as client:
        yield client, app
    app.state.engine.dispose()


def add_run(app, organization="oncopilot", status="success", attempts=(), created_at="2026-10-15T12:00:00+00:00"):
    run_id = str(uuid4())
    direct = organization == "oncopilot"
    with app.state.sessions.begin() as session:
        session.add(Run(
            id=run_id, organization_id=organization, developer_id="onco-dev" if direct else "rad-dev",
            agent_id="onco-agent" if direct else "rad-agent", partner_id=None if direct else "meddata-partners",
            idempotency_key=str(uuid4()), fingerprint="f" * 64, case_id="cg-syn-012" if direct else "cg-syn-013",
            provider="claude", status=status, created_at=created_at, response={},
        ))
        session.flush()
        for number, values in enumerate(attempts, 1):
            details = {
                "attempt": number, "model_id": "claude-sonnet-5-5", "api_status": "success",
                "generation_status": "parsed", **values.pop("details", {}),
            }
            session.add(Attempt(run_id=run_id, number=number, details=details, **values))
    return run_id


def tokens(input_tokens=1000, output_tokens=200, cache_creation_tokens=0, cache_read_tokens=0, details=None):
    return dict(input_tokens=input_tokens, output_tokens=output_tokens,
                cache_creation_tokens=cache_creation_tokens, cache_read_tokens=cache_read_tokens,
                details=details or {})


def estimate(client, org="oncopilot", start=START, end=END):
    response = client.get("/v1/pricing/estimate", headers=auth(org), params={
        "reporting_period_start": start, "reporting_period_end": end,
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_decimal_costing_and_separate_cache_rates(platform):
    _, app = platform
    with app.state.sessions() as session:
        card = rate_card_for(session, "claude-sonnet-5-5", "2026-10-15T00:00:00+00:00")
        attempt = SimpleNamespace(input_tokens=1_000_000, output_tokens=1_000_000,
                                  cache_creation_tokens=1_000_000, cache_read_tokens=1_000_000,
                                  details={"cache_write_ttl": "5m"})
        five = estimate_attempt_cost(attempt, card)
        attempt.details = {"cache_write_ttl": "1h"}
        hour = estimate_attempt_cost(attempt, card)
    assert str(five.total) == "14.60000000"
    assert str(hour.total) == "16.10000000"
    assert str(five.cache_read_cost) == "0.10000000"


def test_missing_usage_and_ambiguous_cache_remain_unknown(platform):
    _, app = platform
    with app.state.sessions() as session:
        card = rate_card_for(session, "claude-sonnet-5-5", START)
        missing = SimpleNamespace(input_tokens=None, output_tokens=2, cache_creation_tokens=0,
                                  cache_read_tokens=0, details={})
        ambiguous = SimpleNamespace(input_tokens=1, output_tokens=2, cache_creation_tokens=3,
                                    cache_read_tokens=0, details={})
        assert estimate_attempt_cost(missing, card).total is None
        result = estimate_attempt_cost(ambiguous, card)
        assert result.total is None and "TTL" in result.unknown_reason


def test_retries_count_once_and_unsuccessful_customer_charge_is_waived(platform):
    client, app = platform
    add_run(app, attempts=[tokens(input_tokens=1000), tokens(input_tokens=2000)])
    add_run(app, status="fallback", attempts=[tokens(input_tokens=3000)])
    result = estimate(client)
    usage = [line for line in result["lines"] if line["line_type"] == "usage"]
    assert len(usage) == 3 and len({line["attempt_id"] for line in usage}) == 3
    waived = [line for line in usage if line["details"]["run_status"] == "fallback"]
    assert len(waived) == 1 and waived[0]["waived"] is True and waived[0]["customer_charge"] == "0.00000000"
    assert result["estimated_upstream_cost"] == "0.01800000"
    assert result["illustrative_customer_charge"] == "0.06500000"


def test_committed_plan_partner_attribution_and_direct_customer(platform):
    client, _ = platform
    direct = estimate(client)
    partner = estimate(client, "radpath")
    assert direct["channel"] == "direct" and direct["partner_id"] is None
    assert direct["simulated_partner_payout"] == "0.00000000"
    assert partner["pricing_snapshot"]["customer_plan"]["code"] == "committed_use"
    assert partner["illustrative_customer_charge"] == "25.00000000"
    assert partner["simulated_partner_payout"] == "5.00000000"
    assert partner["simulated_gross_margin"] == "20.00000000"


def test_invoice_idempotency_isolation_adjustment_and_reconciliation(platform):
    client, app = platform
    add_run(app, attempts=[tokens()])
    body = {"reporting_period_start": START, "reporting_period_end": END}
    first = client.post("/v1/invoices", headers=auth("oncopilot", "invoice-1"), json=body)
    replay = client.post("/v1/invoices", headers=auth("oncopilot", "invoice-1"), json=body)
    assert first.status_code == 200 and replay.json()["invoice_id"] == first.json()["invoice_id"]
    invoice_id = first.json()["invoice_id"]
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Invoice)) == 1
    assert client.get(f"/v1/invoices/{invoice_id}", headers=auth("radpath")).status_code == 404
    assert client.get("/v1/invoices", headers=auth("radpath")).json()["invoices"] == []
    correction = client.post(f"/v1/invoices/{invoice_id}/adjustments",
                             headers=auth("oncopilot", "credit-1"),
                             json={"amount": "-0.01", "reason": "Simulated service credit"})
    assert correction.status_code == 200
    assert correction.json()["correction_of_invoice_id"] == invoice_id
    changed_replay = client.post(f"/v1/invoices/{invoice_id}/adjustments",
                                 headers=auth("oncopilot", "credit-1"),
                                 json={"amount": "-0.02", "reason": "Different simulated credit"})
    assert changed_replay.status_code == 409
    assert client.get(f"/v1/invoices/{invoice_id}/reconciliation", headers=auth()).json()["balanced"] is True


def test_unknown_tokens_propagate_through_estimate_and_invoice(platform):
    client, app = platform
    add_run(app, attempts=[tokens(input_tokens=None)])
    result = estimate(client)
    assert result["estimated_upstream_cost"] is None
    assert result["illustrative_customer_charge"] is None
    assert result["unknown_upstream_attempts"] == 1
    invoice = client.post("/v1/invoices", headers=auth("oncopilot", "unknown-1"),
                          json={"reporting_period_start": START, "reporting_period_end": END}).json()
    assert invoice["estimated_upstream_cost"] is None
    assert invoice["illustrative_customer_charge"] is None


def test_pricing_revision_selection_snapshot_and_immutability(platform):
    client, app = platform
    add_run(app, attempts=[tokens()])
    october = client.post("/v1/invoices", headers=auth("oncopilot", "october"),
                          json={"reporting_period_start": START, "reporting_period_end": END}).json()
    with app.state.sessions.begin() as session:
        session.add(RateCard(
            id="anthropic-claude-sonnet-5-5-2026-11-01", provider="anthropic", model_id="claude-sonnet-5-5",
            effective_from="2026-11-01T00:00:00+00:00", effective_to=None, currency="USD",
            input_per_million="3", output_per_million="12", cache_write_5m_per_million="3.75",
            cache_write_1h_per_million="6", cache_read_per_million="0.15",
            source_name="Test revision", source_url="https://example.invalid/test-rate",
        ))
    assert list(october["pricing_snapshot"]["rate_cards"]) == ["anthropic-claude-sonnet-5-5-2026-09-28"]
    with app.state.sessions() as session:
        assert rate_card_for(session, "claude-sonnet-5-5", "2026-11-15T00:00:00+00:00").id.endswith("2026-11-01")
        plan = session.get(PricingPlan, "illustrative-payg-2026-10-01")
        plan.usage_multiplier = "9"
        with pytest.raises(ValueError, match="immutable"):
            session.flush()


def test_unit_economics_and_partner_endpoints_are_tenant_scoped(platform):
    client, app = platform
    add_run(app, "oncopilot", attempts=[tokens()])
    add_run(app, "radpath", attempts=[tokens()])
    params = {"reporting_period_start": START, "reporting_period_end": END}
    onco = client.get("/v1/partner-attribution", headers=auth(), params=params).json()
    rad = client.get("/v1/partner-attribution", headers=auth("radpath"), params=params).json()
    economics = client.get("/v1/unit-economics", headers=auth(), params=params).json()
    assert onco["organization_id"] == "oncopilot" and onco["partner_id"] is None
    assert rad["organization_id"] == "radpath" and rad["partner_id"] == "meddata-partners"
    assert "radpath" not in str(economics)


def test_m3_schema_compiles_for_postgres_offline():
    statements = []
    engine = create_mock_engine("postgresql+psycopg://", lambda sql, *a, **kw: statements.append(str(sql.compile(dialect=engine.dialect))))
    Base.metadata.create_all(engine)
    assert any("m3_rate_cards" in statement for statement in statements)
    assert any("m3_invoice_lines" in statement for statement in statements)
