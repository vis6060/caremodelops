# cg-syn-011

Patient: Claude750 Hoyt490 Nader710 (05b9cb37-7ecb-c9c0-6d9a-702c690c4df7)

Source bundle: Claude750_Nader710_05b9cb37-7ecb-c9c0-6d9a-702c690c4df7.json

Complexity score: 1184

## Complexity inputs
- Encounter: 99
- Condition: 49
- Observation: 579
- MedicationRequest: 42
- MedicationAdministration: 13
- Procedure: 231
- DiagnosticReport: 167
- CarePlan: 4

## Generated artifacts
- encounters.jsonl: 99
- events.jsonl: 1199
- evidence.jsonl: 1201
- notes.jsonl: 4
- provenance.jsonl: 11
- tasks.jsonl: 4
- overlays.json: 1

## Overlay policy
Overlay count: 1

Overlays are present only when the source bundle lacks imaging-like evidence for the required radiology note.
