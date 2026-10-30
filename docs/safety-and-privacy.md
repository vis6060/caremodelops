# Safety And Privacy

## Patient-Scoped Retrieval

ChartGround filters by trusted `patient_id` before retrieval ranking. The search path is designed so a patient-scoped query cannot return another patient's evidence.

## Cross-Patient Leakage Prevention

Evaluation includes cross-patient safety tasks and runtime checks. Citation validation also rejects evidence IDs that do not belong to the requested patient.

## Prompt-Injection Handling

The verified agent treats requests to ignore safety rules, citations, or patient boundaries as unsafe. Prompt-injection tasks are included in the public evaluation harness.

## Citation Validation

Cited evidence must exist, belong to the requested patient, and be clinical evidence. Provenance and safety metadata remain available for validation, but they are not ranked as clinician-facing evidence by default.

## Claim Verification

The verified agent extracts material claims and checks whether cited evidence supports them. Unsupported claims push the action toward uncertainty or abstention.

## Action Policy

- `answer`: evidence directly supports the response.
- `uncertain`: evidence is incomplete or insufficient.
- `escalate`: clinically important conflict is detected.
- `abstain`: the request is unsupported, unsafe, or asks for cross-patient evidence.

## Synthetic Public Benchmark

Public cases are synthetic Synthea-derived records. They are appropriate for reproducible demos and evaluation plumbing, but not for proving clinical performance.

## Restricted-Data Controls

The private MIMIC stress test is local only. Raw data, private case rows, patient-level outputs, raw notes, and private identifiers stay out of public documentation and version control.

## Safe To Publish

- Public synthetic cases.
- Source code.
- Public evaluation summaries.
- Clinician-review instructions and blinded synthetic outputs.
- Aggregate-only private stress-test metrics.

## Must Stay Private

- Restricted raw data.
- Private generated cases.
- Patient-level private evaluation rows.
- Raw clinical note text.
- Private identifiers.
- Local private filesystem paths.

## Medical Device Boundary

ChartGround is a research and portfolio prototype. It is not a medical device, not a clinical decision support product, and not intended for diagnosis, treatment, patient advice, or clinical deployment.
