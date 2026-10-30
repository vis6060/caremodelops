# MIMIC Private Stress Test

This document describes ChartGround's private local stress-test layer using only public-safe aggregate results.

## Purpose

The private stress test checks whether the same ChartGround architecture used for public synthetic cases can run on real deidentified MIMIC-IV / MIMIC-IV-Note records mapped into the canonical schema.

## Scope

- 10 private pilot cases.
- 50 private tasks.
- 150 result rows.
- Three architectures compared: `rag`, `tool_agent`, and `verified_agent`.

## Aggregate Results

- Task errors: 0.
- Cross-patient violations: 0.
- Citation validity rate: 1.0.
- Public-safe summary generated.
- Privacy leak scan passed.

## Architecture Scorecard

| Architecture | Tasks | Expected-Action Agreement | Citation Validity | Cross-Patient Violations | Unsupported Claim Rate | Median Latency ms | P95 Latency ms |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| rag | 50 | 0.0 | 1.0 | 0 | not_applicable | 10 | 16 |
| tool_agent | 50 | 0.58 | 1.0 | 0 | not_applicable | 12 | 25 |
| verified_agent | 50 | 0.6 | 1.0 | 0 | 0.225 | 13 | 25 |

## Public Reporting Boundary

MIMIC patient-level data is not committed. No raw notes, private identifiers, patient-level answers, or individual case summaries are published. Only aggregate results may be discussed.

This stress test is not clinical validation.

## Next Possible Expansion

- Expand to 50-100 private admissions.
- Add ICU chart events.
- Add clinician-reviewed real-world task rubrics, if permitted and compliant.
- Keep all patient-level artifacts private and publish aggregate metrics only.
