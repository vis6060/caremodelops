# cg-syn-004

Patient: Frederick289 Hyman89 Bergstrom287 (a18a7549-55f5-dfbd-03bd-8488f664ce2f)

Source bundle: Frederick289_Bergstrom287_a18a7549-55f5-dfbd-03bd-8488f664ce2f.json

Complexity score: 134

## Complexity inputs
- Encounter: 11
- Condition: 11
- Observation: 64
- MedicationRequest: 1
- MedicationAdministration: 1
- Procedure: 24
- DiagnosticReport: 22

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
