import socket
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_mock_engine, func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chartground.platform_m2.database import Base
from chartground.platform_m2.seed import seed as seed_m2
from chartground.platform_m3.models import RateCard
from chartground.platform_m3.seed import seed as seed_m3
from chartground.platform_m4.api import create_app
from chartground.platform_m4.models import SpendAudit, SpendReservation
from chartground.platform_m4.seed import seed as seed_m4

KEYS = {"oncopilot": "m4-test-onco-" + "a" * 32, "radpath": "m4-test-rad-" + "b" * 32}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    original_connect = socket.socket.connect

    def blocked(sock, address):
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(sock, address)
        raise AssertionError("Network is forbidden in M4 tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")


class FakeAdapter:
    def __init__(self, mode="known"):
        self.mode = mode
        self.calls = []
        self.lock = Lock()

    def __call__(self, request):
        with self.lock:
            self.calls.append(request)
        if self.mode == "raise":
            raise RuntimeError("local fake failure")
        attempts = []
        status, source = "success", "claude"
        if self.mode != "no_attempts":
            known = self.mode != "unknown"
            attempts = [dict(
                attempt=1, timestamp="2026-10-28T00:00:00+00:00", max_tokens=1000,
                api_status="failed" if self.mode == "failed" else "success",
                generation_status="unusable" if self.mode == "failed" else "parsed",
                model_id="claude-sonnet-5-5", request_id="local-fake-request",
                stop_reason="end_turn", latency_ms=1,
                input_tokens=100 if known else None, output_tokens=10 if known else None,
                cache_creation_tokens=0 if known else None, cache_read_tokens=0 if known else None,
            )]
        if self.mode in {"failed", "no_attempts"}:
            status, source = "fallback", "deterministic_fallback"
        return {
            "case_id": request["case_id"], "provider": request["provider"], "status": status,
            "action": "answer" if status == "success" else "escalate",
            "action_reason": "Offline fake result.", "answer_source": source,
            "answer": "Offline fake result.", "usage": {"attempts": attempts},
            "cited_evidence_ids": [], "error": None,
        }


@pytest.fixture
def platform(tmp_path):
    fake = FakeAdapter()
    app = create_app("sqlite:///" + (tmp_path / "m4.sqlite3").as_posix(), adapter=fake,
                     allow_claude=True, seed_defaults=False)
    seed_m2(app.state.sessions, KEYS)
    seed_m3(app.state.sessions)
    seed_m4(app.state.sessions)
    with TestClient(app) as client:
        yield client, app, fake
    app.state.engine.dispose()


def headers(org="oncopilot", key=None):
    result = {"Authorization": "Bearer " + KEYS[org]}
    if key:
        result["Idempotency-Key"] = key
    return result


def run_body(org="oncopilot", provider="claude"):
    return {
        "case_id": "cg-syn-012" if org == "oncopilot" else "cg-syn-013",
        "question": "Summarize the synthetic record.",
        "agent_id": "onco-agent" if org == "oncopilot" else "rad-agent",
        "provider": provider,
    }


def policy(limit="1.00", daily=10, monthly=100, input_tokens=1000,
           output_tokens=1000, attempts=1, model="claude-sonnet-5-5"):
    return {
        "monthly_spend_limit": limit, "daily_request_limit": daily,
        "monthly_request_limit": monthly, "assumed_input_tokens": input_tokens,
        "max_output_tokens": output_tokens, "max_attempts": attempts, "model_id": model,
    }


def set_limits(client, limit="1.00", daily=10, monthly=100, **kwargs):
    values = policy(limit, daily, monthly, **kwargs)
    assert client.put("/v1/spending-controls/organization", headers=headers(), json=values).status_code == 200
    assert client.put("/v1/spending-controls/agents/onco-agent", headers=headers(), json=values).status_code == 200
    return values


def test_preflight_uses_effective_m3_rate_and_bounded_attempts(platform):
    client, _, _ = platform
    set_limits(client, input_tokens=1000, output_tokens=1000, attempts=2)
    result = client.post("/v1/spending-controls/preflight", headers=headers(),
                         json={"agent_id": "onco-agent"}).json()
    assert result["known"] is True
    assert result["rate_card_version"] == "anthropic-claude-sonnet-5-5-2026-09-28"
    assert result["estimated_max_cost"] == "0.03400000"
    assert [row["max_output_tokens"] for row in result["attempts"]] == [1000, 2000]


def test_approved_request_reconciles_actual_usage_and_replay_is_idempotent(platform):
    client, app, fake = platform
    set_limits(client)
    first = client.post("/v1/runs", headers=headers(key="approved-1"), json=run_body())
    replay = client.post("/v1/runs", headers=headers(key="approved-1"), json=run_body())
    assert first.status_code == 200 and replay.status_code == 200
    assert first.json()["run_id"] == replay.json()["run_id"] and len(fake.calls) == 1
    reservations = client.get("/v1/spending-controls/reservations", headers=headers()).json()["reservations"]
    assert len(reservations) == 1
    assert reservations[0]["status"] == "reconciled"
    assert reservations[0]["actual_cost"] == "0.00030000"
    assert reservations[0]["held_cost"] == "0.00030000"
    with app.state.sessions() as session:
        events = set(session.scalars(select(SpendAudit.event_type)))
    assert {"preflight_approval", "reservation_created", "reconciliation", "budget_change"}.issubset(events)


