# cg-syn-018

Patient: Johnathon489 Curtis94 O'Connell601 (39648018-2c1c-63a4-ffbd-cdbf994bb297)

Source bundle: Johnathon489_O'Connell601_39648018-2c1c-63a4-ffbd-cdbf994bb297.json

Complexity score: 1909

## Complexity inputs
- Encounter: 63
- Condition: 43
- Observation: 1158
- MedicationRequest: 90
- MedicationAdministration: 43
- Procedure: 273
- DiagnosticReport: 233
- CarePlan: 6

## Generated artifacts
- encounters.jsonl: 63
- events.jsonl: 1920
- evidence.jsonl: 1921
- notes.jsonl: 4
- provenance.jsonl: 12
- tasks.jsonl: 4
- overlays.json: 1

## Overlay policy
Overlay count: 1

Overlays are present only when the source bundle lacks imaging-like evidence for the required radiology note.
