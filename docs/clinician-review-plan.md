# Clinician Review Plan

## Purpose

The clinician-review package is designed to collect structured expert feedback on synthetic chart-review outputs. It tests whether outputs are useful, supported, appropriately cautious, and clear enough for review workflows.

## What Clinicians Review

- 30 synthetic-data tasks.
- 90 blinded output rows.
- Three architectures hidden as Output A, Output B, and Output C.

## Generated Files

- `clinician_review_blinded_outputs.csv`
- `clinician_review_rubric.csv`
- `clinician_review_instructions.md`
- Private answer key retained locally.

## Scoring Rubric

Reviewers score:

- Correctness.
- Omissions.
- Citation support.
- Uncertainty handling.
- Escalation appropriateness.
- Clarity and usefulness.
- Correction burden.
- Potential harm.

## Review Boundary

The clinician-review package uses synthetic data only. It is structured expert feedback, not clinical validation. No MIMIC-derived patient-level data, raw notes, or private evaluation rows are sent to clinicians.
