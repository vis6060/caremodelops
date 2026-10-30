# cg-syn-020

Patient: Johnnie679 Clemente531 Howe413 (03dbd4d2-eb02-c13b-c8af-8f40b0edc73e)

Source bundle: Johnnie679_Howe413_03dbd4d2-eb02-c13b-c8af-8f40b0edc73e.json

Complexity score: 1213

## Complexity inputs
- Encounter: 60
- Condition: 44
- Observation: 629
- MedicationRequest: 68
- MedicationAdministration: 18
- Procedure: 245
- DiagnosticReport: 141
- CarePlan: 8

## Generated artifacts
- encounters.jsonl: 60
- events.jsonl: 1227
- evidence.jsonl: 1228
- notes.jsonl: 4
- provenance.jsonl: 11
- tasks.jsonl: 4
- overlays.json: 1

## Overlay policy
Overlay count: 1

Overlays are present only when the source bundle lacks imaging-like evidence for the required radiology note.
