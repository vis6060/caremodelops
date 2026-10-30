# cg-syn-008

Patient: Alonzo487 Maria750 Powlowski563 (18e9c2f8-6b6a-9d58-b016-3efbac871853)

Source bundle: Alonzo487_Powlowski563_18e9c2f8-6b6a-9d58-b016-3efbac871853.json

Complexity score: 1739

## Complexity inputs
- Encounter: 92
- Condition: 67
- Observation: 959
- MedicationRequest: 106
- MedicationAdministration: 6
- Procedure: 296
- DiagnosticReport: 209
- CarePlan: 4

## Generated artifacts
- encounters.jsonl: 92
- events.jsonl: 1755
- evidence.jsonl: 1756
- notes.jsonl: 4
- provenance.jsonl: 11
- tasks.jsonl: 4
- overlays.json: 1

## Overlay policy
Overlay count: 1

Overlays are present only when the source bundle lacks imaging-like evidence for the required radiology note.
