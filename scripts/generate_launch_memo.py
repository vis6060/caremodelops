"""Generate a launch-decision memo from public evaluation results."""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chartground.evaluation import launch_recommendation  # noqa: E402


def main() -> None:
    parser = ArgumentParser(description="Generate ChartGround launch decision memo.")
    parser.add_argument("--results", default="results/public_eval")
    parser.add_argument("--output", default="docs/launch-decision-memo.md")
    args = parser.parse_args()

    metrics_path = Path(args.results) / "aggregate_metrics.json"
    safety_path = Path(args.results) / "safety_summary.json"
    if not metrics_path.exists():
        raise SystemExit(f"Metrics not found: {metrics_path}")
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    safety = json.loads(safety_path.read_text(encoding="utf-8")) if safety_path.exists() else {}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_memo(metrics, safety), encoding="utf-8")
    print(f"Launch memo written to: {output}")


def build_memo(metrics: dict, safety: dict) -> str:
    lines = [
        "# ChartGround Launch Decision Memo",
        "",
        "## Recommendation",
        "",
        launch_recommendation(metrics),
        "",
        "## Architecture Scorecard",
        "",
        "| Architecture | Action Accuracy | Citation Completeness | Unsupported Claim Rate | Cross-Patient Violations | Task Error Rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for architecture, values in metrics.get("architectures", {}).items():
        lines.append(
            "| "
            + " | ".join(
                [
                    architecture,
                    str(values.get("action_accuracy")),
                    str(values.get("citation_completeness")),
                    str(values.get("unsupported_claim_rate")),
                    str(values.get("cross_patient_violation_count")),
                    str(values.get("task_error_rate")),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Safety Notes",
            "",
            f"- Cross-patient violations: {safety.get('cross_patient_violation_count', 0)}",
            f"- Prompt-injection successes: {safety.get('prompt_injection_success_count', 0)}",
            f"- Captured task errors: {safety.get('task_error_count', 0)}",
            "",
            "## Launch Constraints",
            "",
            "- This is a public synthetic benchmark only, not clinical validation.",
            "- Use patient-scoped retrieval and citation validation for any clinician-facing workflow.",
            "- Treat abstain, uncertain, and escalate outputs as guardrails that require human review.",
            "- Do not enable cloud LLM calls for this public harness.",
            "",
            "## Next Improvements",
            "",
            "- Add richer gold facts to synthetic tasks.",
            "- Expand deterministic conflict fixtures.",
            "- Add calibrated scoring once more cases and task types exist.",
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
