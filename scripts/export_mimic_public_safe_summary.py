"""Export aggregate-only public-safe MIMIC private stress-test summary."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from print_mimic_private_scorecard import build_scorecard, read_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description="Export public-safe aggregate MIMIC summary.")
    parser.add_argument("--eval", required=True)
    parser.add_argument("--audit", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    eval_dir = Path(args.eval)
    audit_dir = Path(args.audit)
    output_dir = Path(args.output)
    require_private_path(eval_dir)
    require_private_path(audit_dir)
    require_private_path(output_dir)
    rows = read_jsonl(eval_dir / "run_results.jsonl")
    aggregate = read_json(eval_dir / "aggregate_metrics.json")
    audit = read_json(audit_dir / "eval_integrity_metrics.json")
    scorecard = build_scorecard(rows, aggregate)
    summary = build_summary(rows, aggregate, audit, scorecard)

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "mimic_private_aggregate_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    (output_dir / "mimic_private_aggregate_summary.md").write_text(summary_markdown(summary), encoding="utf-8")
    write_scorecard(output_dir / "mimic_private_architecture_scorecard.csv", scorecard)
    print(f"Wrote public-safe aggregate summary to {output_dir}")


def build_summary(
    rows: list[dict[str, Any]],
    aggregate: dict[str, Any],
    audit: dict[str, Any],
    scorecard: list[dict[str, Any]],
) -> dict[str, Any]:
    private_cases = len({row.get("case_id") for row in rows})
    private_tasks = len({row.get("task_id") for row in rows})
    action_distribution: dict[str, dict[str, int]] = defaultdict(dict)
    for architecture, counter in grouped_counter(rows, "architecture", "actual_action").items():
        action_distribution[architecture] = dict(counter)
    return {
        "source": "mimic_iv_private_aggregate",
        "public_safe": True,
        "private_case_count": private_cases,
        "private_task_count": private_tasks,
        "architectures_compared": sorted({row.get("architecture") for row in rows}),
        "aggregate_action_distribution": action_distribution,
        "aggregate_cross_patient_violations": audit.get("cross_patient_violation_count", aggregate.get("overall", {}).get("cross_patient_violation_count")),
        "aggregate_task_error_rate": aggregate.get("overall", {}).get("task_error_rate"),
        "aggregate_task_error_count": audit.get("task_error_count"),
        "aggregate_citation_validity_rate": audit.get("citation_validity_rate"),
        "aggregate_unsupported_claim_count": audit.get("unsupported_claim_count"),
        "aggregate_insufficient_evidence_count": audit.get("insufficient_evidence_count"),
        "latency_by_architecture": audit.get("latency_by_architecture", {}),
        "architecture_scorecard": scorecard,
        "high_level_failure_modes": summarize_failure_modes(rows),
        "reporting_boundary": "Aggregate metrics only; no patient-level MIMIC rows, identifiers, note text, answers, or case summaries.",
    }


def summarize_failure_modes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter: Counter[tuple[str, str]] = Counter()
    for row in rows:
        architecture = str(row.get("architecture") or "unspecified")
        if row.get("error"):
            counter[(architecture, "task_error")] += 1
        if row.get("cross_patient_violation"):
            counter[(architecture, "cross_patient_violation")] += 1
        if row.get("unsupported_claims"):
            counter[(architecture, "unsupported_claims_present")] += 1
        if not row.get("action_correct"):
            counter[(architecture, "expected_action_mismatch")] += 1
    return [{"architecture": key[0], "mode": key[1], "count": value} for key, value in sorted(counter.items())]


def summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# MIMIC Private Stress-Test Aggregate Summary",
        "",
        "Public-safe aggregate summary. No patient-level identifiers, note text, answers, or case rows are included.",
        "",
        f"- Private cases: {summary['private_case_count']}",
        f"- Private tasks: {summary['private_task_count']}",
        f"- Architectures compared: {', '.join(summary['architectures_compared'])}",
        f"- Cross-patient violations: {summary['aggregate_cross_patient_violations']}",
        f"- Task error rate: {summary['aggregate_task_error_rate']}",
        f"- Citation validity rate: {summary['aggregate_citation_validity_rate']}",
        f"- Unsupported claim count: {summary['aggregate_unsupported_claim_count']}",
        "",
        "## Architecture Scorecard",
        "",
        "| Architecture | Tasks | Expected-Action Agreement | Citation Validity | Cross-Patient Violations | Unsupported Claim Rate | Median Latency ms | P95 Latency ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary["architecture_scorecard"]:
        lines.append(
            f"| {row['architecture']} | {row['task_count']} | {row['expected_action_agreement']} | "
            f"{row['citation_validity_rate']} | {row['cross_patient_violations']} | "
            f"{row['unsupported_claim_rate']} | {row['median_latency_ms']} | {row['p95_latency_ms']} |"
        )
    lines.extend(
        [
            "",
            "## Public Reporting Boundary",
            "",
            summary["reporting_boundary"],
        ]
    )
    return "\n".join(lines) + "\n"


def grouped_counter(rows: list[dict[str, Any]], group_key: str, value_key: str) -> dict[str, Counter]:
    grouped: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        grouped[str(row.get(group_key) or "unspecified")][str(row.get(value_key) or "blank")] += 1
    return grouped


def write_scorecard(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "architecture",
        "task_count",
        "task_error_rate",
        "action_distribution",
        "citation_validity_rate",
        "cross_patient_violations",
        "unsupported_claim_rate",
        "median_latency_ms",
        "p95_latency_ms",
        "expected_action_agreement",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def require_private_path(path: Path) -> None:
    normalized = str(path.resolve()).replace("\\", "/")
    if "/results/mimic_private/" not in normalized and not normalized.endswith("/results/mimic_private"):
        raise ValueError("MIMIC public-safe export inputs and outputs must stay under results/mimic_private/")


if __name__ == "__main__":
    main()
