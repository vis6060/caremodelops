# ChartGround Milestone 3 local setup

Milestone 3 adds simulated pricing and invoices to the existing M2 platform. It never processes payments and its customer charges, commitments, partner shares, and margins are illustrative. Estimated upstream cost uses recorded per-attempt Anthropic token counts and a versioned rate-card snapshot.

## Setup and tests (PowerShell)

```powershell
conda activate chartground-claude
python -m pip install -r requirements-m3.txt
python -m pytest -v
```

The default database remains `results/m2_local/platform.sqlite3`. Starting the M3 app adds only `m3_*` tables; it does not recreate or alter M2 rows.

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m uvicorn chartground.platform_m3.api:create_app --factory --host 127.0.0.1 --port 8000
```

## Read-only M2 validation

This command opens SQLite with `mode=ro`, validates credential-to-tenant mappings, persisted run IDs, usage attempts, and cross-tenant isolation, and never displays API keys.

```powershell
python scripts/validate_m2_readonly.py
```

## Offline monetization demo

The demo reads existing M2 runs and attempts, creates idempotent simulated invoices for OncoPilot and RadPath, and makes no Claude request.

```powershell
python scripts/m3_demo.py
```

Running the demo again returns the same invoice for each organization and reporting period. OncoPilot uses the illustrative pay-as-you-go plan. RadPath uses the illustrative committed-use plan and attributes a simulated revenue share to MedData Partners.

## Pricing and accounting assumptions

- The seeded `claude-sonnet-5-5` rate card is effective 2026-09-28 and records Anthropic's documented USD per-million-token rates: input $2, output $10, 5-minute cache write $2.50, 1-hour cache write $4, and cache read $0.10. Source: <https://platform.claude.com/docs/en/models/sonnet-5-5/overview>.
- Rate cards, plans, organization assignments, and partner terms are immutable. Price changes are added as new effective-dated versions. Unknown models or uncovered dates remain unpriced.
- A null token count remains unknown. A nonzero aggregate cache-write count also remains unpriced unless its 5-minute/1-hour TTL or token breakdown is recorded.
- Every M2 attempt, including a retry, failed attempt, or truncated attempt, contributes upstream cost exactly once. Top-level usage totals are not priced.
- Customer usage and response fees are waived when the M2 run status is not `success`; any known upstream cost remains in unit economics.
- Pay-as-you-go is simulated as 1.5 times estimated upstream usage plus $0.05 per successful response. Committed use is simulated as 1.2 times usage with a $25 minimum per reporting period.
- MedData Partners receives a simulated 20% of RadPath customer charges. OncoPilot is attributed directly and has no partner payout.
- Standard invoices are unique per organization and reporting period. Corrections are separate adjustment invoices linked to the original, preserving its pricing snapshot.
- PostgreSQL schema generation is covered offline. Deployment and migration operations should be verified separately before using PostgreSQL.
