# cg-syn-007

Patient: Clement78 Chauncey770 Reilly981 (78f78281-31b8-408c-4a99-7dd75bd7d9e5)

Source bundle: Clement78_Reilly981_78f78281-31b8-408c-4a99-7dd75bd7d9e5.json

Complexity score: 15997

## Complexity inputs
- Encounter: 421
- Condition: 374
- Observation: 10938
- MedicationRequest: 1056
- MedicationAdministration: 57
- Procedure: 1548
- DiagnosticReport: 1603

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
