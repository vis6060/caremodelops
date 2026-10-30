# cg-syn-014

Patient: Elwood28 Raymond398 Kassulke119 (3c6b2a2f-edc2-4e29-6098-f673c4eced68)

Source bundle: Elwood28_Kassulke119_3c6b2a2f-edc2-4e29-6098-f673c4eced68.json

Complexity score: 1610

## Complexity inputs
- Encounter: 51
- Condition: 53
- Observation: 1039
- MedicationRequest: 103
- MedicationAdministration: 5
- Procedure: 189
- DiagnosticReport: 166
- CarePlan: 4

## Generated artifacts
- encounters.jsonl: 51
- events.jsonl: 1624
- evidence.jsonl: 1625
- notes.jsonl: 4
- provenance.jsonl: 11
- tasks.jsonl: 4
- overlays.json: 1

## Overlay policy
Overlay count: 1

Overlays are present only when the source bundle lacks imaging-like evidence for the required radiology note.
