# cg-syn-023

Patient: Kareem959 Brenton674 Kuvalis369 (31b47e18-355d-9994-87d5-c9d3f798554e)

Source bundle: Kareem959_Kuvalis369_31b47e18-355d-9994-87d5-c9d3f798554e.json

Complexity score: 162

## Complexity inputs
- Encounter: 11
- Condition: 14
- Observation: 70
- MedicationRequest: 0
- MedicationAdministration: 0
- Procedure: 44
- DiagnosticReport: 23
- CarePlan: 0

## Generated artifacts
- encounters.jsonl: 11
- events.jsonl: 173
- evidence.jsonl: 174
- notes.jsonl: 4
- provenance.jsonl: 11
- tasks.jsonl: 4
- overlays.json: 1

## Overlay policy
Overlay count: 1

Overlays are present only when the source bundle lacks imaging-like evidence for the required radiology note.
