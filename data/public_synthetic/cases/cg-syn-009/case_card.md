# cg-syn-009

Patient: Bernie827 Fahey393 (65d77495-c38b-ca1c-e787-0ccb5a6f6f76)

Source bundle: Bernie827_Fahey393_65d77495-c38b-ca1c-e787-0ccb5a6f6f76.json

Complexity score: 1632

## Complexity inputs
- Encounter: 110
- Condition: 61
- Observation: 813
- MedicationRequest: 36
- MedicationAdministration: 5
- Procedure: 362
- DiagnosticReport: 238
- CarePlan: 7

## Generated artifacts
- encounters.jsonl: 110
- events.jsonl: 1652
- evidence.jsonl: 1653
- notes.jsonl: 4
- provenance.jsonl: 11
- tasks.jsonl: 4
- overlays.json: 1

## Overlay policy
Overlay count: 1

Overlays are present only when the source bundle lacks imaging-like evidence for the required radiology note.
