# Demo Script

This demo uses public synthetic data only.

## Commands

Run public evaluation:

```powershell
python scripts/run_public_evaluation.py --architectures rag tool_agent verified_agent --output results/public_eval_37
```

Print scorecard:

```powershell
python scripts/print_scorecard.py --results results/public_eval_37
```

Generate clinician-review package:

```powershell
python scripts/create_clinician_review_package.py --results results/public_eval_37 --cases data/public_synthetic/cases --output results/clinician_review --task-count 30 --seed 6060
```

Run verified-agent demo:

```powershell
python scripts/agent_demo.py --case-id cg-syn-001 --architecture verified_agent --question "What changed during this encounter?"
```

Compare architectures:

```powershell
python scripts/compare_architectures.py --case-id cg-syn-001 --question "What changed during this encounter?"
```

## Five-Minute Flow

1. Show the problem: chart review needs grounded answers, not just fluent summaries.
2. Show a public synthetic case and its canonical evidence files.
3. Compare RAG vs `tool_agent` vs `verified_agent`.
4. Show citation validation and claim checking.
5. Show safety behavior for uncertainty, conflicts, abstention, and cross-patient boundaries.
6. Show the clinician-review export package.
7. Mention the private MIMIC stress test only at the aggregate level.

## Talk Track

"ChartGround asks what a healthcare AI assistant should do before it answers. It retrieves only inside the selected patient, computes structured clinical facts with deterministic tools, validates citations, checks claim support, and chooses whether to answer, say it is uncertain, escalate, or abstain."
