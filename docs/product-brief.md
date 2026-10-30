# Product Brief

## Problem

Longitudinal chart review is evidence-heavy, safety-sensitive, and full of uncertainty. A useful assistant must find the right patient-specific evidence, explain what it used, avoid unsupported clinical claims, and know when the record is incomplete or conflicting.

## Target User

The target reviewer is a clinician, clinical AI evaluator, or healthcare product/engineering team assessing grounded AI behavior on chart-review tasks. ChartGround is not built for patient use or production clinical care.

## User Workflow

1. Select a synthetic case.
2. Ask a chart-review question.
3. Compare RAG, tool-using, and verified-agent outputs.
4. Inspect cited evidence and tool outputs.
5. Review whether the system answered, expressed uncertainty, escalated, or abstained appropriately.
6. Export blinded outputs for structured clinician feedback.

## Product Hypothesis

Healthcare AI workflows improve when retrieval, deterministic tools, citation validation, and action policy are treated as product primitives instead of being left entirely to generation.

## Differentiation From Generic RAG

Generic RAG retrieves text and asks a model to answer. ChartGround adds patient-scoped retrieval before ranking, canonical clinical evidence, deterministic chart-review tools, citation ownership checks, claim support checks, and explicit safety actions.

## Why Deterministic Tools Matter

Clinical review questions often ask for timelines, lab trends, medication changes, radiology comparisons, and conflicts. These are better handled by reproducible tool logic than by free-form generation alone.

## Why The Verified Agent Matters

The verified agent separates answer generation from answer verification. It validates citations, checks support for material claims, detects missing information and conflicts, and chooses whether answering is appropriate.

## Safety Principles

- Filter by patient before retrieval ranking.
- Cite clinical evidence, not provenance or validation metadata.
- Treat missing evidence as uncertainty.
- Escalate clinically important conflicts.
- Abstain from unsupported diagnosis or treatment requests.
- Keep restricted data private and report only aggregate metrics.

## What Was Evaluated

ChartGround compares `rag`, `tool_agent`, and `verified_agent` over 37 public synthetic cases, 141 authored public tasks plus runtime adversarial checks, and a 30-task blinded clinician-review export package.

## Current Status

The public benchmark, evaluation harness, clinician-review export package, and private aggregate-only stress-test reporting are implemented locally. Public results show stronger action behavior for tool and verified-agent architectures than the baseline RAG path, with 0 cross-patient violations and 0 task errors in the latest public run.

## Next Steps

- Collect structured clinician feedback on the blinded synthetic package.
- Improve citation completeness and evidence selection.
- Expand deterministic clinical tools.
- Continue private stress testing with compliant aggregate-only reporting.
