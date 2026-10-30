# cg-syn-024

Patient: Kristen940 Eva64 Greenfelder433 (6e074740-b2fd-3aa8-620c-b83832271fc6)

Source bundle: Kristen940_Greenfelder433_6e074740-b2fd-3aa8-620c-b83832271fc6.json

Complexity score: 2424

## Complexity inputs
- Encounter: 68
- Condition: 75
- Observation: 1465
- MedicationRequest: 236
- MedicationAdministration: 17
- Procedure: 287
- DiagnosticReport: 270
- CarePlan: 6

## Generated artifacts
- encounters.jsonl: 68
- events.jsonl: 2439
- evidence.jsonl: 2440
- notes.jsonl: 4
- provenance.jsonl: 11
- tasks.jsonl: 4
- overlays.json: 1

## Overlay policy
Overlay count: 1

Overlays are present only when the source bundle lacks imaging-like evidence for the required radiology note.
