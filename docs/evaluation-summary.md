# Evaluation Summary

## Public Benchmark

The public benchmark contains 37 synthetic ChartGround cases and 141 authored public tasks. The current evaluation run also includes runtime adversarial checks, producing 151 evaluated tasks per architecture.

## Architectures Compared

- `rag`
- `tool_agent`
- `verified_agent`

## Metrics

- Action accuracy / expected-action agreement.
- Citation precision.
- Citation completeness.
- Unsupported claim rate.
- Task error rate.
- Cross-patient violations.
- Prompt-injection success count.
- Escalation and abstention recall.
- Latency and tool-call count.

## Latest Public Scorecard

| Architecture | Evaluated Tasks | Action Accuracy | Citation Precision | Citation Completeness | Unsupported Claim Rate | Cross-Patient Violations | Task Error Rate |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| rag | 151 | 0.07947 | 0.093813 | 0.310606 | not_applicable | 0 | 0.0 |
| tool_agent | 151 | 0.900662 | 0.299134 | 0.666667 | not_applicable | 0 | 0.0 |
| verified_agent | 151 | 1.0 | 0.299134 | 0.666667 | 0.055276 | 0 | 0.0 |

## Main Finding

Tool use improved action behavior over the baseline RAG path, and the verified-agent architecture improved safety and grounding behavior by adding citation validation, claim support checks, prompt-injection handling, and explicit abstention. Patient isolation remained intact in the latest public run.

## Interpretation

These scores are useful for product and architecture comparison, but they are not clinical validation. Synthetic expected-action labels can test safety logic and evaluation plumbing, but they do not prove real-world clinical correctness.

## Limitations

- Synthetic cases do not capture full real-world chart complexity.
- Some task labels are generated or calibrated heuristically.
- Citation completeness depends on the quality of gold evidence IDs.
- The deterministic fallback answerer is intentionally simple.
- Clinician review is still needed before making stronger product claims.
