# cg-syn-010

Patient: Cathie710 Stephanie963 Barrows492 (8bac0b5c-64d7-341f-be22-cf831ae3c342)

Source bundle: Cathie710_Barrows492_8bac0b5c-64d7-341f-be22-cf831ae3c342.json

Complexity score: 1207

## Complexity inputs
- Encounter: 250
- Condition: 41
- Observation: 455
- MedicationRequest: 34
- MedicationAdministration: 1
- Procedure: 135
- DiagnosticReport: 285
- CarePlan: 6

## Generated artifacts
- encounters.jsonl: 250
- events.jsonl: 1220
- evidence.jsonl: 1221
- notes.jsonl: 4
- provenance.jsonl: 11
- tasks.jsonl: 4
- overlays.json: 1

## Overlay policy
Overlay count: 1

Overlays are present only when the source bundle lacks imaging-like evidence for the required radiology note.
