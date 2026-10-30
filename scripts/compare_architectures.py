"""Compare ChartGround answer architectures for one case/question."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chartground.agent import ToolAgentService
from chartground.evidence_store import DEFAULT_CASES_ROOT


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare ChartGround RAG, tool-agent, and verified-agent outputs.")
    parser.add_argument("--cases-root", default=str(DEFAULT_CASES_ROOT))
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--question", required=True)
    args = parser.parse_args()

    service = ToolAgentService(cases_root=args.cases_root)
    print("architecture\taction\tcitations\tclaims\tunsupported\tconflicts\tlatency_ms")
    for architecture in ("rag", "tool_agent", "verified_agent"):
        response = service.answer_question(args.case_id, args.question, architecture=architecture)
        print(
            f"{architecture}\t{response.action}\t{len(response.cited_evidence_ids)}\t"
            f"{len(response.claims)}\t{len(response.unsupported_claims)}\t"
            f"{len(response.conflicts)}\t{response.latency_ms}"
        )


if __name__ == "__main__":
    main()
