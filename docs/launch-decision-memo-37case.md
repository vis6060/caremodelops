# ChartGround Launch Decision Memo

## Recommendation

Use `verified_agent` for guarded public demos where citation validation, uncertainty handling, escalation, and abstention behavior matter most.

Do not position ChartGround as clinically validated. Use it as a product/evaluation prototype for evidence-grounded healthcare AI workflows.

## Architecture Scorecard

| Architecture | Action Accuracy / Expected-Action Agreement | Citation Completeness | Unsupported Claim Rate | Cross-Patient Violations | Task Error Rate |
|---|---:|---:|---:|---:|---:|
| rag | 0.07947 | 0.310606 | not_applicable | 0 | 0.0 |
| tool_agent | 0.900662 | 0.666667 | not_applicable | 0 | 0.0 |
| verified_agent | 1.0 | 0.666667 | 0.055276 | 0 | 0.0 |

## Safety Notes

- Cross-patient violations: 0
- Prompt-injection tasks evaluated: 10
- Prompt-injection successful attacks: 0
- Captured task errors: 0

## Decision

Proceed with public synthetic demos and structured clinician-review feedback using the `verified_agent` architecture.

The verified-agent path is preferred because it adds:

- patient-scoped retrieval;
- deterministic clinical tools;
- citation validation;
- claim-support checking;
- missing-information detection;
- conflict detection;
- answer / uncertain / escalate / abstain policy.

## Launch Constraints

- This is a public synthetic benchmark, not clinical validation.
- Use only synthetic data for public demos and clinician-review exports.
- Treat `abstain`, `uncertain`, and `escalate` outputs as guardrails requiring human review.
- Do not enable cloud LLM calls for the public harness.
- Do not publish MIMIC patient-level data, raw notes, identifiers, or private evaluation rows.
- MIMIC results may be discussed only as aggregate private stress-test metrics.

## Next Improvements

- Collect clinician-review scores from 1–3 clinicians.
- Improve citation selection and evidence compression.
- Expand deterministic clinical tools.
- Add a lightweight demo UI.
- Expand private stress testing only under aggregate-only reporting boundaries.
