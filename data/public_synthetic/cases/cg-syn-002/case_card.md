# cg-syn-002

Patient: Gerard367 Grover559 Effertz744 (2a0cd458-67da-bba4-745f-e7ffd120a576)

Source bundle: Gerard367_Effertz744_2a0cd458-67da-bba4-745f-e7ffd120a576.json

Complexity score: 154

## Complexity inputs
- Encounter: 10
- Condition: 10
- Observation: 68
- MedicationRequest: 1
- MedicationAdministration: 1
- Procedure: 43
- DiagnosticReport: 21

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
