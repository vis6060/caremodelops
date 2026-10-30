"""Run deterministic ChartGround clinical tools for one case."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chartground.clinical_tools import ClinicalTools
from chartground.evidence_store import DEFAULT_CASES_ROOT, EvidenceStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic ChartGround clinical tools.")
    parser.add_argument("--cases-root", default=str(DEFAULT_CASES_ROOT))
    parser.add_argument("--case-id", required=True)
    args = parser.parse_args()

    store = EvidenceStore(args.cases_root)
    tools = ClinicalTools(store, args.cases_root)
    patient_id = store.get_case(args.case_id)["patient_id"]
    lab_name = choose_lab_name(tools, patient_id) or "hemoglobin"

    print(f"Case: {args.case_id}")
    print(f"Patient: {patient_id}")
    print()
    print("Timeline:")
    print_json(tools.build_patient_timeline(patient_id)[:8])
    print()
    print(f"Lab trend: {lab_name}")
    lab_trend = tools.get_lab_trend(patient_id, lab_name)
    if not lab_trend["found"]:
        print("No numeric labs available for this case.")
    print_json(lab_trend)
    print()
    print("Medication changes:")
    print_json(tools.get_medication_changes(patient_id))
    print()
    print("Radiology comparison:")
    print_json(tools.compare_radiology_reports(patient_id))
    print()
    print("Detected conflicts:")
    print_json(tools.detect_record_conflicts(patient_id))
    print()
    print('Clinical note search: "What changed during this encounter?"')
    print_json(tools.search_clinical_notes(patient_id, "What changed during this encounter?", top_k=5))


def choose_lab_name(tools: ClinicalTools, patient_id: str) -> str | None:
    for row in tools.build_patient_timeline(patient_id):
        if row.get("event_type") == "observation" and row.get("display"):
            return str(row["display"])
    return None


def print_json(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
