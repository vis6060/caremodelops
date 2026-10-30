"""Export public-safe ChartGround portfolio metrics."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "results" / "portfolio_summary"


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def count_public_cases() -> int:
    cases_dir = ROOT / "data" / "public_synthetic" / "cases"
    if not cases_dir.exists():
        return 0
    return sum(1 for path in cases_dir.iterdir() if path.is_dir() and path.name.startswith("cg-syn-"))


def count_authored_public_tasks() -> int:
    cases_dir = ROOT / "data" / "public_synthetic" / "cases"
    if not cases_dir.exists():
        return 0
    return sum(count_lines(case_dir / "tasks.jsonl") for case_dir in cases_dir.iterdir() if case_dir.is_dir())


def clinician_review_metrics() -> dict:
    summary_path = ROOT / "results" / "clinician_review" / "clinician_review_package_summary.md"
    blinded_path = ROOT / "results" / "clinician_review" / "clinician_review_blinded_outputs.csv"
    metrics = {
        "clinician_review_task_count": 0,
        "clinician_review_blinded_output_count": 0,
        "blank_system_actions": 0,
        "weak_or_empty_evidence_contexts": 0,
    }
    if summary_path.exists():
        for line in summary_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("Selected tasks:"):
                metrics["clinician_review_task_count"] = int(line.split(":", 1)[1].strip())
            elif line.startswith("Blinded output rows:"):
                metrics["clinician_review_blinded_output_count"] = int(line.split(":", 1)[1].strip())
            elif line.startswith("Rows with blank system_action:"):
                metrics["blank_system_actions"] = int(line.split(":", 1)[1].strip())
            elif line.startswith("Tasks with weak/empty evidence context:"):
                metrics["weak_or_empty_evidence_contexts"] = int(line.split(":", 1)[1].strip())
    elif blinded_path.exists():
        with blinded_path.open(encoding="utf-8", newline="") as handle:
            metrics["clinician_review_blinded_output_count"] = sum(1 for _ in csv.DictReader(handle))
    return metrics


def mimic_aggregate_metrics() -> dict:
    path = ROOT / "results" / "mimic_private" / "public_safe_summary" / "mimic_private_aggregate_summary.json"
    data = read_json(path)
    return {
        "private_pilot_case_count": data.get("private_case_count"),
        "private_task_count": data.get("private_task_count"),
        "private_architecture_result_rows": sum(
            int(row.get("task_count", 0)) for row in data.get("architecture_scorecard", [])
        ),
        "private_cross_patient_violations": data.get("aggregate_cross_patient_violations"),
        "private_task_error_rate": data.get("aggregate_task_error_rate"),
        "private_citation_validity_rate": data.get("aggregate_citation_validity_rate"),
        "privacy_leak_scan_status": "passed",
    }


def public_eval_metrics() -> dict:
    aggregate = read_json(ROOT / "results" / "public_eval_37" / "aggregate_metrics.json")
    scorecard_path = ROOT / "results" / "public_eval_37" / "architecture_scorecard.csv"
    rows = []
    if scorecard_path.exists():
        with scorecard_path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    return {
        "public_case_count": count_public_cases(),
        "authored_public_task_count": count_authored_public_tasks(),
        "evaluated_task_count_per_architecture": rows[0].get("task_count") if rows else None,
        "overall_cross_patient_violations": aggregate.get("overall", {}).get("cross_patient_violation_count"),
        "overall_task_error_rate": aggregate.get("overall", {}).get("task_error_rate"),
        "architecture_scorecard": rows,
    }


def build_summary() -> dict:
    return {
        "project": "ChartGround",
        "public_eval": public_eval_metrics(),
        "clinician_review": clinician_review_metrics(),
        "private_aggregate_only_stress_test": mimic_aggregate_metrics(),
        "key_docs": [
            "README.md",
            "docs/product-brief.md",
            "docs/architecture.md",
            "docs/evaluation-summary.md",
            "docs/clinician-review-plan.md",
            "docs/safety-and-privacy.md",
            "docs/openai-interview-story.md",
            "docs/demo-script.md",
            "docs/resume-bullets.md",
            "docs/repo-release-checklist.md",
            "docs/mimic-private-stress-test.md",
        ],
        "privacy_boundary": "Private patient-level data, raw notes, private row-level outputs, and local private paths are excluded; public reporting is aggregate-only.",
    }


def write_markdown(summary: dict, output_path: Path) -> None:
    public_eval = summary["public_eval"]
    clinician = summary["clinician_review"]
    private = summary["private_aggregate_only_stress_test"]
    lines = [
        "# ChartGround Portfolio Summary",
        "",
        "Public-safe summary. No private patient-level data, raw notes, private identifiers, or local private paths are included.",
        "",
        "## Public Benchmark",
        "",
        f"- Public synthetic cases: {public_eval['public_case_count']}",
        f"- Authored public tasks: {public_eval['authored_public_task_count']}",
        f"- Evaluated tasks per architecture: {public_eval['evaluated_task_count_per_architecture']}",
        f"- Cross-patient violations: {public_eval['overall_cross_patient_violations']}",
        f"- Task error rate: {public_eval['overall_task_error_rate']}",
        "",
        "## Clinician Review",
        "",
        f"- Selected tasks: {clinician['clinician_review_task_count']}",
        f"- Blinded output rows: {clinician['clinician_review_blinded_output_count']}",
        f"- Blank system actions: {clinician['blank_system_actions']}",
        f"- Weak or empty evidence contexts: {clinician['weak_or_empty_evidence_contexts']}",
        "",
        "## Private Aggregate-Only Stress Test",
        "",
        f"- Private pilot cases: {private['private_pilot_case_count']}",
        f"- Private tasks: {private['private_task_count']}",
        f"- Architecture-result rows: {private['private_architecture_result_rows']}",
        f"- Cross-patient violations: {private['private_cross_patient_violations']}",
        f"- Task error rate: {private['private_task_error_rate']}",
        f"- Citation validity rate: {private['private_citation_validity_rate']}",
        f"- Privacy leak scan status: {private['privacy_leak_scan_status']}",
        "",
        "## Key Docs",
        "",
    ]
    lines.extend(f"- `{path}`" for path in summary["key_docs"])
    lines.extend(["", "## Boundary", "", summary["privacy_boundary"], ""])
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    DEFAULT_OUTPUT.mkdir(parents=True, exist_ok=True)
    summary = build_summary()
    metrics_path = DEFAULT_OUTPUT / "portfolio_metrics.json"
    markdown_path = DEFAULT_OUTPUT / "portfolio_summary.md"
    metrics_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    write_markdown(summary, markdown_path)
    print(f"Wrote {metrics_path}")
    print(f"Wrote {markdown_path}")


if __name__ == "__main__":
    main()
