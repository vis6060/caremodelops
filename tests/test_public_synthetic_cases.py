from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chartground.validation import REQUIRED_CASE_FILES, read_jsonl, validate_cases  # noqa: E402


CASES_ROOT = ROOT / "data/public_synthetic/cases"
BACKUP_ROOT = ROOT / "data/public_synthetic/cases_backup_before_clinician_30_regeneration"
CLINICIAN_RAW = Path(__file__).resolve().parents[1] / "data" / "public_synthetic" / "clinician_review_raw"


def test_thirty_seven_cases_exist_and_validate() -> None:
    case_dirs = sorted(path for path in CASES_ROOT.iterdir() if path.is_dir())
    assert len(case_dirs) == 37
    assert [path.name for path in case_dirs] == [f"cg-syn-{index:03d}" for index in range(1, 38)]
    assert all(re.fullmatch(r"cg-syn-\d{3}", path.name) for path in case_dirs)
    assert validate_cases(CASES_ROOT, expected_count=37) == []


def test_original_seven_cases_were_preserved() -> None:
    assert BACKUP_ROOT.exists()
    for index in range(1, 8):
        case_name = f"cg-syn-{index:03d}"
        assert directory_hash(CASES_ROOT / case_name, excluded={"tasks.jsonl", "expected_behavior.json"}) == directory_hash(
            BACKUP_ROOT / case_name,
            excluded={"tasks.jsonl", "expected_behavior.json"},
        )


def test_new_cases_map_to_clinician_review_raw_files() -> None:
    manifest = json.loads((CASES_ROOT / "manifest.json").read_text(encoding="utf-8"))
    new_cases = [row for row in manifest["cases"] if row["case_id"] >= "cg-syn-008"]
    assert len(new_cases) == 30
    expected_files = sorted(path.name for path in CLINICIAN_RAW.glob("*.json"))
    assert [row["source_bundle"] for row in new_cases] == expected_files
    for row in new_cases:
        case_dir = CASES_ROOT / row["case_id"]
        assert file_hash(case_dir / "raw_fhir_bundle.json") == file_hash(CLINICIAN_RAW / row["source_bundle"])
        patient = read_jsonl(case_dir / "patients.jsonl")[0]
        assert patient["patient_id"] == row["patient_id"]


def test_required_files_exist_for_every_case() -> None:
    for case_dir in sorted(path for path in CASES_ROOT.iterdir() if path.is_dir()):
        assert REQUIRED_CASE_FILES <= {path.name for path in case_dir.iterdir()}


def test_fhir_resources_become_canonical_events_when_present() -> None:
    mapping = {
        "Observation": {"laboratory", "vital_sign", "observation"},
        "MedicationRequest": {"medication_order"},
        "MedicationAdministration": {"medication_administration"},
        "Procedure": {"procedure"},
        "Condition": {"condition"},
        "DiagnosticReport": {"diagnostic_report", "radiology"},
        "CarePlan": {"care_plan"},
    }
    for index in range(8, 38):
        case_id = f"cg-syn-{index:03d}"
        case_dir = CASES_ROOT / case_id
        bundle = json.loads((case_dir / "raw_fhir_bundle.json").read_text(encoding="utf-8"))
        raw_types = {entry.get("resource", {}).get("resourceType") for entry in bundle.get("entry", [])}
        event_types = {row["event_type"] for row in read_jsonl(case_dir / "events.jsonl")}
        for raw_type, expected_event_types in mapping.items():
            if raw_type in raw_types:
                assert event_types & expected_event_types, f"{case_id} missing canonical event for {raw_type}"


def test_numeric_observations_remain_numeric_where_possible() -> None:
    numeric_events = []
    for index in range(8, 38):
        events = read_jsonl(CASES_ROOT / f"cg-syn-{index:03d}" / "events.jsonl")
        numeric_events.extend(row for row in events if row["event_type"] in {"laboratory", "vital_sign", "observation"} and isinstance(row.get("value"), (int, float)))
    assert numeric_events
    assert all(row.get("event_time") or row.get("date") for row in numeric_events)


def test_every_note_sentence_has_provenance_and_tasks_validate() -> None:
    for case_dir in sorted(path for path in CASES_ROOT.iterdir() if path.is_dir()):
        notes = read_jsonl(case_dir / "notes.jsonl")
        provenance = read_jsonl(case_dir / "provenance.jsonl")
        tasks = read_jsonl(case_dir / "tasks.jsonl")
        evidence_ids = {row["evidence_id"] for row in read_jsonl(case_dir / "evidence.jsonl")}
        sentence_keys = {(note["note_id"], sentence["sentence_id"]) for note in notes for sentence in note.get("sentences", [])}
        provenance_keys = {(row["note_id"], row["sentence_id"]) for row in provenance}
        assert sentence_keys == provenance_keys
        for task in tasks:
            assert task["case_id"] == case_dir.name
            assert task.get("prompt") or task.get("question")
            assert task.get("expected_action", "answer") in {"answer", "uncertain", "escalate", "abstain"}
            for evidence_id in task.get("required_evidence_ids", []):
                assert evidence_id in evidence_ids


def test_diversity_audit_meets_minimum_targets() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/audit_case_diversity.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    output = result.stdout
    assert "cases: 37" in output
    assert "tasks:" in output
    totals = parse_audit_totals(output)
    assert totals["tasks"] >= 60
    assert totals["cases_with_lab_trend"] >= 5
    assert totals["cases_with_medication"] >= 5
    assert totals["cases_with_radiology"] >= 4
    assert totals["cases_with_radiology_comparison"] >= 3
    assert totals["cases_with_conflict_task"] >= 3
    assert totals["cases_with_missing_info_task"] >= 3
    assert totals["cases_with_prompt_injection_task"] >= 3
    assert totals["cases_with_cross_patient_task"] >= 3


def test_public_evaluation_runs_without_system_failures(tmp_path: Path) -> None:
    output_dir = tmp_path / "eval"
    subprocess.run(
        [
            sys.executable,
            "scripts/run_public_evaluation.py",
            "--architectures",
            "rag",
            "verified_agent",
            "--limit",
            "4",
            "--output",
            str(output_dir),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    failures = (output_dir / "task_failures.jsonl").read_text(encoding="utf-8")
    assert failures == ""


def test_no_mimic_references_in_public_cases() -> None:
    for path in CASES_ROOT.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".json", ".jsonl", ".md"}:
            assert "mimic" not in path.read_text(encoding="utf-8").lower()


def parse_audit_totals(output: str) -> dict[str, int]:
    totals = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip("- ")
        value = value.strip()
        if value.isdigit():
            totals[key] = int(value)
    return totals


def directory_hash(path: Path, excluded: set[str] | None = None) -> str:
    excluded = excluded or set()
    digest = hashlib.sha256()
    for file_path in sorted(file for file in path.rglob("*") if file.is_file()):
        if file_path.name in excluded:
            continue
        digest.update(str(file_path.relative_to(path)).encode("utf-8"))
        digest.update(file_path.read_bytes())
    return digest.hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
