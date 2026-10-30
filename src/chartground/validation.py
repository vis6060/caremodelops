"""Validation helpers for generated ChartGround synthetic cases."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REQUIRED_CASE_FILES = {
    "raw_fhir_bundle.json",
    "overlays.json",
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


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def validate_case(case_dir: Path) -> list[str]:
    errors: list[str] = []
    missing = sorted(name for name in REQUIRED_CASE_FILES if not (case_dir / name).exists())
    errors.extend(f"missing required file: {name}" for name in missing)
    if missing:
        return errors

    patients = read_jsonl(case_dir / "patients.jsonl")
    encounters = read_jsonl(case_dir / "encounters.jsonl")
    events = read_jsonl(case_dir / "events.jsonl")
    notes = read_jsonl(case_dir / "notes.jsonl")
    evidence = read_jsonl(case_dir / "evidence.jsonl")
    provenance = read_jsonl(case_dir / "provenance.jsonl")
    tasks = read_jsonl(case_dir / "tasks.jsonl")
    expected = json.loads((case_dir / "expected_behavior.json").read_text(encoding="utf-8"))
    overlays = json.loads((case_dir / "overlays.json").read_text(encoding="utf-8"))

    if len(patients) != 1:
        errors.append("patients.jsonl must contain exactly one patient")
        return errors
    patient_id = patients[0]["patient_id"]
    case_id = patients[0]["case_id"]

    all_rows = patients + encounters + events + notes + evidence + provenance + tasks
    for row in all_rows:
        if row.get("patient_id") != patient_id:
            errors.append(f"patient isolation violation in {row}")
        if row.get("case_id") != case_id:
            errors.append(f"case isolation violation in {row}")

    evidence_by_id = {row["evidence_id"]: row for row in evidence}
    evidence_source_ids = {row["source_id"] for row in evidence}
    event_ids = {row["event_id"] for row in events}
    note_ids = {row["note_id"] for row in notes}
    note_sentence_ids = {(note["note_id"], sentence["sentence_id"]) for note in notes for sentence in note.get("sentences", [])}
    prov_sentence_ids = {(row["note_id"], row["sentence_id"]) for row in provenance}

    for row in evidence:
        if not row.get("source_id"):
            errors.append(f"evidence missing source_id: {row.get('evidence_id')}")
    for row in events:
        for evidence_id in row.get("evidence_ids", []):
            if evidence_id not in evidence_by_id:
                errors.append(f"event references missing evidence_id: {evidence_id}")
        for source_id in row.get("source_ids", []):
            if source_id not in evidence_source_ids:
                errors.append(f"event references missing source_id: {source_id}")
    for row in provenance:
        if row.get("source_id") not in evidence_source_ids:
            errors.append(f"provenance references missing source_id: {row.get('source_id')}")
        if row.get("evidence_id") not in evidence_by_id:
            errors.append(f"provenance references missing evidence_id: {row.get('evidence_id')}")
        elif evidence_by_id[row["evidence_id"]]["source_id"] != row.get("source_id"):
            errors.append(f"provenance source/evidence mismatch: {row.get('provenance_id')}")
    if note_sentence_ids != prov_sentence_ids:
        errors.append("every note sentence must have exactly one sentence-level provenance row")

    for task in tasks:
        for evidence_id in task.get("required_evidence_ids", []):
            if evidence_id not in evidence_by_id:
                errors.append(f"task references missing evidence_id: {evidence_id}")
        for event_id in task.get("required_event_ids", []):
            if event_id not in event_ids:
                errors.append(f"task references missing event_id: {event_id}")
        for note_id in task.get("required_note_ids", []):
            if note_id not in note_ids:
                errors.append(f"task references missing note_id: {note_id}")
    expected_task_ids = {row["task_id"] for row in expected.get("tasks", [])}
    task_ids = {row["task_id"] for row in tasks}
    if expected_task_ids != task_ids:
        errors.append("expected_behavior task ids must match tasks.jsonl")

    overlay_source_ids = {
        evidence_row["source_id"]
        for overlay in overlays
        for evidence_row in as_list(overlay.get("evidence"))
        if isinstance(evidence_row, dict) and evidence_row.get("source_id")
    }
    for source_id in overlay_source_ids:
        if source_id not in evidence_source_ids:
            errors.append(f"overlay source not present in evidence: {source_id}")
    return errors


def validate_cases(root: Path, expected_count: int | None = 5) -> list[str]:
    errors: list[str] = []
    case_dirs = sorted(path for path in root.iterdir() if path.is_dir())
    if expected_count is not None and len(case_dirs) != expected_count:
        errors.append(f"expected {expected_count} case directories, found {len(case_dirs)}")
    for case_dir in case_dirs:
        errors.extend(f"{case_dir.name}: {error}" for error in validate_case(case_dir))
    return errors


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]
