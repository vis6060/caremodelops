import csv
import json
from collections import Counter
from pathlib import Path


CASES_DIR = Path("data/public_synthetic/cases")
OUT_DIR = Path("results/public_eval_37")
OUT_CSV = OUT_DIR / "case_diversity_audit.csv"
OUT_MD = OUT_DIR / "case_diversity_report.md"


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []

    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def lower(value) -> str:
    return str(value or "").lower()


def is_numeric(value) -> bool:
    try:
        float(value)
        return value is not None and str(value).strip() != ""
    except Exception:
        return False


def audit_case(case_dir: Path) -> dict:
    case_id = case_dir.name

    patients = read_jsonl(case_dir / "patients.jsonl")
    encounters = read_jsonl(case_dir / "encounters.jsonl")
    events = read_jsonl(case_dir / "events.jsonl")
    notes = read_jsonl(case_dir / "notes.jsonl")
    evidence = read_jsonl(case_dir / "evidence.jsonl")
    provenance = read_jsonl(case_dir / "provenance.jsonl")
    tasks = read_jsonl(case_dir / "tasks.jsonl")
    expected = read_json(case_dir / "expected_behavior.json")
    overlays = read_json(case_dir / "overlays.json")

    patient_id = patients[0].get("patient_id", "") if patients else ""

    event_types = Counter(lower(e.get("event_type") or e.get("source_type")) for e in events)
    evidence_types = Counter(lower(e.get("source_type") or e.get("event_type")) for e in evidence)
    note_types = Counter(lower(n.get("note_type") or n.get("source_type") or n.get("title")) for n in notes)
    task_types = Counter(lower(t.get("task_type")) for t in tasks)
    eval_focus = Counter(lower(t.get("evaluation_focus")) for t in tasks)
    expected_actions = Counter(lower(t.get("expected_action")) for t in tasks)

    numeric_labs = []
    timestamps = set()
    lab_names = Counter()

    for e in events:
        text = " ".join([
            lower(e.get("event_type")),
            lower(e.get("source_type")),
            lower(e.get("display")),
            lower(e.get("title")),
            lower(e.get("code")),
        ])

        event_time = e.get("event_time") or e.get("source_time") or e.get("timestamp")
        if event_time:
            timestamps.add(str(event_time))

        if (
            "lab" in text
            or "observation" in text
            or lower(e.get("event_type")) in {"laboratory", "observation", "vital_sign"}
        ):
            if is_numeric(e.get("value")):
                numeric_labs.append(e)
                lab_names[lower(e.get("display") or e.get("title") or "unknown")] += 1

    labs_with_trend = sum(1 for _, count in lab_names.items() if count >= 2)

    medication_count = sum(
        1 for e in events
        if "med" in lower(e.get("event_type"))
        or "medication" in lower(e.get("source_type"))
        or "medication" in lower(e.get("display"))
        or "medication" in lower(e.get("title"))
    )

    radiology_count = sum(
        1 for item in evidence + notes + events
        if "radiology" in lower(item.get("source_type"))
        or "radiology" in lower(item.get("event_type"))
        or "radiology" in lower(item.get("note_type"))
        or "diagnostic" in lower(item.get("event_type"))
        or "diagnostic" in lower(item.get("source_type"))
        or "x-ray" in lower(item.get("text"))
        or "radiograph" in lower(item.get("text"))
        or "impression" in lower(item.get("text"))
    )

    procedure_count = sum(
        1 for e in events
        if "procedure" in lower(e.get("event_type"))
        or "procedure" in lower(e.get("source_type"))
    )

    has_conflict_task = any(
        "conflict" in lower(t.get("task_type"))
        or "conflict" in lower(t.get("evaluation_focus"))
        or lower(t.get("expected_action")) == "escalate"
        for t in tasks
    )

    has_missing_info_task = any(
        "missing" in lower(t.get("task_type"))
        or "missing" in lower(t.get("evaluation_focus"))
        or lower(t.get("expected_action")) in {"uncertain", "abstain"}
        for t in tasks
    )

    has_prompt_injection_task = any(
        "prompt" in lower(t.get("adversarial_type"))
        or "injection" in lower(t.get("adversarial_type"))
        or "prompt" in lower(t.get("evaluation_focus"))
        or "injection" in lower(t.get("question"))
        for t in tasks
    )

    has_cross_patient_task = any(
        "cross" in lower(t.get("adversarial_type"))
        or "cross" in lower(t.get("evaluation_focus"))
        or "other patient" in lower(t.get("question"))
        for t in tasks
    )

    row = {
        "case_id": case_id,
        "patient_id": patient_id,
        "patients": len(patients),
        "encounters": len(encounters),
        "events": len(events),
        "notes": len(notes),
        "evidence": len(evidence),
        "provenance": len(provenance),
        "tasks": len(tasks),
        "distinct_timestamps": len(timestamps),
        "numeric_lab_events": len(numeric_labs),
        "labs_with_2plus_values": labs_with_trend,
        "medication_events": medication_count,
        "radiology_items": radiology_count,
        "procedure_events": procedure_count,
        "has_lab_trend": labs_with_trend >= 1,
        "has_medication": medication_count >= 1,
        "has_radiology": radiology_count >= 1,
        "has_radiology_comparison": radiology_count >= 2,
        "has_procedure": procedure_count >= 1,
        "has_conflict_task": has_conflict_task,
        "has_missing_info_task": has_missing_info_task,
        "has_prompt_injection_task": has_prompt_injection_task,
        "has_cross_patient_task": has_cross_patient_task,
        "task_types": ";".join(f"{k}:{v}" for k, v in sorted(task_types.items()) if k),
        "evaluation_focus": ";".join(f"{k}:{v}" for k, v in sorted(eval_focus.items()) if k),
        "expected_actions": ";".join(f"{k}:{v}" for k, v in sorted(expected_actions.items()) if k),
        "event_types": ";".join(f"{k}:{v}" for k, v in sorted(event_types.items()) if k),
        "evidence_types": ";".join(f"{k}:{v}" for k, v in sorted(evidence_types.items()) if k),
        "note_types": ";".join(f"{k}:{v}" for k, v in sorted(note_types.items()) if k),
        "has_overlays": bool(overlays),
        "expected_behavior_keys": ";".join(sorted(expected.keys())) if isinstance(expected, dict) else "",
    }

    return row


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    case_dirs = sorted([p for p in CASES_DIR.iterdir() if p.is_dir()])
    rows = [audit_case(case_dir) for case_dir in case_dirs]

    if not rows:
        raise RuntimeError(f"No case directories found in {CASES_DIR}")

    fieldnames = list(rows[0].keys())

    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    totals = {
        "cases": len(rows),
        "tasks": sum(r["tasks"] for r in rows),
        "cases_with_lab_trend": sum(bool(r["has_lab_trend"]) for r in rows),
        "cases_with_medication": sum(bool(r["has_medication"]) for r in rows),
        "cases_with_radiology": sum(bool(r["has_radiology"]) for r in rows),
        "cases_with_radiology_comparison": sum(bool(r["has_radiology_comparison"]) for r in rows),
        "cases_with_procedure": sum(bool(r["has_procedure"]) for r in rows),
        "cases_with_conflict_task": sum(bool(r["has_conflict_task"]) for r in rows),
        "cases_with_missing_info_task": sum(bool(r["has_missing_info_task"]) for r in rows),
        "cases_with_prompt_injection_task": sum(bool(r["has_prompt_injection_task"]) for r in rows),
        "cases_with_cross_patient_task": sum(bool(r["has_cross_patient_task"]) for r in rows),
    }

    recommendations = []

    if totals["cases_with_lab_trend"] < 5:
        recommendations.append("Add overlays/tasks for more numeric lab trends.")
    if totals["cases_with_medication"] < 5:
        recommendations.append("Add overlays/tasks for medication changes or uncertainty.")
    if totals["cases_with_radiology"] < 4:
        recommendations.append("Add radiology reports or radiology tasks.")
    if totals["cases_with_radiology_comparison"] < 3:
        recommendations.append("Add second radiology reports for comparison tasks.")
    if totals["cases_with_conflict_task"] < 3:
        recommendations.append("Add conflict/escalation tasks.")
    if totals["cases_with_missing_info_task"] < 3:
        recommendations.append("Add missing-information or uncertainty tasks.")
    if totals["cases_with_prompt_injection_task"] < 3:
        recommendations.append("Add prompt-injection adversarial tasks.")
    if totals["cases_with_cross_patient_task"] < 3:
        recommendations.append("Add cross-patient safety tasks.")
    if totals["tasks"] < 60:
        recommendations.append("Expand task set to at least 60 tasks before clinician review.")

    lines = [
        "# ChartGround 37-Case Diversity Audit",
        "",
        "## Summary",
        "",
    ]

    for key, value in totals.items():
        lines.append(f"- {key}: {value}")

    lines.extend([
        "",
        "## Recommended minimum coverage before clinician review",
        "",
        "- At least 37 generated cases",
        "- At least 60 public evaluation tasks",
        "- At least 5 cases with lab trends",
        "- At least 5 cases with medication evidence",
        "- At least 4 cases with radiology evidence",
        "- At least 3 cases with radiology comparison",
        "- At least 3 conflict/escalation cases",
        "- At least 3 missing-information cases",
        "- At least 3 prompt-injection tasks",
        "- At least 3 cross-patient safety tasks",
        "",
        "## Recommendations",
        "",
    ])

    if recommendations:
        for item in recommendations:
            lines.append(f"- {item}")
    else:
        lines.append("- Coverage looks sufficient to proceed with Milestone 7 calibration and clinician-review export.")

    lines.extend([
        "",
        "## Per-case table",
        "",
        "| Case | Tasks | Events | Evidence | Lab trend | Meds | Radiology | Rad comparison | Conflict task | Missing info | Prompt injection | Cross-patient |",
        "|---|---:|---:|---:|---|---|---|---|---|---|---|---|",
    ])

    for r in rows:
        lines.append(
            f"| {r['case_id']} "
            f"| {r['tasks']} "
            f"| {r['events']} "
            f"| {r['evidence']} "
            f"| {r['has_lab_trend']} "
            f"| {r['has_medication']} "
            f"| {r['has_radiology']} "
            f"| {r['has_radiology_comparison']} "
            f"| {r['has_conflict_task']} "
            f"| {r['has_missing_info_task']} "
            f"| {r['has_prompt_injection_task']} "
            f"| {r['has_cross_patient_task']} |"
        )

    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"Cases audited: {totals['cases']}")
    print(f"Tasks found: {totals['tasks']}")
    print(f"Wrote: {OUT_CSV}")
    print(f"Wrote: {OUT_MD}")
    print()
    print("Coverage summary:")
    for key, value in totals.items():
        print(f"  {key}: {value}")

    print()
    if recommendations:
        print("Recommendations:")
        for item in recommendations:
            print(f"  - {item}")
    else:
        print("Coverage looks sufficient to proceed.")


if __name__ == "__main__":
    main()
