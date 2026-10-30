from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chartground.mimic_adapter import CaseContext, diagnosis_event, lab_event, note_evidence_and_provenance, prescription_event, procedure_event


def test_mimic_adapter_maps_core_rows_without_real_mimic() -> None:
    ctx = CaseContext(case_id="mimic-pilot-001", patient_id="p1", encounter_id="e1")
    diagnosis = diagnosis_event(ctx, {"seq_num": 1, "icd_code": "X", "icd_version": 10, "long_title": "Condition"}, "2100-01-01")
    lab = lab_event(ctx, {"labevent_id": 1, "label": "Creatinine", "charttime": "2100-01-02", "valuenum": 1.2, "valueuom": "mg/dL"})
    med = prescription_event(ctx, {"cg_row_id": 1, "drug": "Medication", "starttime": "2100-01-02", "dose_val_rx": "1", "dose_unit_rx": "tab"})
    procedure = procedure_event(ctx, {"seq_num": 1, "icd_code": "P", "icd_version": 10, "long_title": "Procedure"}, "2100-01-01")
    assert diagnosis["event_type"] == "condition"
    assert lab["event_type"] == "laboratory"
    assert med["event_type"] == "medication_order"
    assert procedure["event_type"] == "procedure"


def test_notes_map_to_private_chunks_without_real_mimic() -> None:
    ctx = CaseContext(case_id="mimic-pilot-001", patient_id="p1", encounter_id="e1")
    note, evidence, provenance = note_evidence_and_provenance(
        ctx,
        {"note_id": "n1", "charttime": "2100-01-01", "text": "Short private fixture note."},
        "discharge",
        max_chunk_chars=100,
    )
    assert note["note_type"] == "discharge"
    assert evidence
    assert provenance
    assert evidence[0]["metadata"]["public_safe"] is False


def test_private_reporting_scripts_on_fake_data(tmp_path: Path) -> None:
    private_root = tmp_path / "results" / "mimic_private"
    eval_dir = private_root / "eval"
    cases_dir = private_root / "cases"
    case_dir = cases_dir / "mimic-pilot-001"
    eval_dir.mkdir(parents=True)
    case_dir.mkdir(parents=True)

    evidence_id = "ev-private-fixture"
    write_jsonl(case_dir / "evidence.jsonl", [{"case_id": "mimic-pilot-001", "patient_id": "p1", "evidence_id": evidence_id, "source_id": "src1"}])
    rows = [
        fake_result("rag", evidence_id, "answer"),
        fake_result("verified_agent", evidence_id, "answer", claims=[{"support_status": "supported"}]),
    ]
    write_jsonl(eval_dir / "run_results.jsonl", rows)
    write_jsonl(eval_dir / "task_failures.jsonl", [])
    (eval_dir / "aggregate_metrics.json").write_text(
        json.dumps(
            {
                "overall": {"task_error_rate": 0.0, "cross_patient_violation_count": 0},
                "architectures": {
                    "rag": {"task_count": 1, "task_error_rate": 0.0, "action_accuracy": 1.0, "cross_patient_violation_count": 0, "median_latency_ms": 1, "p95_latency_ms": 1, "unsupported_claim_rate": "not_applicable"},
                    "verified_agent": {"task_count": 1, "task_error_rate": 0.0, "action_accuracy": 1.0, "cross_patient_violation_count": 0, "median_latency_ms": 2, "p95_latency_ms": 2, "unsupported_claim_rate": 0.0},
                },
            }
        ),
        encoding="utf-8",
    )

    audit_dir = private_root / "eval_audit"
    subprocess.run(
        [sys.executable, "scripts/audit_mimic_private_eval.py", "--eval", str(eval_dir), "--cases", str(cases_dir), "--output", str(audit_dir)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [sys.executable, "scripts/print_mimic_private_scorecard.py", "--eval", str(eval_dir)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    public_dir = private_root / "public_safe_summary"
    subprocess.run(
        [sys.executable, "scripts/export_mimic_public_safe_summary.py", "--eval", str(eval_dir), "--audit", str(audit_dir), "--output", str(public_dir)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    summary = (public_dir / "mimic_private_aggregate_summary.json").read_text(encoding="utf-8")
    assert "patient_id" not in summary
    assert "Fixture answer" not in summary


def test_privacy_scanner_flags_and_passes_clean_files(tmp_path: Path) -> None:
    dirty = tmp_path / "dirty.md"
    dirty.write_text("subject_id should not appear in a public-safe summary", encoding="utf-8")
    dirty_result = subprocess.run(
        [sys.executable, "scripts/check_mimic_privacy_leaks.py", "--paths", str(dirty)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert dirty_result.returncode == 1

    clean = tmp_path / "clean.md"
    clean.write_text("Aggregate-only summary with no restricted identifiers.", encoding="utf-8")
    subprocess.run(
        [sys.executable, "scripts/check_mimic_privacy_leaks.py", "--paths", str(clean)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def fake_result(architecture: str, evidence_id: str, action: str, claims: list[dict] | None = None) -> dict:
    return {
        "architecture": architecture,
        "case_id": "mimic-pilot-001",
        "task_id": "task-001",
        "task_type": "timeline_summary",
        "evaluation_focus": "timeline",
        "patient_id": "p1",
        "answer": "Fixture answer",
        "actual_action": action,
        "expected_action": action,
        "action_correct": True,
        "cited_evidence_ids": [evidence_id],
        "gold_evidence_ids": [evidence_id],
        "citation_applicable": True,
        "cross_patient_violation": False,
        "unsupported_claims": [],
        "claims": claims or [],
        "conflicts": [],
        "latency_ms": 1,
        "error": None,
    }


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
