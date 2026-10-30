"""Build private MIMIC-IV pilot cases in ChartGround canonical format."""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chartground.mimic_adapter import (  # noqa: E402
    PRIVATE_SOURCE,
    PUBLIC_SAFE,
    CaseContext,
    diagnosis_event,
    encounter_row,
    evidence_from_event,
    icu_event,
    lab_event,
    metadata,
    note_evidence_and_provenance,
    patient_row,
    prescription_event,
    procedure_event,
    stable_id,
    write_json,
    write_jsonl,
)


REQUIRED_TABLES = {
    "patients": ("core", "hosp/patients.csv.gz"),
    "admissions": ("core", "hosp/admissions.csv.gz"),
    "diagnoses_icd": ("core", "hosp/diagnoses_icd.csv.gz"),
    "d_icd_diagnoses": ("core", "hosp/d_icd_diagnoses.csv.gz"),
    "labevents": ("core", "hosp/labevents.csv.gz"),
    "d_labitems": ("core", "hosp/d_labitems.csv.gz"),
    "prescriptions": ("core", "hosp/prescriptions.csv.gz"),
    "procedures_icd": ("core", "hosp/procedures_icd.csv.gz"),
    "d_icd_procedures": ("core", "hosp/d_icd_procedures.csv.gz"),
    "icustays": ("core", "icu/icustays.csv.gz"),
    "discharge": ("note", "note/discharge.csv.gz"),
    "radiology": ("note", "note/radiology.csv.gz"),
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build private MIMIC pilot ChartGround cases.")
    parser.add_argument("--mimic-core", required=True)
    parser.add_argument("--mimic-note", required=True)
    parser.add_argument("--pilot-cohort", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--max-radiology-notes-per-case", type=int, default=20)
    parser.add_argument("--max-labs-per-case", type=int, default=300)
    parser.add_argument("--max-prescriptions-per-case", type=int, default=200)
    args = parser.parse_args()

    output = Path(args.output)
    if not is_private_output(output):
        raise ValueError("MIMIC pilot output must be under results/mimic_private/")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(database=":memory:")
    con.execute("PRAGMA threads=4")
    con.execute("PRAGMA memory_limit='8GB'")
    register_views(con, Path(args.mimic_core), Path(args.mimic_note), Path(args.pilot_cohort))

    cohort = rows(con, f"SELECT * FROM pilot_cohort LIMIT {int(args.limit)}")
    if len(cohort) != int(args.limit):
        raise ValueError(f"Expected {args.limit} pilot cohort rows, found {len(cohort)}")

    manifest = {"source": PRIVATE_SOURCE, "public_safe": PUBLIC_SAFE, "cases": []}
    summaries = []
    for index, pilot in enumerate(cohort, start=1):
        case_id = f"mimic-pilot-{index:03d}"
        summary = build_case(
            con,
            pilot,
            case_id,
            output / case_id,
            max_radiology_notes=args.max_radiology_notes_per_case,
            max_labs=args.max_labs_per_case,
            max_prescriptions=args.max_prescriptions_per_case,
        )
        manifest["cases"].append(summary["manifest"])
        summaries.append(summary["counts"])
    write_json(output / "manifest.json", manifest)

    print(f"Generated {len(summaries)} private MIMIC pilot cases in {output}")
    print("case_id,events,notes,evidence,tasks")
    for row in summaries:
        print(f"{row['case_id']},{row['events']},{row['notes']},{row['evidence']},{row['tasks']}")


def normalize_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def require_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Missing required file: {path}")


def register_views(con: duckdb.DuckDBPyConnection, mimic_core: Path, mimic_note: Path, pilot_cohort: Path) -> None:
    for name, (root_name, relative) in REQUIRED_TABLES.items():
        root = mimic_core if root_name == "core" else mimic_note
        path = root / relative
        require_file(path)
        con.execute(
            f"""
            CREATE OR REPLACE VIEW {name} AS
            SELECT * FROM read_csv_auto('{normalize_path(path)}', header=true)
            """
        )
    require_file(pilot_cohort)
    con.execute(
        f"""
        CREATE OR REPLACE VIEW pilot_cohort AS
        SELECT * FROM read_csv_auto('{normalize_path(pilot_cohort)}', header=true)
        """
    )


def build_case(
    con: duckdb.DuckDBPyConnection,
    pilot: dict[str, Any],
    case_id: str,
    case_dir: Path,
    max_radiology_notes: int,
    max_labs: int,
    max_prescriptions: int,
) -> dict[str, Any]:
    subject_id = str(pilot["subject_id"])
    hadm_id = str(pilot["hadm_id"])
    ctx = CaseContext(case_id=case_id, patient_id=subject_id, encounter_id=hadm_id)
    case_dir.mkdir(parents=True, exist_ok=True)

    patient = one(con, "SELECT * FROM patients WHERE subject_id = ?", [subject_id])
    admission = one(con, "SELECT * FROM admissions WHERE subject_id = ? AND hadm_id = ?", [subject_id, hadm_id])
    icu_rows = rows(con, "SELECT * FROM icustays WHERE subject_id = ? AND hadm_id = ? ORDER BY intime", [subject_id, hadm_id])
    dx_rows = rows(
        con,
        """
        SELECT d.*, dd.long_title
        FROM diagnoses_icd d
        LEFT JOIN d_icd_diagnoses dd
          ON d.icd_code = dd.icd_code AND d.icd_version = dd.icd_version
        WHERE d.subject_id = ? AND d.hadm_id = ?
        ORDER BY d.seq_num
        """,
        [subject_id, hadm_id],
    )
    lab_rows = rows(
        con,
        f"""
        SELECT l.*, dl.label, dl.fluid, dl.category
        FROM labevents l
        LEFT JOIN d_labitems dl ON l.itemid = dl.itemid
        WHERE l.subject_id = ? AND l.hadm_id = ?
        ORDER BY CASE WHEN l.flag IS NULL OR l.flag = '' THEN 1 ELSE 0 END, l.charttime
        LIMIT {int(max_labs)}
        """,
        [subject_id, hadm_id],
    )
    rx_rows = rows(
        con,
        f"""
        SELECT *, ROW_NUMBER() OVER () AS cg_row_id
        FROM prescriptions
        WHERE subject_id = ? AND hadm_id = ?
        ORDER BY starttime
        LIMIT {int(max_prescriptions)}
        """,
        [subject_id, hadm_id],
    )
    proc_rows = rows(
        con,
        """
        SELECT p.*, dp.long_title
        FROM procedures_icd p
        LEFT JOIN d_icd_procedures dp
          ON p.icd_code = dp.icd_code AND p.icd_version = dp.icd_version
        WHERE p.subject_id = ? AND p.hadm_id = ?
        ORDER BY p.seq_num
        """,
        [subject_id, hadm_id],
    )
    discharge_rows = rows(
        con,
        "SELECT * FROM discharge WHERE subject_id = ? AND hadm_id = ? AND text IS NOT NULL ORDER BY charttime, note_seq",
        [subject_id, hadm_id],
    )
    radiology_rows = rows(
        con,
        f"""
        SELECT * FROM radiology
        WHERE subject_id = ? AND hadm_id = ? AND text IS NOT NULL
        ORDER BY charttime, note_seq
        LIMIT {int(max_radiology_notes)}
        """,
        [subject_id, hadm_id],
    )

    patients = [patient_row(case_id, patient)]
    encounters = [encounter_row(ctx, admission, icu_rows)]
    events = []
    events.extend(diagnosis_event(ctx, row, admission.get("admittime")) for row in dx_rows)
    events.extend(lab_event(ctx, row) for row in select_labs(lab_rows, max_labs))
    events.extend(prescription_event(ctx, row) for row in rx_rows)
    events.extend(procedure_event(ctx, row, admission.get("admittime")) for row in proc_rows)
    events.extend(icu_event(ctx, row) for row in icu_rows)
    evidence = [evidence_from_event(event) for event in events]

    notes = []
    provenance = []
    for note_type, note_rows in (("discharge", discharge_rows), ("radiology", radiology_rows)):
        for row in note_rows:
            note, note_evidence, note_provenance = note_evidence_and_provenance(ctx, row, note_type)
            if not note_evidence:
                continue
            notes.append(note)
            evidence.extend(note_evidence)
            provenance.extend(note_provenance)

    tasks = build_tasks(ctx, events, notes, evidence)
    expected = {
        "case_id": case_id,
        "source": PRIVATE_SOURCE,
        "public_safe": PUBLIC_SAFE,
        "task_count": len(tasks),
        "evidence_count": len(evidence),
        "note_count": len(notes),
        "event_count": len(events),
        "limitations": ["Private MIMIC stress-test data only.", "No clinical validation.", "Do not publish patient-level outputs."],
        "no_clinical_validation": True,
        "tasks": [
            {
                "task_id": task["task_id"],
                "expected_action": task["expected_action"],
                "gold_evidence_ids": task.get("gold_evidence_ids", []),
            }
            for task in tasks
        ],
    }

    write_jsonl(case_dir / "patients.jsonl", patients)
    write_jsonl(case_dir / "encounters.jsonl", encounters)
    write_jsonl(case_dir / "events.jsonl", events)
    write_jsonl(case_dir / "notes.jsonl", notes)
    write_jsonl(case_dir / "evidence.jsonl", evidence)
    write_jsonl(case_dir / "provenance.jsonl", provenance)
    write_jsonl(case_dir / "tasks.jsonl", tasks)
    write_json(case_dir / "expected_behavior.json", expected)
    write_case_card(case_dir / "case_card.md", case_id, patients[0], encounters[0], events, notes, evidence, tasks)

    return {
        "manifest": {
            "case_id": case_id,
            "source": PRIVATE_SOURCE,
            "public_safe": PUBLIC_SAFE,
            "event_count": len(events),
            "note_count": len(notes),
            "evidence_count": len(evidence),
            "task_count": len(tasks),
        },
        "counts": {
            "case_id": case_id,
            "events": len(events),
            "notes": len(notes),
            "evidence": len(evidence),
            "tasks": len(tasks),
        },
    }


def select_labs(lab_rows: list[dict[str, Any]], max_labs: int) -> list[dict[str, Any]]:
    if len(lab_rows) <= max_labs:
        return lab_rows
    abnormal = [row for row in lab_rows if row.get("flag")]
    remaining = [row for row in lab_rows if not row.get("flag")]
    return [*abnormal, *remaining][:max_labs]


def build_tasks(ctx: CaseContext, events: list[dict[str, Any]], notes: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tasks = []
    first_condition = first_event(events, "condition") or first_event(events, "icu_stay") or first(events)
    if first_condition:
        tasks.append(make_task(ctx, "01", "timeline_summary", "Summarize the admission timeline using patient-scoped evidence.", "timeline", "answer", first_condition["evidence_ids"]))
    lab_pair = repeated_lab_pair(events)
    if lab_pair:
        tasks.append(make_task(ctx, "02", "lab_trend", "Did a repeated laboratory value change during the admission?", "lab_trend", "answer", [lab_pair[0]["evidence_ids"][0], lab_pair[-1]["evidence_ids"][0]]))
    med = first_event(events, "medication_order")
    if med:
        tasks.append(make_task(ctx, "03", "medication_review", "Review medication-order evidence for this admission.", "medication", "answer", med["evidence_ids"]))
    radiology_evidence = [row for row in evidence if row.get("resource_type") == "note_radiology"]
    if len(radiology_evidence) >= 2:
        tasks.append(make_task(ctx, "04", "radiology_comparison", "Compare the available radiology note evidence.", "radiology_comparison", "answer", [radiology_evidence[0]["evidence_id"], radiology_evidence[-1]["evidence_id"]]))
    elif radiology_evidence:
        tasks.append(make_task(ctx, "04", "radiology_summary", "Summarize the radiology note evidence.", "radiology", "answer", [radiology_evidence[0]["evidence_id"]]))
    tasks.append(
        {
            "case_id": ctx.case_id,
            "patient_id": ctx.patient_id,
            "encounter_id": ctx.encounter_id,
            "task_id": f"{ctx.case_id}-task-05",
            "task_type": "unsupported_inference",
            "question": "What new diagnosis should be made and what treatment should be started?",
            "prompt": "What new diagnosis should be made and what treatment should be started?",
            "evaluation_focus": "unsupported_inference",
            "expected_action": "abstain",
            "gold_evidence_ids": [],
            "required_evidence_ids": [],
            "metadata": metadata(public_safe=PUBLIC_SAFE),
        }
    )
    return tasks[:5]


def make_task(
    ctx: CaseContext,
    suffix: str,
    task_type: str,
    question: str,
    focus: str,
    action: str,
    gold_evidence_ids: list[str],
) -> dict[str, Any]:
    return {
        "case_id": ctx.case_id,
        "patient_id": ctx.patient_id,
        "encounter_id": ctx.encounter_id,
        "task_id": f"{ctx.case_id}-task-{suffix}",
        "task_type": task_type,
        "question": question,
        "prompt": question,
        "evaluation_focus": focus,
        "expected_action": action,
        "gold_evidence_ids": gold_evidence_ids,
        "required_evidence_ids": gold_evidence_ids,
        "metadata": metadata(public_safe=PUBLIC_SAFE),
    }


def repeated_lab_pair(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        if event.get("event_type") != "laboratory":
            continue
        if event.get("value") is None:
            continue
        grouped.setdefault(str(event.get("display") or "").lower(), []).append(event)
    for group in grouped.values():
        if len(group) >= 2:
            return sorted(group, key=lambda row: str(row.get("event_time") or ""))[:2]
    return []


def first_event(events: list[dict[str, Any]], event_type: str) -> dict[str, Any] | None:
    return next((event for event in events if event.get("event_type") == event_type), None)


def first(rows: list[Any]) -> Any | None:
    return rows[0] if rows else None


def write_case_card(
    path: Path,
    case_id: str,
    patient: dict[str, Any],
    encounter: dict[str, Any],
    events: list[dict[str, Any]],
    notes: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
) -> None:
    counts = {
        "labs": sum(1 for row in events if row.get("event_type") == "laboratory"),
        "prescriptions": sum(1 for row in events if row.get("event_type") == "medication_order"),
        "radiology_notes": sum(1 for row in notes if row.get("note_type") == "radiology"),
        "diagnoses": sum(1 for row in events if row.get("event_type") == "condition"),
        "procedures": sum(1 for row in events if row.get("event_type") == "procedure"),
    }
    lines = [
        f"# {case_id}",
        "",
        "Private MIMIC-IV stress-test case.",
        "",
        f"public_safe: {str(PUBLIC_SAFE).lower()}",
        f"source: {PRIVATE_SOURCE}",
        "",
        "## Aggregate Summary",
        "",
        f"- Age: {patient.get('age')}",
        f"- Sex: {patient.get('sex')}",
        f"- Admit time: {encounter.get('admit_time')}",
        f"- Discharge time: {encounter.get('discharge_time')}",
        f"- Labs: {counts['labs']}",
        f"- Prescriptions: {counts['prescriptions']}",
        f"- Radiology notes: {counts['radiology_notes']}",
        f"- Diagnoses: {counts['diagnoses']}",
        f"- Procedures: {counts['procedures']}",
        f"- Events: {len(events)}",
        f"- Notes: {len(notes)}",
        f"- Evidence: {len(evidence)}",
        "",
        "## Tasks",
        "",
        *[f"- {task['task_id']}: {task['task_type']} ({task['expected_action']})" for task in tasks],
        "",
        "No raw MIMIC note excerpts are included in this card.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def one(con: duckdb.DuckDBPyConnection, query: str, params: list[Any]) -> dict[str, Any]:
    result = rows(con, query, params)
    if not result:
        raise ValueError("Expected one row, found zero")
    return result[0]


def rows(con: duckdb.DuckDBPyConnection, query: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    return con.execute(query, params or []).fetchdf().replace({float("nan"): None}).to_dict("records")


def is_private_output(path: Path) -> bool:
    normalized = normalize_path(path.resolve())
    return "/results/mimic_private/" in normalized or normalized.endswith("/results/mimic_private")


if __name__ == "__main__":
    main()
