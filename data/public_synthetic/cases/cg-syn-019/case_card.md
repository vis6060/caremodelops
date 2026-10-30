# cg-syn-019

Patient: Johnie961 Sanford861 Hills818 (03fded39-5f96-d73c-99bc-9de16a781c10)

Source bundle: Johnie961_Hills818_03fded39-5f96-d73c-99bc-9de16a781c10.json

Complexity score: 1959

## Complexity inputs
- Encounter: 89
- Condition: 86
- Observation: 1087
- MedicationRequest: 73
- MedicationAdministration: 18
- Procedure: 368
- DiagnosticReport: 232
- CarePlan: 6

## Generated artifacts
- encounters.jsonl: 89
- events.jsonl: 1971
- evidence.jsonl: 1972
- notes.jsonl: 4
- provenance.jsonl: 12
- tasks.jsonl: 4
- overlays.json: 1

## Overlay policy
Overlay count: 1

Overlays are present only when the source bundle lacks imaging-like evidence for the required radiology note.
