# cg-syn-025

Patient: Lanny564 Sean831 Balistreri607 (2270fda7-48fb-8425-b221-1c79595e83f7)

Source bundle: Lanny564_Balistreri607_2270fda7-48fb-8425-b221-1c79595e83f7.json

Complexity score: 1504

## Complexity inputs
- Encounter: 76
- Condition: 67
- Observation: 677
- MedicationRequest: 135
- MedicationAdministration: 16
- Procedure: 345
- DiagnosticReport: 181
- CarePlan: 7

## Generated artifacts
- encounters.jsonl: 76
- events.jsonl: 1520
- evidence.jsonl: 1521
- notes.jsonl: 4
- provenance.jsonl: 11
- tasks.jsonl: 4
- overlays.json: 1

## Overlay policy
Overlay count: 1

Overlays are present only when the source bundle lacks imaging-like evidence for the required radiology note.
