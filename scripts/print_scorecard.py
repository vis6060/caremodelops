"""Print a compact public evaluation scorecard."""

from __future__ import annotations

import csv
import sys
from argparse import ArgumentParser
from pathlib import Path


def main() -> None:
    parser = ArgumentParser(description="Print ChartGround public evaluation scorecard.")
    parser.add_argument("--results", default="results/public_eval")
    args = parser.parse_args()

    scorecard = Path(args.results) / "architecture_scorecard.csv"
    if not scorecard.exists():
        raise SystemExit(f"Scorecard not found: {scorecard}")

    with scorecard.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    columns = [
        "architecture",
        "task_count",
        "action_accuracy",
        "citation_precision",
        "citation_completeness",
        "unsupported_claim_rate",
        "cross_patient_violation_count",
        "task_error_rate",
    ]
    widths = {column: max(len(column), *(len(str(row.get(column, ""))) for row in rows)) for column in columns}
    print(" | ".join(column.ljust(widths[column]) for column in columns))
    print("-+-".join("-" * widths[column] for column in columns))
    for row in rows:
        print(" | ".join(str(row.get(column, "")).ljust(widths[column]) for column in columns))


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)
