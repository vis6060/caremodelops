# cg-syn-006

Patient: Son314 Dorian295 Dooley940 (bb598416-7bda-c1db-1069-1774083ea954)

Source bundle: Son314_Dooley940_bb598416-7bda-c1db-1069-1774083ea954.json

Complexity score: 21961

## Complexity inputs
- Encounter: 472
- Condition: 491
- Observation: 15133
- MedicationRequest: 1999
- MedicationAdministration: 176
- Procedure: 1636
- DiagnosticReport: 2054

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
