# cg-syn-021

Patient: Joi660 Grant908 (c6b5eeea-95f2-dfd1-4321-09c193733ab4)

Source bundle: Joi660_Grant908_c6b5eeea-95f2-dfd1-4321-09c193733ab4.json

Complexity score: 1330

## Complexity inputs
- Encounter: 77
- Condition: 34
- Observation: 745
- MedicationRequest: 37
- MedicationAdministration: 10
- Procedure: 242
- DiagnosticReport: 183
- CarePlan: 2

## Generated artifacts
- encounters.jsonl: 77
- events.jsonl: 1345
- evidence.jsonl: 1346
- notes.jsonl: 4
- provenance.jsonl: 11
- tasks.jsonl: 4
- overlays.json: 1

## Overlay policy
Overlay count: 1

Overlays are present only when the source bundle lacks imaging-like evidence for the required radiology note.
