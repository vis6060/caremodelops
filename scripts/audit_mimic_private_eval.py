"""Audit private MIMIC evaluation outputs without exposing patient-level content."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


VALID_ACTIONS = {"answer", "uncertain", "escalate", "abstain"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit private MIMIC evaluation integrity.")
    parser.add_argument("--eval", required=True)
    parser.add_argument("--cases", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    eval_dir = Path(args.eval)
    cases_dir = Path(args.cases)
    output_dir = Path(args.output)
    require_private_path(eval_dir)
    require_private_path(cases_dir)
    require_private_path(output_dir)
    rows = read_jsonl(eval_dir / "run_results.jsonl")
    failures = read_jsonl(eval_dir / "task_failures.jsonl")
    evidence_by_id = load_case_evidence(cases_dir)
    metrics = audit_rows(rows, failures, evidence_by_id)
    failure_modes = build_failure_modes(rows)

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "eval_integrity_metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")
    (output_dir / "eval_integrity_summary.md").write_text(summary_markdown(metrics), encoding="utf-8")
    write_failure_modes(output_dir / "private_failure_modes.csv", failure_modes)
    print(f"Audited {metrics['result_rows']} private result rows across {metrics['architecture_count']} architecture(s).")
    print(f"Cross-patient violations: {metrics['cross_patient_violation_count']}")
    print(f"Task errors: {metrics['task_error_count']}")


def audit_rows(rows: list[dict[str, Any]], failures: list[dict[str, Any]], evidence_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    architectures = sorted({str(row.get("architecture")) for row in rows if row.get("architecture")})
    task_ids = {row.get("task_id") for row in rows}
    invalid_actions = [row for row in rows if row.get("actual_action") not in VALID_ACTIONS]
    missing_citations = [row for row in rows if row.get("citation_applicable", True) and row.get("gold_evidence_ids") and not row.get("cited_evidence_ids")]
    missing_evidence = 0
    wrong_patient = 0
    cited_total = 0
    cited_valid = 0
    for row in rows:
        patient_id = row.get("patient_id")
        for evidence_id in row.get("cited_evidence_ids") or []:
            cited_total += 1
            evidence = evidence_by_id.get(str(evidence_id))
            if not evidence:
                missing_evidence += 1
                continue
            if evidence.get("patient_id") != patient_id:
                wrong_patient += 1
                continue
            cited_valid += 1
    unsupported_claim_count = sum(len(row.get("unsupported_claims") or []) for row in rows)
    insufficient_count = sum(
        1
        for row in rows
        for claim in row.get("unsupported_claims") or []
        if claim.get("support_status") == "insufficient_evidence"
    )
    conflict_count = sum(len(row.get("conflicts") or []) for row in rows)
    return {
        "task_count": len(task_ids),
        "architecture_count": len(architectures),
        "architectures": architectures,
        "result_rows": len(rows),
        "task_error_count": len(failures) + sum(1 for row in rows if row.get("error")),
        "missing_answer_count": sum(1 for row in rows if not str(row.get("answer") or "").strip()),
        "blank_action_count": sum(1 for row in rows if not str(row.get("actual_action") or "").strip()),
        "invalid_action_count": len(invalid_actions),
        "missing_cited_evidence_ids_count": len(missing_citations),
        "cited_evidence_missing_count": missing_evidence,
        "cited_evidence_wrong_patient_count": wrong_patient,
        "citation_validity_rate": round(cited_valid / cited_total, 6) if cited_total else "not_applicable",
        "cross_patient_violation_count": sum(1 for row in rows if row.get("cross_patient_violation")) + wrong_patient,
        "unsupported_claim_count": unsupported_claim_count,
        "insufficient_evidence_count": insufficient_count,
        "conflict_count": conflict_count,
        "latency_by_architecture": latency_summary(rows),
        "action_distribution_by_architecture": distributions(rows, "architecture", "actual_action"),
        "task_type_distribution": dict(Counter(str(row.get("task_type") or "unspecified") for row in rows)),
        "evaluation_focus_distribution": dict(Counter(str(row.get("evaluation_focus") or "unspecified") for row in rows)),
    }


def latency_summary(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("architecture") or "unspecified")].append(int(row.get("latency_ms") or 0))
    return {
        key: {
            "median_latency_ms": percentile(values, 50),
            "p95_latency_ms": percentile(values, 95),
            "min_latency_ms": min(values) if values else 0,
            "max_latency_ms": max(values) if values else 0,
        }
        for key, values in sorted(grouped.items())
    }


def distributions(rows: list[dict[str, Any]], group_key: str, value_key: str) -> dict[str, dict[str, int]]:
    grouped: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        grouped[str(row.get(group_key) or "unspecified")][str(row.get(value_key) or "blank")] += 1
    return {key: dict(counter) for key, counter in sorted(grouped.items())}


def build_failure_modes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter: Counter[tuple[str, str, str, str]] = Counter()
    for row in rows:
        architecture = str(row.get("architecture") or "unspecified")
        task_type = str(row.get("task_type") or "unspecified")
        focus = str(row.get("evaluation_focus") or "unspecified")
        if row.get("error"):
            counter[(architecture, task_type, focus, "task_error")] += 1
        if not row.get("action_correct"):
            counter[(architecture, task_type, focus, "expected_action_mismatch")] += 1
        if row.get("cross_patient_violation"):
            counter[(architecture, task_type, focus, "cross_patient_violation")] += 1
        if row.get("unsupported_claims"):
            counter[(architecture, task_type, focus, "unsupported_claims_present")] += 1
        if not str(row.get("answer") or "").strip():
            counter[(architecture, task_type, focus, "missing_answer")] += 1
    return [
        {"architecture": key[0], "task_type": key[1], "evaluation_focus": key[2], "failure_mode": key[3], "count": count}
        for key, count in sorted(counter.items())
    ]


def summary_markdown(metrics: dict[str, Any]) -> str:
    lines = [
        "# MIMIC Private Evaluation Integrity Summary",
        "",
        "Aggregate-only summary. No patient-level identifiers or note text are included.",
        "",
        f"- Private tasks: {metrics['task_count']}",
        f"- Architectures: {metrics['architecture_count']}",
        f"- Result rows: {metrics['result_rows']}",
        f"- Task errors: {metrics['task_error_count']}",
        f"- Cross-patient violations: {metrics['cross_patient_violation_count']}",
        f"- Citation validity rate: {metrics['citation_validity_rate']}",
        f"- Unsupported claims: {metrics['unsupported_claim_count']}",
        f"- Insufficient-evidence claims: {metrics['insufficient_evidence_count']}",
        f"- Conflicts surfaced: {metrics['conflict_count']}",
        "",
        "## Action Distribution",
        "",
    ]
    for architecture, distribution in metrics["action_distribution_by_architecture"].items():
        lines.append(f"- {architecture}: {distribution}")
    return "\n".join(lines) + "\n"


def write_failure_modes(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = ["architecture", "task_type", "evaluation_focus", "failure_mode", "count"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def load_case_evidence(cases_dir: Path) -> dict[str, dict[str, Any]]:
    evidence: dict[str, dict[str, Any]] = {}
    for path in sorted(cases_dir.glob("mimic-pilot-*/evidence.jsonl")):
        for row in read_jsonl(path):
            evidence[str(row.get("evidence_id"))] = row
    return evidence


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def percentile(values: list[int], percent: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((percent / 100) * (len(ordered) - 1))))
    return ordered[index]


def require_private_path(path: Path) -> None:
    normalized = str(path.resolve()).replace("\\", "/")
    if "/results/mimic_private/" not in normalized and not normalized.endswith("/results/mimic_private"):
        raise ValueError("MIMIC audit inputs and outputs must stay under results/mimic_private/")


if __name__ == "__main__":
    main()
