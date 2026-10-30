# cg-syn-013

Patient: Dante562 Gayle448 Farrell962 (f51b72ad-f9dd-60e9-ccc0-b14dab899488)

Source bundle: Dante562_Farrell962_f51b72ad-f9dd-60e9-ccc0-b14dab899488.json

Complexity score: 2286

## Complexity inputs
- Encounter: 58
- Condition: 73
- Observation: 1510
- MedicationRequest: 161
- MedicationAdministration: 15
- Procedure: 233
- DiagnosticReport: 233
- CarePlan: 3

## Generated artifacts
- encounters.jsonl: 58
- events.jsonl: 2299
- evidence.jsonl: 2301
- notes.jsonl: 4
- provenance.jsonl: 11
- tasks.jsonl: 4
- overlays.json: 1

## Overlay policy
Overlay count: 1

Overlays are present only when the source bundle lacks imaging-like evidence for the required radiology note.
