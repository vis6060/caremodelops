# cg-syn-001

Patient: Moises22 Shon148 Ritchie586 (96f0491f-13b9-67b5-5ca7-20037081f800)

Source bundle: Moises22_Ritchie586_96f0491f-13b9-67b5-5ca7-20037081f800.json

Complexity score: 160

## Complexity inputs
- Encounter: 12
- Condition: 16
- Observation: 70
- MedicationRequest: 0
- MedicationAdministration: 0
- Procedure: 38
- DiagnosticReport: 24

## Generated artifacts
- encounters.jsonl: 0
- events.jsonl: 1
- evidence.jsonl: 2
- notes.jsonl: 4
- provenance.jsonl: 11
- tasks.jsonl: 3
- overlays.json: 1

## Overlay policy
Overlay count: 1

Overlays are present only when the source bundle lacks imaging-like evidence for the required radiology note.
