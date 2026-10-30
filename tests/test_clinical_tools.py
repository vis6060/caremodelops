from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chartground.clinical_tools import ClinicalToolRegistry, ClinicalTools
from chartground.evidence_store import EvidenceStore


CASES_ROOT = ROOT / "data/public_synthetic/cases"


def test_build_patient_timeline_returns_only_requested_patient() -> None:
    store = EvidenceStore(CASES_ROOT)
    tools = ClinicalTools(store, CASES_ROOT)
    patient_id = store.get_case("cg-syn-001")["patient_id"]
    rows = tools.build_patient_timeline(patient_id)
    assert rows
    assert {row["patient_id"] for row in rows} == {patient_id}


def test_timeline_is_sorted_chronologically_when_timestamps_exist() -> None:
    store = EvidenceStore(CASES_ROOT)
    tools = ClinicalTools(store, CASES_ROOT)
    patient_id = store.get_case("cg-syn-001")["patient_id"]
    timestamps = [row["event_time"] for row in tools.build_patient_timeline(patient_id) if row.get("event_time")]
    assert timestamps == sorted(timestamps)


def test_lab_trend_directions_and_non_numeric_values(tmp_path: Path) -> None:
    cases_root = make_lab_fixture(tmp_path)
    tools = ClinicalTools(cases_root=cases_root)
    patient_id = "patient-lab"

    assert tools.get_lab_trend(patient_id, "Creatinine")["direction"] == "increased"
    assert tools.get_lab_trend(patient_id, "Hemoglobin")["direction"] == "decreased"
    assert tools.get_lab_trend(patient_id, "Sodium")["direction"] == "unchanged"
    missing = tools.get_lab_trend(patient_id, "Platelet")
    assert missing["direction"] == "insufficient_data"
    potassium = tools.get_lab_trend(patient_id, "Potassium")
    assert potassium["direction"] == "insufficient_data"
    assert potassium["errors"][0]["error"] == "non_numeric_value"


def test_medication_changes_are_structured_and_conservative() -> None:
    store = EvidenceStore(CASES_ROOT)
    tools = ClinicalTools(store, CASES_ROOT)
    patient_id = store.get_case("cg-syn-001")["patient_id"]
    result = tools.get_medication_changes(patient_id)
    assert set(result) == {
        "patient_id",
        "medications_started",
        "medications_stopped",
        "medications_continued",
        "medications_uncertain",
        "potential_conflicts",
    }
    assert result["medications_uncertain"]


def test_compare_radiology_reports_insufficient_with_single_report() -> None:
    store = EvidenceStore(CASES_ROOT)
    tools = ClinicalTools(store, CASES_ROOT)
    patient_id = store.get_case("cg-syn-001")["patient_id"]
    result = tools.compare_radiology_reports(patient_id)
    assert result["report_count"] < 2
    assert result["insufficient_data"] is True


def test_search_clinical_notes_excludes_non_clinical_metadata() -> None:
    store = EvidenceStore(CASES_ROOT)
    tools = ClinicalTools(store, CASES_ROOT)
    patient_id = store.get_case("cg-syn-001")["patient_id"]
    results = tools.search_clinical_notes(patient_id, "cross-patient information used for this note", top_k=5)
    assert results
    assert all("cross-patient" not in result["snippet"].lower() for result in results)


def test_detect_record_conflicts_returns_structured_conflict_objects() -> None:
    store = EvidenceStore(CASES_ROOT)
    tools = ClinicalTools(store, CASES_ROOT)
    patient_id = store.get_case("cg-syn-001")["patient_id"]
    result = tools.detect_record_conflicts(patient_id)
    assert result["patient_id"] == patient_id
    assert isinstance(result["conflicts"], list)
    for conflict in result["conflicts"]:
        assert {"conflict_type", "description", "severity", "supporting_evidence_ids", "source_ids", "recommended_action"} <= set(conflict)


def test_no_tool_returns_other_patient_evidence() -> None:
    store = EvidenceStore(CASES_ROOT)
    tools = ClinicalTools(store, CASES_ROOT)
    patient_id = store.get_case("cg-syn-001")["patient_id"]
    assert all(row["patient_id"] == patient_id for row in tools.build_patient_timeline(patient_id))
    assert all(row["patient_id"] == patient_id for row in tools.search_clinical_notes(patient_id, "radiology", top_k=5))
    assert tools.get_lab_trend(patient_id, "anything")["patient_id"] == patient_id
    assert tools.get_medication_changes(patient_id)["patient_id"] == patient_id
    assert tools.compare_radiology_reports(patient_id)["patient_id"] == patient_id
    assert tools.detect_record_conflicts(patient_id)["patient_id"] == patient_id


