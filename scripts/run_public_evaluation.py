"""Run ChartGround public synthetic evaluation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chartground.evaluation import (  # noqa: E402
    DEFAULT_ARCHITECTURES,
    PublicEvaluationRunner,
    compute_metrics,
    load_public_evaluation_tasks,
    write_evaluation_outputs,
)
from chartground.evidence_store import DEFAULT_CASES_ROOT  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the public ChartGround evaluation harness.")
    parser.add_argument("--cases-root", default=str(DEFAULT_CASES_ROOT))
    parser.add_argument("--architecture", action="append", choices=DEFAULT_ARCHITECTURES)
    parser.add_argument("--architectures", nargs="+", choices=DEFAULT_ARCHITECTURES)
    parser.add_argument("--case-id")
    parser.add_argument("--task-type")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", default="results/public_eval")
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args()

    architectures = args.architectures or args.architecture or list(DEFAULT_ARCHITECTURES)
    tasks = load_public_evaluation_tasks(args.cases_root)
    if args.case_id:
        tasks = [task for task in tasks if task.case_id == args.case_id]
    if args.task_type:
        tasks = [task for task in tasks if task.task_type == args.task_type]
    if args.limit is not None:
        tasks = tasks[: args.limit]
    if not tasks:
        raise SystemExit("No evaluation tasks matched the requested filters.")

    runner = PublicEvaluationRunner(args.cases_root)
    rows, failures = runner.run(tasks, list(architectures), fail_fast=args.fail_fast)
    metrics = compute_metrics(rows)
    write_evaluation_outputs(rows, failures, metrics, args.output)

    print(f"Evaluated {len(tasks)} tasks across {len(architectures)} architecture(s).")
    print(f"Result rows: {len(rows)}")
    print(f"Failures captured: {len(failures)}")
    print(f"Outputs written to: {Path(args.output)}")


if __name__ == "__main__":
    main()
