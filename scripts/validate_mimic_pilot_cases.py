"""Validate private MIMIC pilot ChartGround cases."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REQUIRED_FILES = {
    "patients.jsonl",
    "encounters.jsonl",
    "events.jsonl",
    "notes.jsonl",
    "evidence.jsonl",
    "provenance.jsonl",
    "tasks.jsonl",
    "expected_behavior.json",
    "case_card.md",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate private MIMIC pilot cases.")
    parser.add_argument("--cases", required=True)
    parser.add_argument("--expected-count", type=int, default=10)
    args = parser.parse_args()

    cases_root = Path(args.cases)
    errors = validate_cases(cases_root, args.expected_count)
    if errors:
        print(f"Validation failed with {len(errors)} error(s).")
        for error in errors[:50]:
            print(error)
        sys.exit(1)
    case_dirs = sorted(path for path in cases_root.iterdir() if path.is_dir())
    task_count = sum(len(read_jsonl(path / "tasks.jsonl")) for path in case_dirs)
    print(f"Validated {len(case_dirs)} private MIMIC cases with {task_count} tasks.")


def validate_cases(cases_root: Path, expected_count: int = 10) -> list[str]:
    errors: list[str] = []
    normalized = str(cases_root.resolve()).replace("\\", "/")
    if "/results/mimic_private/" not in normalized and not normalized.endswith("/results/mimic_private/cases"):
        errors.append("MIMIC private cases must be under results/mimic_private/")
        return errors
    if "public_synthetic" in normalized:
        errors.append("MIMIC validation must not use public_synthetic paths")
        return errors
    if not cases_root.exists():
        errors.append(f"cases root does not exist: {cases_root}")
        return errors
    case_dirs = sorted(path for path in cases_root.iterdir() if path.is_dir())
    if len(case_dirs) != expected_count:
        errors.append(f"expected {expected_count} cases, found {len(case_dirs)}")
    for case_dir in case_dirs:
        errors.extend(f"{case_dir.name}: {error}" for error in validate_case(case_dir))
    return errors


def validate_case(case_dir: Path) -> list[str]:
    errors: list[str] = []
    missing = sorted(REQUIRED_FILES - {path.name for path in case_dir.iterdir() if path.is_file()})
    if missing:
        return [f"missing required file: {name}" for name in missing]
    forbidden = {"raw_fhir_bundle.json", "overlays.json"}
    for name in forbidden:
        if (case_dir / name).exists():
            errors.append(f"forbidden private MIMIC file present: {name}")

    patients = read_jsonl(case_dir / "patients.jsonl")
    encounters = read_jsonl(case_dir / "encounters.jsonl")
    events = read_jsonl(case_dir / "events.jsonl")
    notes = read_jsonl(case_dir / "notes.jsonl")
    evidence = read_jsonl(case_dir / "evidence.jsonl")
    provenance = read_jsonl(case_dir / "provenance.jsonl")
    tasks = read_jsonl(case_dir / "tasks.jsonl")
    expected = json.loads((case_dir / "expected_behavior.json").read_text(encoding="utf-8"))

    for name, rows in {
        "patients": patients,
        "encounters": encounters,
        "events": events,
        "notes": notes,
        "evidence": evidence,
        "tasks": tasks,
    }.items():
        if not rows:
            errors.append(f"{name}.jsonl must not be empty")
    if len(patients) != 1:
        errors.append("patients.jsonl must contain exactly one patient")
        return errors
    patient_id = patients[0].get("patient_id")
    case_id = patients[0].get("case_id")
    if expected.get("source") != "mimic_iv_private" or expected.get("public_safe") is not False:
        errors.append("expected_behavior must mark source=mimic_iv_private and public_safe=false")

    evidence_by_id = {row.get("evidence_id"): row for row in evidence}
    evidence_source_ids = {row.get("source_id") for row in evidence}
    note_sentence_keys = {(note.get("note_id"), sentence.get("sentence_id")) for note in notes for sentence in note.get("sentences", [])}
    provenance_keys = {(row.get("note_id"), row.get("sentence_id")) for row in provenance}

    for collection_name, rows in {
        "encounters": encounters,
        "events": events,
        "notes": notes,
        "evidence": evidence,
        "provenance": provenance,
        "tasks": tasks,
    }.items():
        for row in rows:
            if row.get("patient_id") != patient_id:
                errors.append(f"{collection_name} patient_id mismatch")
            if row.get("case_id") != case_id:
                errors.append(f"{collection_name} case_id mismatch")

    for row in evidence:
        if not row.get("evidence_id") or not row.get("source_id"):
            errors.append("evidence row missing evidence_id/source_id")
        if row.get("metadata", {}).get("public_safe") is not False:
            errors.append(f"evidence missing public_safe=false: {row.get('evidence_id')}")
    for row in events:
        for evidence_id in row.get("evidence_ids", []):
            if evidence_id not in evidence_by_id:
                errors.append(f"event references missing evidence_id: {evidence_id}")
    for row in provenance:
        if row.get("evidence_id") not in evidence_by_id:
            errors.append(f"provenance references missing evidence_id: {row.get('evidence_id')}")
        if row.get("source_id") not in evidence_source_ids:
            errors.append(f"provenance references missing source_id: {row.get('source_id')}")
        if row.get("public_safe") is not False:
            errors.append(f"provenance missing public_safe=false: {row.get('provenance_id')}")
    if note_sentence_keys != provenance_keys:
        errors.append("every note sentence must have matching chunk-level provenance")

    for task in tasks:
        if task.get("patient_id") != patient_id:
            errors.append(f"task patient mismatch: {task.get('task_id')}")
        if task.get("metadata", {}).get("public_safe") is not False:
            errors.append(f"task missing public_safe=false: {task.get('task_id')}")
        for evidence_id in task.get("gold_evidence_ids", []) or task.get("required_evidence_ids", []):
            evidence_row = evidence_by_id.get(evidence_id)
            if not evidence_row:
                errors.append(f"task references missing evidence_id: {evidence_id}")
            elif evidence_row.get("patient_id") != patient_id:
                errors.append(f"task gold evidence belongs to another patient: {evidence_id}")
    return errors


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    main()
