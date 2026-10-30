# cg-syn-015

Patient: Emory494 Ollie731 Douglas31 (e9029855-1b0f-523c-a96c-183a80ab96b2)

Source bundle: Emory494_Douglas31_e9029855-1b0f-523c-a96c-183a80ab96b2.json

Complexity score: 1440

## Complexity inputs
- Encounter: 71
- Condition: 71
- Observation: 724
- MedicationRequest: 113
- MedicationAdministration: 12
- Procedure: 276
- DiagnosticReport: 164
- CarePlan: 9

## Generated artifacts
- encounters.jsonl: 71
- events.jsonl: 1453
- evidence.jsonl: 1454
- notes.jsonl: 4
- provenance.jsonl: 11
- tasks.jsonl: 4
- overlays.json: 1

## Overlay policy
Overlay count: 1

Overlays are present only when the source bundle lacks imaging-like evidence for the required radiology note.
