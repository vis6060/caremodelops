"""Run local private evaluation over MIMIC pilot cases."""

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Run private MIMIC pilot evaluation.")
    parser.add_argument("--cases", required=True)
    parser.add_argument("--architectures", nargs="+", choices=DEFAULT_ARCHITECTURES, default=list(DEFAULT_ARCHITECTURES))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    cases = Path(args.cases)
    output = Path(args.output)
    if not is_private(cases) or not is_private(output):
        raise ValueError("MIMIC private evaluation inputs and outputs must stay under results/mimic_private/")

    tasks = load_public_evaluation_tasks(cases, include_adversarial=False)
    runner = PublicEvaluationRunner(cases)
    rows, failures = runner.run(tasks, list(args.architectures))
    metrics = compute_metrics(rows)
    write_evaluation_outputs(rows, failures, metrics, output)
    print(f"Evaluated {len(tasks)} private MIMIC tasks across {len(args.architectures)} architecture(s).")
    print(f"Result rows: {len(rows)}")
    print(f"Failures captured: {len(failures)}")
    print(f"Outputs written to: {output}")


def is_private(path: Path) -> bool:
    normalized = str(path.resolve()).replace("\\", "/")
    return "/results/mimic_private/" in normalized or normalized.endswith("/results/mimic_private")


if __name__ == "__main__":
    main()
