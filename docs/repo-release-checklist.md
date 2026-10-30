# Repository Release Checklist

## Privacy And Data

- `.gitignore` checked.
- Restricted raw-data folder is ignored.
- Private stress-test outputs are ignored.
- Local database files are ignored.
- No raw notes in public docs.
- No private patient identifiers in public docs.
- No private local paths in public docs.
- No patient-level private outputs in public docs.
- Public synthetic data only in committed case artifacts.

## Documentation

- README complete.
- Product brief complete.
- Architecture document complete.
- Evaluation summary complete.
- Clinician-review plan complete.
- Safety and privacy document complete.
- Demo script complete.
- Resume and interview materials complete.

## Validation

- Tests pass.
- Public evaluation is reproducible.
- Clinician-review package generated.
- Privacy scanner passed on public docs and public-safe summaries.
- Large generated artifacts reviewed before commit.

## Release Boundary

Public repository content may include source code, synthetic cases, public evaluation summaries, and aggregate-only private stress-test metrics. It must not include restricted raw data, private generated cases, private row-level outputs, raw note text, private identifiers, or local private paths.
