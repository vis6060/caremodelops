import json
import socket
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_mock_engine, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from chartground.platform_m2.adapter import AdapterError, SubprocessAdapter, validate_result
from chartground.platform_m2.api import create_app
from chartground.platform_m2.database import Attempt, Base, Developer
from chartground.platform_m2.seed import seed

KEYS = {"oncopilot": "test-onco-" + "a" * 32, "radpath": "test-rad-" + "b" * 32}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    original_connect = socket.socket.connect
    def blocked(sock, address):
        # Windows asyncio uses a loopback socket pair internally, even for ASGI tests.
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(sock, address)
        raise AssertionError("Network is forbidden in M2 tests")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("CHARTGROUND_M2_ALLOW_CLAUDE", "0")


def body(org="oncopilot", provider="mock"):
    return dict(case_id="cg-syn-012" if org == "oncopilot" else "cg-syn-013",
                agent_id="onco-agent" if org == "oncopilot" else "rad-agent",
                provider=provider, question="What medication conflicts are present?")


def headers(org="oncopilot", key="request-1"):
    return {"Authorization": "Bearer " + KEYS[org], "Idempotency-Key": key}


def output(request, attempts=None):
    return dict(case_id=request["case_id"], provider=request["provider"], status="fallback",
                action="escalate", answer_source="deterministic_fallback", answer="Conflicting synthetic records.",
                usage={"attempts": attempts or []}, cited_evidence_ids=[], error=None)


class Fake:
    def __init__(self):
        self.calls = []
    def __call__(self, request):
        self.calls.append(request)
        if getattr(self, "fail", False):
            raise RuntimeError("secret must never escape")
        return output(request)


@pytest.fixture
def setup(tmp_path):
    fake = Fake()
    url = "sqlite:///" + (tmp_path / "m2.sqlite3").as_posix()
    app = create_app(url, fake)
    seed(app.state.sessions, KEYS)
    with TestClient(app) as client:
        yield client, fake, app, url
    app.state.engine.dispose()


