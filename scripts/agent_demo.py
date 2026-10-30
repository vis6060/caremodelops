"""Run ChartGround RAG or tool-agent demos."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chartground.agent import ToolAgentService
from chartground.evidence_store import DEFAULT_CASES_ROOT


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ChartGround agent demos.")
    parser.add_argument("--cases-root", default=str(DEFAULT_CASES_ROOT))
    parser.add_argument("--case-id")
    parser.add_argument("--auto-rich-case", action="store_true")
    parser.add_argument("--list-cases", action="store_true")
    parser.add_argument("--architecture", choices=["rag", "tool_agent", "verified_agent"], default="tool_agent")
    parser.add_argument("--question", default="What changed during this encounter?")
    args = parser.parse_args()

    service = ToolAgentService(cases_root=args.cases_root)
    if args.list_cases:
        for case_id in service.store.list_cases():
            patient_id = service.store.get_case(case_id)["patient_id"]
            print(f"{case_id}\t{patient_id}")
        return

    case_id = args.case_id
    if args.auto_rich_case:
        case_id = service.select_auto_rich_case()
    if not case_id:
        raise SystemExit("Provide --case-id, --auto-rich-case, or --list-cases.")

    response = service.answer_question(case_id, args.question, architecture=args.architecture)
    print(f"Case: {response.case_id}")
    print(f"Patient: {response.patient_id}")
    print(f"Architecture: {response.architecture}")
    print(f"Question: {response.question}")
    print()
    print("Answer:")
    print(response.answer)
    print()
    print(f"Action: {response.action}")
    print(f"Action reason: {response.action_reason}")
    print(f"Latency ms: {response.latency_ms}")
    print()
    print("Tool calls used:")
    for call in response.tool_calls:
        print(f"- {call['tool_name']} ({call['status']})")
    print()
    print("Cited evidence IDs:")
    for evidence_id in response.cited_evidence_ids:
        print(f"- {evidence_id}")
    print()
    print("Conflicts:")
    print(json.dumps(response.conflicts, indent=2, sort_keys=True))
    print()
    print("Claims:")
    print(json.dumps(response.claims, indent=2, sort_keys=True))
    print()
    print("Unsupported claims:")
    print(json.dumps(response.unsupported_claims, indent=2, sort_keys=True))
    print()
    print("Missing information:")
    print(json.dumps(response.missing_information, indent=2, sort_keys=True))
    print()
    print("Limitations:")
    print(json.dumps(response.limitations, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
