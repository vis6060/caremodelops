# cg-syn-017

Patient: Jenae263 Steven797 Barrows492 (cd17df2b-671c-6ab1-f395-20e321538380)

Source bundle: Jenae263_Barrows492_cd17df2b-671c-6ab1-f395-20e321538380.json

Complexity score: 1862

## Complexity inputs
- Encounter: 167
- Condition: 36
- Observation: 995
- MedicationRequest: 79
- MedicationAdministration: 29
- Procedure: 233
- DiagnosticReport: 317
- CarePlan: 6

## Generated artifacts
- encounters.jsonl: 167
- events.jsonl: 1876
- evidence.jsonl: 1877
- notes.jsonl: 4
- provenance.jsonl: 12
- tasks.jsonl: 4
- overlays.json: 1

## Overlay policy
Overlay count: 1

Overlays are present only when the source bundle lacks imaging-like evidence for the required radiology note.
