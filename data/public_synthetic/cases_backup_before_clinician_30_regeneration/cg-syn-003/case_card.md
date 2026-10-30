# cg-syn-003

Patient: Gordon377 Nick779 Mayert710 (61881389-a751-276d-d508-7c3975573c04)

Source bundle: Gordon377_Mayert710_61881389-a751-276d-d508-7c3975573c04.json

Complexity score: 152

## Complexity inputs
- Encounter: 14
- Condition: 18
- Observation: 62
- MedicationRequest: 4
- MedicationAdministration: 1
- Procedure: 32
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
