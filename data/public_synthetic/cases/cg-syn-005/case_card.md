# cg-syn-005

Patient: Rickey821 Ambrose149 Hilll811 (e283a1ed-e69b-fadc-1ef4-cae6ad541eb7)

Source bundle: Rickey821_Hilll811_e283a1ed-e69b-fadc-1ef4-cae6ad541eb7.json

Complexity score: 133

## Complexity inputs
- Encounter: 11
- Condition: 10
- Observation: 64
- MedicationRequest: 1
- MedicationAdministration: 0
- Procedure: 22
- DiagnosticReport: 25

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
