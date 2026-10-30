import socket
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chartground.platform_m2.database import Run
from chartground.platform_m2.seed import seed as seed_m2
from chartground.platform_m3.seed import seed as seed_m3
from chartground.platform_m4.seed import seed as seed_m4
from chartground.platform_m5.analytics import (developer_adoption,
                                               monetization_summary,
                                               spending_summary,
                                               summarize_usage)
from chartground.platform_m5.api import create_app
from chartground.platform_m5.client import PlatformAPI
from chartground.platform_m5.models import DeveloperLifecycleEvent

KEYS = {"oncopilot": "m5-test-onco-" + "a" * 32, "radpath": "m5-test-rad-" + "b" * 32}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    original_connect = socket.socket.connect

    def blocked(sock, address):
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(sock, address)
        raise AssertionError("Network is forbidden in M5 tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")


class FakeAdapter:
    def __init__(self):
        self.calls = 0

    def __call__(self, request):
        self.calls += 1
        return {
            "case_id": request["case_id"], "provider": request["provider"], "status": "success",
            "action": "answer", "action_reason": "Offline test.", "answer_source": "offline_fake",
            "answer": "Offline test.", "cited_evidence_ids": [], "error": None,
            "usage": {"attempts": [{
                "attempt": 1, "timestamp": "2026-10-28T00:00:00+00:00", "max_tokens": 1000,
                "api_status": "success", "generation_status": "parsed",
                "model_id": "claude-sonnet-5-5", "request_id": "offline-m5",
                "stop_reason": "end_turn", "latency_ms": 1,
                "input_tokens": 100, "output_tokens": 10,
                "cache_creation_tokens": 0, "cache_read_tokens": 0,
            }]},
        }


@pytest.fixture
def platform(tmp_path):
    fake = FakeAdapter()
    app = create_app("sqlite:///" + (tmp_path / "m5.sqlite3").as_posix(), adapter=fake,
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


def run_body(org="oncopilot"):
    return {"case_id": "cg-syn-012" if org == "oncopilot" else "cg-syn-013",
            "question": "Offline analytics test.",
            "agent_id": "onco-agent" if org == "oncopilot" else "rad-agent",
            "provider": "claude"}


def test_usage_calculations_keep_unknown_tokens_visible():
    usage = {"attempts": [
        {"input_tokens": 10, "output_tokens": 3, "cache_creation_tokens": 0,
         "cache_read_tokens": 0, "generation_status": "parsed", "model_id": "model-a"},
        {"input_tokens": None, "output_tokens": 2, "cache_creation_tokens": None,
         "cache_read_tokens": None, "api_status": "failed", "model_id": "model-a"},
    ]}
    runs = [{"status": "success", "agent_id": "agent-a"}, {"status": "fallback", "agent_id": "agent-a"}]
    result = summarize_usage(usage, runs)
    assert result["reported_token_totals"]["input_tokens"] == 10
    assert result["unknown_token_counts"]["input_tokens"] == 1
    assert result["measured_request_count"] == 2
    assert result["attempt_statuses"] == {"parsed": 1, "failed": 1}


def test_adoption_does_not_fabricate_conversion_or_retention():
    runs = [{"run_id": "one", "developer_id": "dev", "status": "success",
             "created_at": "2026-10-01T00:00:00+00:00"}]
    result = developer_adoption(runs, [])
    assert result["developers"][0]["requests"] == 1
    assert result["activation_rate"] is None and result["retention_rate"] is None
    assert "Insufficient" in result["activation_note"]
    assert result["developers"][0]["activated_at"] is None


def test_cost_revenue_and_spending_labels_are_explicit():
    invoices = [{"illustrative_customer_charge": "10", "simulated_partner_payout": "2"}]
    economics = {"estimated_upstream_cost": "1.5", "simulated_gross_margin": "6.5"}
    monetization = monetization_summary(invoices, economics)
    spending = spending_summary(
        {"held_spend": "3", "unreconciled_requests": 1},
        [{"status": "reconciled", "actual_cost": "1"},
         {"status": "unreconciled", "actual_cost": None}],
        [{}], [{"event_type": "preflight_denial"}],
    )
    assert monetization["estimated_upstream_cost"] == Decimal("1.5")
    assert "Illustrative" in monetization["labels"]["simulated_customer_charges"]
    assert "no payment" in monetization["labels"]["simulated_partner_payouts"]
    assert spending["unknown_cost_count"] == 1 and spending["denial_count"] == 1
    assert "not treated as zero" in spending["labels"]["unknown_cost"]


def test_future_success_records_lifecycle_once_and_replay_is_idempotent(platform):
    client, app, fake = platform
    first = client.post("/v1/runs", headers=headers(key="future-success"), json=run_body())
    replay = client.post("/v1/runs", headers=headers(key="future-success"), json=run_body())
    assert first.status_code == 200 and replay.status_code == 200 and fake.calls == 1
    events = client.get("/v1/analytics/lifecycle-events", headers=headers()).json()["events"]
    assert {row["event_type"] for row in events} == {
        "api_request_approved", "api_call_succeeded",
        "first_successful_api_call", "developer_activated",
    }
    assert len(events) == 4
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(DeveloperLifecycleEvent)) == 4


