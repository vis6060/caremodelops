"""Offline spending-control demo using a temporary database and fake usage."""

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chartground.platform_m2.seed import seed as seed_m2
from chartground.platform_m3.seed import seed as seed_m3
from chartground.platform_m4.api import create_app
from chartground.platform_m4.seed import seed as seed_m4

KEYS = {"oncopilot": "m4-demo-onco-" + "a" * 32, "radpath": "m4-demo-rad-" + "b" * 32}


class OfflineAdapter:
    def __init__(self):
        self.calls = 0

    def __call__(self, request):
        self.calls += 1
        return {
            "case_id": request["case_id"], "provider": request["provider"], "status": "success",
            "action": "answer", "action_reason": "Offline demo response.",
            "answer_source": "offline_fake_adapter", "answer": "Offline demo response.",
            "cited_evidence_ids": [], "error": None,
            "usage": {"attempts": [{
                "attempt": 1, "timestamp": "2026-10-28T00:00:00+00:00", "max_tokens": 4096,
                "api_status": "success", "generation_status": "unusable",
                "model_id": "claude-sonnet-5-5", "request_id": "offline-demo",
                "stop_reason": None, "latency_ms": 0, "input_tokens": None,
                "output_tokens": None, "cache_creation_tokens": None, "cache_read_tokens": None,
            }]},
        }


def main():
    with TemporaryDirectory(prefix="chartground-m4-") as directory:
        adapter = OfflineAdapter()
        url = "sqlite:///" + (Path(directory) / "demo.sqlite3").as_posix()
        app = create_app(url, adapter=adapter, allow_claude=True, seed_defaults=False)
        seed_m2(app.state.sessions, KEYS)
        seed_m3(app.state.sessions)
        seed_m4(app.state.sessions)
        auth = {"Authorization": "Bearer " + KEYS["oncopilot"]}
        body = {"case_id": "cg-syn-012", "question": "Offline budget-control demo.",
                "agent_id": "onco-agent", "provider": "claude"}
        with TestClient(app) as client:
            preflight = client.post("/v1/spending-controls/preflight", headers=auth,
                                    json={"agent_id": "onco-agent"}).json()
            policy = {
                "monthly_spend_limit": preflight["estimated_max_cost"],
                "daily_request_limit": 10, "monthly_request_limit": 100,
                "assumed_input_tokens": 8000, "max_output_tokens": 4096,
                "max_attempts": 2, "model_id": "claude-sonnet-5-5",
            }
            client.put("/v1/spending-controls/organization", headers=auth, json=policy).raise_for_status()
            client.put("/v1/spending-controls/agents/onco-agent", headers=auth, json=policy).raise_for_status()
            approved_headers = {**auth, "Idempotency-Key": "m4-demo-approved"}
            denied_headers = {**auth, "Idempotency-Key": "m4-demo-denied"}
            approved = client.post("/v1/runs", headers=approved_headers, json=body)
            replay = client.post("/v1/runs", headers=approved_headers, json=body)
            denied = client.post("/v1/runs", headers=denied_headers, json=body)
            alerts = client.get("/v1/spending-controls/alerts", headers=auth).json()["alerts"]
            status = client.get("/v1/spending-controls/status", headers=auth).json()
            print(json.dumps({
                "approved": approved.status_code == 200,
                "approved_run_id": approved.json()["run_id"],
                "alert_thresholds": sorted({row["threshold_percent"] for row in alerts}),
                "budget_rejection": denied.status_code == 429,
                "rejection_reason": denied.json()["result"]["spending_control"]["reason"],
                "idempotent_replay": replay.json()["run_id"] == approved.json()["run_id"],
                "subprocess_dispatches": adapter.calls,
                "held_spend": status["held_spend"],
                "unreconciled_requests": status["unreconciled_requests"],
                "paid_api_calls": 0,
            }, indent=2))
        app.state.engine.dispose()


if __name__ == "__main__":
    main()