def test_alerts_hard_rejection_and_rejected_replay_never_dispatch(platform):
    client, _, fake = platform
    fake.mode = "unknown"
    set_limits(client, limit="0.01200000")
    approved = client.post("/v1/runs", headers=headers(key="threshold"), json=run_body())
    assert approved.status_code == 200 and len(fake.calls) == 1
    alerts = client.get("/v1/spending-controls/alerts", headers=headers()).json()["alerts"]
    assert {row["threshold_percent"] for row in alerts if row["scope_type"] == "organization"} == {50, 80, 100}
    denied = client.post("/v1/runs", headers=headers(key="over-budget"), json=run_body())
    replay = client.post("/v1/runs", headers=headers(key="over-budget"), json=run_body())
    assert denied.status_code == replay.status_code == 429
    assert denied.json()["run_id"] == replay.json()["run_id"]
    assert len(fake.calls) == 1
    assert "budget exceeded" in denied.json()["result"]["spending_control"]["reason"].lower()


def test_concurrent_reservations_cannot_overspend(platform):
    client, _, fake = platform
    fake.mode = "unknown"
    set_limits(client, limit="0.01200000")

    def submit(number):
        return client.post("/v1/runs", headers=headers(key=f"concurrent-{number}"), json=run_body())

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(submit, (1, 2)))
    assert sorted(response.status_code for response in responses) == [200, 429]
    assert len(fake.calls) == 1


def test_agent_budget_quota_boundary_and_tenant_isolation(platform):
    client, _, fake = platform
    org = policy(limit="1.00", daily=10, monthly=100)
    agent = policy(limit="0.01200000", daily=1, monthly=1)
    client.put("/v1/spending-controls/organization", headers=headers(), json=org).raise_for_status()
    client.put("/v1/spending-controls/agents/onco-agent", headers=headers(), json=agent).raise_for_status()
    fake.mode = "unknown"
    first = client.post("/v1/runs", headers=headers(key="agent-boundary"), json=run_body())
    assert first.status_code == 200
    second = client.post("/v1/runs", headers=headers(key="agent-quota"), json=run_body())
    assert second.status_code == 429 and len(fake.calls) == 1
    assert "agent daily" in second.json()["result"]["spending_control"]["reason"].lower()
    assert client.get("/v1/spending-controls/agents/rad-agent/status", headers=headers()).status_code == 404
    assert client.put("/v1/spending-controls/agents/rad-agent", headers=headers(), json=agent).status_code == 404
    assert client.get("/v1/spending-controls/reservations", headers=headers("radpath")).json()["reservations"] == []


@pytest.mark.parametrize("mode,expected_status,actual_known", [
    ("unknown", 200, False), ("no_attempts", 200, False), ("raise", 502, False), ("failed", 200, True),
])
def test_missing_failed_and_indeterminate_usage_preserve_cost(platform, mode, expected_status, actual_known):
    client, _, fake = platform
    set_limits(client)
    fake.mode = mode
    response = client.post("/v1/runs", headers=headers(key=f"mode-{mode}"), json=run_body())
    assert response.status_code == expected_status
    row = client.get("/v1/spending-controls/reservations", headers=headers()).json()["reservations"][0]
    if actual_known:
        assert row["status"] == "reconciled" and row["actual_cost"] == "0.00030000"
        assert row["reconciliation"]["failed_calls_preserved"] is True
    else:
        assert row["status"] == "unreconciled" and row["actual_cost"] is None
        assert row["held_cost"] == row["reserved_cost"] == "0.01200000"


def test_pricing_revision_is_snapshotted_in_reservation(platform):
    client, app, fake = platform
    with app.state.sessions.begin() as session:
        session.add(RateCard(
            id="m4-test-sonnet-rate", provider="anthropic", model_id="claude-sonnet-5-5",
            effective_from="2026-10-28T00:00:00+00:00", effective_to=None, currency="USD",
            input_per_million="4", output_per_million="20", cache_write_5m_per_million="5",
            cache_write_1h_per_million="8", cache_read_per_million="0.20",
            source_name="Offline test revision", source_url="https://example.invalid/m4-test",
        ))
    set_limits(client, limit="1.00")
    fake.mode = "unknown"
    result = client.post("/v1/runs", headers=headers(key="revision"), json=run_body())
    assert result.status_code == 200
    row = client.get("/v1/spending-controls/reservations", headers=headers()).json()["reservations"][0]
    assert row["rate_card_version"] == "m4-test-sonnet-rate"
    assert row["reserved_cost"] == "0.02400000"


def test_unknown_model_denied_before_dispatch(platform):
    client, _, fake = platform
    set_limits(client)
    body = {**run_body(), "model": "unknown-local-model"}
    response = client.post("/v1/runs", headers=headers(key="unknown-model"), json=body)
    assert response.status_code == 429 and fake.calls == []
    assert "not allowed" in response.json()["result"]["spending_control"]["reason"].lower()


def test_mock_provider_reconciles_to_zero_without_paid_usage(platform):
    client, _, fake = platform
    set_limits(client)
    fake.mode = "no_attempts"
    response = client.post("/v1/runs", headers=headers(key="mock-zero"), json=run_body(provider="mock"))
    assert response.status_code == 200
    row = client.get("/v1/spending-controls/reservations", headers=headers()).json()["reservations"][0]
    assert row["status"] == "reconciled" and row["actual_cost"] == "0.00000000"
    assert fake.calls[0]["provider"] == "mock"


def test_m4_schema_compiles_for_postgres_offline():
    statements = []
    engine = create_mock_engine("postgresql+psycopg://", lambda sql, *a, **kw: statements.append(str(sql.compile(dialect=engine.dialect))))
    Base.metadata.create_all(engine)
    assert any("m4_budget_policies" in statement for statement in statements)
    assert any("m4_spend_reservations" in statement for statement in statements)
    assert any("m4_spend_audit" in statement for statement in statements)