def test_lifecycle_and_run_analytics_are_tenant_isolated(platform):
    client, _, _ = platform
    onco = client.post("/v1/runs", headers=headers(key="onco-run"), json=run_body()).json()["run_id"]
    rad = client.post("/v1/runs", headers=headers("radpath", "rad-run"), json=run_body("radpath")).json()["run_id"]
    onco_runs = client.get("/v1/analytics/runs", headers=headers()).json()["runs"]
    rad_runs = client.get("/v1/analytics/runs", headers=headers("radpath")).json()["runs"]
    assert {row["run_id"] for row in onco_runs} == {onco}
    assert {row["run_id"] for row in rad_runs} == {rad}
    assert {row["developer_id"] for row in client.get("/v1/analytics/lifecycle-events", headers=headers()).json()["events"]} == {"onco-dev"}
    assert {row["developer_id"] for row in client.get("/v1/analytics/lifecycle-events", headers=headers("radpath")).json()["events"]} == {"rad-dev"}


def test_existing_runs_are_not_backfilled_as_lifecycle_events(tmp_path):
    database_url = "sqlite:///" + (tmp_path / "history.sqlite3").as_posix()
    app = create_app(database_url, adapter=FakeAdapter(), allow_claude=True, seed_defaults=False)
    seed_m2(app.state.sessions, KEYS)
    seed_m3(app.state.sessions)
    seed_m4(app.state.sessions)
    with app.state.sessions.begin() as session:
        session.add(Run(
            id=str(uuid4()), organization_id="oncopilot", developer_id="onco-dev",
            agent_id="onco-agent", partner_id=None, idempotency_key="historical",
            fingerprint="f" * 64, case_id="cg-syn-012", provider="mock",
            status="fallback", created_at="2026-09-01T00:00:00+00:00", response={},
        ))
    before = None
    with app.state.sessions() as session:
        before = session.scalar(select(func.count()).select_from(Run))
        assert session.scalar(select(func.count()).select_from(DeveloperLifecycleEvent)) == 0
    app.state.engine.dispose()
    restarted = create_app(database_url, adapter=FakeAdapter(), allow_claude=True, seed_defaults=False)
    with restarted.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Run)) == before
        assert session.scalar(select(func.count()).select_from(DeveloperLifecycleEvent)) == 0
    restarted.state.engine.dispose()


def test_analytics_runs_do_not_expose_questions_or_answer_text(platform):
    client, _, _ = platform
    client.post("/v1/runs", headers=headers(key="redacted-analytics"), json=run_body())
    payload = client.get("/v1/analytics/runs", headers=headers()).json()
    serialized = str(payload).lower()
    assert "question" not in serialized and "offline test." not in serialized


def test_dashboard_client_redacts_key_and_is_read_only():
    secret = "secret-value-that-must-not-appear"
    client = PlatformAPI("http://127.0.0.1:8000", secret)
    assert secret not in repr(client) and "[REDACTED]" in repr(client)
    public_methods = {name for name in dir(client) if not name.startswith("_")}
    assert "get" in public_methods and not {"post", "put", "patch", "delete"}.intersection(public_methods)
    dashboard = (ROOT / "scripts" / "m5_dashboard.py").read_text(encoding="utf-8")
    assert ".post(" not in dashboard and ".put(" not in dashboard and ".delete(" not in dashboard


def test_m5_api_adds_only_get_analytics_routes(platform):
    _, app, _ = platform
    routes = {(method, route.path) for route in app.routes for method in getattr(route, "methods", set())}
    analytics = {(method, path) for method, path in routes if path.startswith("/v1/analytics/")}
    assert analytics == {("GET", "/v1/analytics/runs"), ("GET", "/v1/analytics/lifecycle-events")}