def test_tool_registry_outputs_are_json_serializable() -> None:
    store = EvidenceStore(CASES_ROOT)
    tools = ClinicalTools(store, CASES_ROOT)
    registry = ClinicalToolRegistry(tools)
    patient_id = store.get_case("cg-syn-001")["patient_id"]
    for name in registry.list_tools():
        kwargs = {"patient_id": patient_id}
        if name == "get_lab_trend":
            kwargs["lab_name"] = "hemoglobin"
        if name == "search_clinical_notes":
            kwargs["query"] = "radiology"
            kwargs["top_k"] = 2
        json.dumps(registry.call(name, **kwargs))


def test_tools_demo_runs_successfully() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/tools_demo.py", "--case-id", "cg-syn-001"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Timeline:" in result.stdout
    assert "Medication changes:" in result.stdout
    assert "Radiology comparison:" in result.stdout
    assert "Detected conflicts:" in result.stdout


def make_lab_fixture(tmp_path: Path) -> Path:
    cases_root = tmp_path / "cases"
    case_dir = cases_root / "cg-syn-lab"
    case_dir.mkdir(parents=True)
    patient = {"case_id": "cg-syn-lab", "patient_id": "patient-lab", "display_name": "Lab Patient", "source_id": "fhir:Patient/patient-lab"}
    write_jsonl(case_dir / "patients.jsonl", [patient])
    shutil.copyfile(CASES_ROOT / "cg-syn-001" / "raw_fhir_bundle.json", case_dir / "raw_fhir_bundle.json")
    write_json(case_dir / "overlays.json", [])
    write_jsonl(case_dir / "encounters.jsonl", [])
    events = [
        lab_event("evt-cr-1", "ev-cr-1", "Creatinine", "2026-01-01", "1.0 mg/dL"),
        lab_event("evt-cr-2", "ev-cr-2", "Creatinine", "2026-01-02", "2.0 mg/dL"),
        lab_event("evt-hgb-1", "ev-hgb-1", "Hemoglobin", "2026-01-01", "12 g/dL"),
        lab_event("evt-hgb-2", "ev-hgb-2", "Hemoglobin", "2026-01-02", "10 g/dL"),
        lab_event("evt-na-1", "ev-na-1", "Sodium", "2026-01-01", "140 mmol/L"),
        lab_event("evt-na-2", "ev-na-2", "Sodium", "2026-01-02", "140 mmol/L"),
        lab_event("evt-k-1", "ev-k-1", "Potassium", "2026-01-01", "hemolyzed"),
    ]
    write_jsonl(case_dir / "events.jsonl", events)
    evidence = [
        {
            "case_id": "cg-syn-lab",
            "patient_id": "patient-lab",
            "evidence_id": event["evidence_ids"][0],
            "source_id": event["source_ids"][0],
            "source_kind": "fixture",
            "resource_type": "Observation",
            "date": event["date"],
            "label": event["label"],
            "code": None,
            "value": event["value"],
            "encounter_id": None,
        }
        for event in events
    ]
    write_jsonl(case_dir / "evidence.jsonl", evidence)
    write_jsonl(case_dir / "notes.jsonl", [])
    write_jsonl(case_dir / "provenance.jsonl", [])
    write_jsonl(case_dir / "tasks.jsonl", [])
    write_json(case_dir / "expected_behavior.json", {"case_id": "cg-syn-lab", "patient_id": "patient-lab", "tasks": []})
    (case_dir / "case_card.md").write_text("# cg-syn-lab\n", encoding="utf-8")
    return cases_root


def lab_event(event_id: str, evidence_id: str, label: str, date: str, value: str) -> dict:
    return {
        "case_id": "cg-syn-lab",
        "patient_id": "patient-lab",
        "event_id": event_id,
        "event_type": "observation",
        "date": date,
        "label": label,
        "value": value,
        "encounter_id": None,
        "evidence_ids": [evidence_id],
        "source_ids": [f"fixture:{evidence_id}"],
    }


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
