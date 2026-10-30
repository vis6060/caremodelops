"""Summarize public evaluation errors and incorrect task rows."""

from __future__ import annotations

import json
from argparse import ArgumentParser
from collections import Counter
from pathlib import Path


def main() -> None:
    parser = ArgumentParser(description="Analyze ChartGround public evaluation errors.")
    parser.add_argument("--results", default="results/public_eval_37")
    parser.add_argument("--output", default="results/public_eval_37/error_analysis.md")
    args = parser.parse_args()

    results_dir = Path(args.results)
    rows = read_jsonl(results_dir / "run_results.jsonl")
    failures = read_jsonl(results_dir / "task_failures.jsonl")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_report(rows, failures), encoding="utf-8")
    print(f"Error analysis written to: {output}")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_report(rows: list[dict], failures: list[dict]) -> str:
    by_architecture = Counter(str(row.get("architecture")) for row in rows)
    errors_by_architecture = Counter(str(row.get("architecture")) for row in rows if row.get("error"))
    incorrect_by_architecture = Counter(
        str(row.get("architecture"))
        for row in rows
        if not row.get("error") and not row.get("action_correct")
    )
    unsupported_by_architecture = Counter(
        str(row.get("architecture"))
        for row in rows
        if row.get("unsupported_claims")
    )
    lines = [
        "# Public Evaluation Error Analysis",
        "",
        f"- Result rows: {len(rows)}",
        f"- Captured failures: {len(failures)}",
        "",
        "| Architecture | Rows | Errors | Incorrect Actions | Rows With Unsupported Claims |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for architecture in sorted(by_architecture):
        lines.append(
            f"| {architecture} | {by_architecture[architecture]} | {errors_by_architecture[architecture]} | "
            f"{incorrect_by_architecture[architecture]} | {unsupported_by_architecture[architecture]} |"
        )
    if failures:
        lines.extend(["", "## Captured Failures", ""])
        for failure in failures[:20]:
            lines.append(
                f"- {failure.get('architecture')} {failure.get('task_id')}: "
                f"{failure.get('error_type')} - {failure.get('message')}"
            )
    else:
        lines.extend(["", "No system failures were captured."])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
