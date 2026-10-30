# cg-syn-022

Patient: Judson999 Kiehn525 (34c4c8b2-4e8f-18cc-0e30-27cdbdf25721)

Source bundle: Judson999_Kiehn525_34c4c8b2-4e8f-18cc-0e30-27cdbdf25721.json

Complexity score: 1498

## Complexity inputs
- Encounter: 58
- Condition: 66
- Observation: 907
- MedicationRequest: 41
- MedicationAdministration: 8
- Procedure: 246
- DiagnosticReport: 168
- CarePlan: 4

## Generated artifacts
- encounters.jsonl: 58
- events.jsonl: 1513
- evidence.jsonl: 1514
- notes.jsonl: 4
- provenance.jsonl: 11
- tasks.jsonl: 4
- overlays.json: 1

## Overlay policy
Overlay count: 1

Overlays are present only when the source bundle lacks imaging-like evidence for the required radiology note.
