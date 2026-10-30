# cg-syn-012

Patient: Cornelius968 Carson894 Daniel959 (2f6d78a0-1a81-cc53-4fc4-8a6d4109a2aa)

Source bundle: Cornelius968_Daniel959_2f6d78a0-1a81-cc53-4fc4-8a6d4109a2aa.json

Complexity score: 3063

## Complexity inputs
- Encounter: 81
- Condition: 97
- Observation: 2062
- MedicationRequest: 61
- MedicationAdministration: 18
- Procedure: 405
- DiagnosticReport: 334
- CarePlan: 5

## Generated artifacts
- encounters.jsonl: 81
- events.jsonl: 3079
- evidence.jsonl: 3081
- notes.jsonl: 4
- provenance.jsonl: 11
- tasks.jsonl: 4
- overlays.json: 1

## Overlay policy
Overlay count: 1

Overlays are present only when the source bundle lacks imaging-like evidence for the required radiology note.
