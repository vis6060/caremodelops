# ChartGround Milestone 4 local setup

Milestone 4 adds organization and agent spending budgets, request quotas, atomic preflight reservations, actual usage reconciliation, local threshold alerts, and tenant-scoped audit records. It does not process payments, send email, or change the M3 invoice model.

## Install and test (PowerShell)

```powershell
conda activate chartground-claude
python -m pip install -r requirements-m4.txt
python -m pytest tests/test_platform_m4.py -v
python -m pytest -v
```

## Offline demo

The demo creates a temporary SQLite database and uses an in-process fake adapter. It shows one approved reservation, 50/80/100 percent local alerts, a hard budget rejection before dispatch, and an idempotent replay. It makes no Claude request and does not modify `results/m2_local/platform.sqlite3`.

```powershell
python scripts/m4_demo.py
```

## Run the local M4 API

The M4 app reuses the existing database URL and creates only additive `m4_*` tables.

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m uvicorn chartground.platform_m4.api:create_app --factory --host 127.0.0.1 --port 8000
```

Live Claude execution remains disabled unless it is explicitly enabled through the existing M2 setting. No live call is needed for setup or testing.

## Control behavior

- Both an active organization policy and an active agent policy are required. The more conservative input, output, and retry assumptions are used for preflight.
- The preflight hold uses the effective M3 model rate card, assumes no cache use, and prices every permitted attempt using bounded input tokens and maximum output tokens.
- SQLite obtains a write reservation before reading budget and quota state. PostgreSQL uses row locks on active policies. Concurrent requests therefore cannot both consume the same remaining budget.
- Requests are allowed when the estimated hold exactly equals the remaining budget and rejected when it exceeds it.
- A rejected request is recorded in the M2 run ledger with status `rejected`, but no subprocess is started and no spend reservation is created.
- Known per-attempt costs replace the preflight hold, including costs from failed or truncated attempts. Missing or unpriceable usage is marked `unreconciled` and retains the full hold.
- Request quotas count dispatched reservations once. Idempotent replays do not add requests, reservations, or costs.
- Alerts are stored at 50%, 80%, and 100% of monthly held spend. They are historical local records and are not emailed.
- Budget changes create new policy revisions and append audit records. Approval, denial, reservation, and reconciliation decisions are also audited.
- Existing M2 runs, M3 rate cards, invoices, API-key hashes, and clinical evaluation outputs are not migrated or rewritten.

PostgreSQL schema generation is covered by offline tests. A real PostgreSQL deployment and migration should be verified separately.
