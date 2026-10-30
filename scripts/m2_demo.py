"""Run two mock-only requests against the local M2 server; never print keys."""
import json
import sys
from pathlib import Path
from uuid import uuid4

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from chartground.platform_m2.database import LOCAL


def main():
    keys = json.loads((LOCAL / "credentials.json").read_text(encoding="utf-8"))
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=200, trust_env=False) as client:
        for org, case, agent in (("oncopilot", "cg-syn-012", "onco-agent"), ("radpath", "cg-syn-013", "rad-agent")):
            headers = {"Authorization": "Bearer " + keys[org], "Idempotency-Key": str(uuid4())}
            body = dict(case_id=case, agent_id=agent, question="What medication conflicts are present?", provider="mock")
            response = client.post("/v1/runs", headers=headers, json=body)
            response.raise_for_status()
            result = response.json()
            replay = client.post("/v1/runs", headers=headers, json=body)
            replay.raise_for_status()
            assert replay.json()["run_id"] == result["run_id"]
            usage = client.get("/v1/usage", headers=headers)
            usage.raise_for_status()
            print(json.dumps({"organization": org, "run_id": result["run_id"], "partner": result["partner_id"],
                              "action": result["result"]["action"], "idempotent_replay": True,
                              "reported_tokens": usage.json()["reported_token_totals"]}))


if __name__ == "__main__":
    main()
