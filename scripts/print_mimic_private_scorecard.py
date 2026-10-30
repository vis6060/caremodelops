"""Print aggregate-only private MIMIC evaluation scorecard."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(description="Print private MIMIC aggregate scorecard.")
    parser.add_argument("--eval", required=True)
    args = parser.parse_args()

    eval_dir = Path(args.eval)
    rows = read_jsonl(eval_dir / "run_results.jsonl")
    aggregate = read_json(eval_dir / "aggregate_metrics.json")
    table = build_scorecard(rows, aggregate)
    print("expected-action agreement, based on generated private task labels, not clinical validation.")
    columns = [
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
    widths = {column: max(len(column), *(len(str(row.get(column, ""))) for row in table)) for column in columns}
    print(" | ".join(column.ljust(widths[column]) for column in columns))
    print("-+-".join("-" * widths[column] for column in columns))
    for row in table:
        print(" | ".join(str(row.get(column, "")).ljust(widths[column]) for column in columns))


def build_scorecard(rows: list[dict[str, Any]], aggregate: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("architecture") or "unspecified")].append(row)
    table = []
    for architecture, arch_rows in sorted(grouped.items()):
        cited_total = 0
        cited_invalid = 0
        for row in arch_rows:
            cited = row.get("cited_evidence_ids") or []
            cited_total += len(cited)
            cited_invalid += int(bool(row.get("cross_patient_violation")))
        metrics = (aggregate.get("architectures") or {}).get(architecture, {})
        distribution = dict(Counter(str(row.get("actual_action") or "blank") for row in arch_rows))
        table.append(
            {
                "architecture": architecture,
                "task_count": len(arch_rows),
                "task_error_rate": metrics.get("task_error_rate", rate(sum(1 for row in arch_rows if row.get("error")), len(arch_rows))),
                "action_distribution": compact_distribution(distribution),
                "citation_validity_rate": round((cited_total - cited_invalid) / cited_total, 6) if cited_total else "not_applicable",
                "cross_patient_violations": metrics.get("cross_patient_violation_count", sum(1 for row in arch_rows if row.get("cross_patient_violation"))),
                "unsupported_claim_rate": metrics.get("unsupported_claim_rate", "not_applicable"),
                "median_latency_ms": metrics.get("median_latency_ms", percentile([int(row.get("latency_ms") or 0) for row in arch_rows], 50)),
                "p95_latency_ms": metrics.get("p95_latency_ms", percentile([int(row.get("latency_ms") or 0) for row in arch_rows], 95)),
                "expected_action_agreement": metrics.get("action_accuracy", rate(sum(1 for row in arch_rows if row.get("action_correct")), len(arch_rows))),
            }
        )
    return table


def compact_distribution(distribution: dict[str, int]) -> str:
    return ",".join(f"{key}:{distribution[key]}" for key in sorted(distribution))


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def percentile(values: list[int], percent: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((percent / 100) * (len(ordered) - 1))))
    return ordered[index]


if __name__ == "__main__":
    main()
