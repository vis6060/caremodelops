"""Run a local patient-scoped ChartGround RAG demo."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chartground.evidence_store import DEFAULT_CASES_ROOT, EvidenceStore
from chartground.rag import RagBaseline


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local ChartGround RAG baseline.")
    parser.add_argument("--cases-root", default=str(DEFAULT_CASES_ROOT))
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    store = EvidenceStore(args.cases_root)
    case = store.get_case(args.case_id)
    patient_id = case["patient_id"]
    response = RagBaseline(store, top_k=args.top_k).answer(patient_id, args.question)

    print(f"Case: {args.case_id}")
    print(f"Patient: {patient_id}")
    print()
    print("Answer:")
    print(response.answer)
    print()
    print("Cited evidence IDs:")
    for evidence_id in response.cited_evidence_ids:
        print(f"- {evidence_id}")
    print()
    print(f"Action: {response.action}")
    print(f"Action reason: {response.action_reason}")
    print()
    print("Retrieved evidence snippets:")
    for item in response.retrieved_evidence:
        snippet = item["text"][:180]
        print(f"- {item['chunk_id']} score={item['score']} evidence_id={item['evidence_id']}")
        print(f"  {snippet}")


if __name__ == "__main__":
    main()
