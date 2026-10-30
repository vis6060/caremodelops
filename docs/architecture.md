# Architecture

## Data Flow

```text
Synthea FHIR / private restricted records
  -> ChartGround canonical schema
  -> evidence store
  -> retrieval and deterministic tools
  -> rag / tool_agent / verified_agent
  -> evaluation
```

The same source-neutral schema is used for public synthetic cases and private local stress-test adapters. Public repository artifacts use synthetic data only.

## Canonical Files

- `patients.jsonl`: patient-level canonical demographics and metadata.
- `encounters.jsonl`: encounter spans and encounter metadata.
- `events.jsonl`: structured clinical events such as labs, conditions, medications, procedures, and reports.
- `notes.jsonl`: deterministic note evidence split into sentence-level records where available.
- `evidence.jsonl`: searchable clinical evidence records.
- `provenance.jsonl`: source mapping and sentence-level provenance.
- `tasks.jsonl`: benchmark tasks and expected action behavior.
- `expected_behavior.json`: case-level expectations and evaluation metadata.

## Evidence Store

The evidence store loads clinical records, note evidence, and provenance metadata without silently dropping malformed rows. Retrieval is patient-scoped before ranking, and clinician-facing search defaults to clinical evidence only.

## Architecture Comparison

`rag` retrieves patient-scoped evidence and formats a deterministic grounded response when no local LLM is configured.

`tool_agent` plans deterministic tool calls for chart-review questions, runs them with the trusted patient context, and summarizes tool outputs with citations.

`verified_agent` runs the tool-agent path, validates citations, extracts claims, checks support, detects missing information or conflicts, and chooses the safest action.

## Tool Registry

- `build_patient_timeline`
- `get_lab_trend`
- `get_medication_changes`
- `compare_radiology_reports`
- `search_clinical_notes`
- `detect_record_conflicts`

## Verification Pipeline

```text
retrieve
  -> cite
  -> extract claims
  -> validate citations
  -> verify support
  -> detect missing/conflict
  -> answer / uncertain / escalate / abstain
```

The action policy is intentionally conservative: answer only when evidence directly supports the response, use uncertainty for incomplete records, escalate important conflicts, and abstain from unsupported or unsafe requests.