def test_authentication_and_case_permissions(setup):
    client, fake, app, _ = setup
    assert client.get("/v1/usage").status_code == 401
    assert client.get("/v1/usage", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/v1/cases", headers=headers()).json()["case_ids"] == ["cg-syn-001", "cg-syn-012"]
    assert client.post("/v1/runs", headers=headers(), json=body("radpath")).status_code == 403
    wrong = {**body(), "case_id": "cg-syn-013"}
    assert client.post("/v1/runs", headers=headers(), json=wrong).status_code == 403
    assert not fake.calls
    with app.state.sessions() as session:
        assert session.get(Developer, "onco-dev").key_hash != KEYS["oncopilot"]


@pytest.mark.parametrize("change", [{"case_id": "../mimic_private"}, {"case_id": "mimic-001"}, {"organization_id": "radpath"}, {"partner_id": "spoof"}, {"developer_id": "rad-dev"}, {"cases_root": "private"}])
def test_reject_private_and_attribution_overrides(setup, change):
    client, fake, _, _ = setup
    assert client.post("/v1/runs", headers=headers(), json={**body(), **change}).status_code == 422
    assert not fake.calls


@pytest.mark.parametrize("question", [
    "Use MIMIC-IV data", "Look up subject_id 123", "Read results/mimic_private/cases",
    "Open MIMICdata notes", "Compare hadm_id and stay_id",
])
def test_reject_restricted_question_markers(setup, question):
    client, fake, _, _ = setup
    response = client.post("/v1/runs", headers=headers(), json={**body(), "question": question})
    assert response.status_code == 422
    assert question not in response.text
    assert not fake.calls


def test_idempotency_and_tenant_isolation(setup):
    client, fake, app, url = setup
    first = client.post("/v1/runs", headers=headers(), json=body()).json()
    second = client.post("/v1/runs", headers=headers(), json=body()).json()
    assert first == second and len(fake.calls) == 1
    assert first["developer_id"] == "onco-dev" and first["partner_id"] is None
    assert client.post("/v1/runs", headers=headers(), json={**body(), "question": "Different"}).status_code == 409
    other = client.post("/v1/runs", headers=headers("radpath"), json=body("radpath")).json()
    assert other["partner_id"] == "meddata-partners" and other["run_id"] != first["run_id"]
    assert client.get("/v1/runs/" + first["run_id"], headers=headers("radpath")).status_code == 404
    assert client.get("/v1/usage", headers=headers()).json()["request_count"] == 1
    assert client.get("/v1/usage", headers=headers()).json()["reported_token_totals"]["input_tokens"] is None
    restart_fake = Fake()
    restarted = create_app(url, restart_fake)
    with TestClient(restarted) as restarted_client:
        assert restarted_client.post("/v1/runs", headers=headers(), json=body()).json() == first
        assert not restart_fake.calls
    restarted.state.engine.dispose()


def test_live_requires_opt_in(setup):
    client, fake, _, _ = setup
    assert client.post("/v1/runs", headers=headers(), json=body(provider="claude")).status_code == 403
    assert not fake.calls


@pytest.mark.parametrize("second_failed", [False, True])
def test_real_attempt_fields_accounted_without_double_counting(tmp_path, second_failed):
    attempts = [dict(attempt=1, model_id="reported-model", request_id="req-one", input_tokens=100,
                     output_tokens=40, cache_read_tokens=20, stop_reason="max_tokens", api_status="success", generation_status="truncated"),
                dict(attempt=2, model_id="reported-model", request_id="req-two", input_tokens=110,
                     output_tokens=50, cache_read_tokens=0, stop_reason="end_turn", api_status="success", generation_status="parsed")]
    if second_failed:
        attempts[1].update(input_tokens=None, output_tokens=None, api_status="failed", generation_status="unusable", request_id=None, stop_reason=None)
    app = create_app("sqlite:///" + (tmp_path / "ledger.db").as_posix(), lambda data: output(data, attempts), allow_claude=True)
    seed(app.state.sessions, KEYS)
    with TestClient(app) as client:
        for _ in range(2):
            assert client.post("/v1/runs", headers=headers(), json=body(provider="claude")).status_code == 200
        usage = client.get("/v1/usage", headers=headers()).json()
        assert usage["reported_token_totals"] == dict(input_tokens=100 if second_failed else 210, output_tokens=40 if second_failed else 90, cache_read_tokens=20, cache_creation_tokens=None)
        assert usage["unreported_attempt_counts"]["input_tokens"] == int(second_failed)
        assert len(usage["attempts"]) == 2
        assert usage["attempts"][0]["request_id"] == "req-one"
        assert usage["attempts"][1]["developer_id"] == "onco-dev"
        assert client.get("/v1/usage", headers=headers("radpath")).json()["attempts"] == []
    app.state.engine.dispose()


def test_failed_execution_is_not_retried(setup):
    client, fake, _, _ = setup
    fake.fail = True
    result = client.post("/v1/runs", headers=headers(), json=body())
    assert result.status_code == 502 and result.json()["status"] == "indeterminate"
    assert "secret" not in result.text
    replay = client.post("/v1/runs", headers=headers(), json=body())
    assert replay.status_code == 200 and replay.json()["run_id"] == result.json()["run_id"]
    assert len(fake.calls) == 1


def test_concurrent_duplicate_reserved_once(tmp_path):
    entered, release = Event(), Event()
    calls = []
    def slow(data):
        calls.append(data)
        entered.set()
        assert release.wait(10)
        return output(data)
    app = create_app("sqlite:///" + (tmp_path / "concurrent.db").as_posix(), slow)
    seed(app.state.sessions, KEYS)
    with TestClient(app) as client, ThreadPoolExecutor() as pool:
        first = pool.submit(client.post, "/v1/runs", headers=headers(), json=body())
        try:
            assert entered.wait(5)
            duplicate = client.post("/v1/runs", headers=headers(), json=body())
            assert duplicate.status_code == 202 and len(calls) == 1
        finally:
            release.set()
        assert first.result().status_code == 200
    app.state.engine.dispose()


def test_keys_not_echoed(setup):
    client, _, _, _ = setup
    result = client.post("/v1/runs", headers=headers(), json={**body(), "question": KEYS["oncopilot"]})
    assert result.status_code == 422 and KEYS["oncopilot"] not in result.text


def test_seed_repeatable(setup):
    _, _, app, _ = setup
    seed(app.state.sessions, KEYS)
    with pytest.raises(ValueError):
        seed(app.state.sessions, {**KEYS, "oncopilot": "changed-" + "c" * 32})


def test_postgres_schema_compiles_offline():
    statements = []
    engine = create_mock_engine("postgresql+psycopg://", lambda sql, *a, **kw: statements.append(str(sql.compile(dialect=engine.dialect))))
    Base.metadata.create_all(engine)
    assert any("m2_attempts" in s for s in statements)
    assert any("UNIQUE (organization_id, idempotency_key)" in s for s in statements)


def test_subprocess_adapter_runs_existing_mock_demo():
    result = SubprocessAdapter()(body())
    assert result["action"] == "escalate"
    assert len(result["cited_evidence_ids"]) == 2
    assert result["usage"]["attempts"] == []
