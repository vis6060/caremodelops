# ChartGround Milestone 5 local setup

Milestone 5 is a read-only Streamlit dashboard over the tenant-authenticated M2, M3, and M4 APIs. It does not read the SQLite database directly, change budget policies, create invoices, dispatch Claude requests, collect payments, or provide a cross-tenant administrator view.

## Install (PowerShell)

```powershell
conda activate chartground-claude
python -m pip install -r requirements-m5.txt
```

## Offline tests

```powershell
python -m pytest tests/test_platform_m5.py -v
python -m pytest -v
```

All dashboard analytics tests use temporary SQLite databases and fake local adapters. They do not make Claude or other external network calls.

## Start the M5-enabled API

The M5 API includes the existing M2-M4 routes and adds only two read-only, tenant-scoped analytics routes for run metadata and lifecycle events.

```powershell
conda activate chartground-claude
$env:PYTHONPATH = "$PWD\src"
python -m uvicorn chartground.platform_m5.api:create_app --factory --host 127.0.0.1 --port 8000
```

Starting this API adds the `m5_developer_lifecycle_events` table if needed. It does not backfill events or rewrite existing runs, usage, pricing, invoices, reservations, or evaluations.

## Start the dashboard in local demo mode

Open a second PowerShell window:

```powershell
conda activate chartground-claude
$env:CHARTGROUND_M5_DEMO = "1"
$env:CHARTGROUND_API_URL = "http://127.0.0.1:8000"
python -m streamlit run scripts/m5_dashboard.py
```

Demo mode offers OncoPilot and RadPath as separate tenant views. Their existing local credentials are read server-side from the ignored `results/m2_local/credentials.json` file for each request. Keys are not displayed, logged, cached, placed in URLs, or embedded in browser assets.

For a non-demo session, omit `CHARTGROUND_M5_DEMO`; the sidebar accepts one tenant API key in a masked field.

## Metric interpretation

- Requests, attempts, tokens, statuses, models, agents, and developer activity are measured from M2 records. Null token counts remain unknown and are not converted to zero.
- Upstream cost is an M3 estimate from measured per-attempt usage and the effective rate card. It is not an Anthropic invoice.
- Customer charges, partner payouts, invoices, and gross margin are fictional M3 commercial scenarios, not recognized revenue or financial reporting.
- M4 held spend may represent an active reservation, reconciled actual estimated cost, or a retained hold for unknown usage. The dashboard labels these states separately.
- Alerts and denials are local M4 control records. No email or external notification is sent.
- Existing runs are included in measured activity but are not converted into historical onboarding or activation events. Lifecycle instrumentation starts only for future requests served by the M5-enabled API.
- Activation is defined as the first successful API call. Retention and conversion metrics remain `Insufficient data` until genuine onboarding and enough elapsed activity periods exist.

The dashboard is intended for local evaluation. It does not include production deployment, unrestricted administration, payment processing, or budget-editing controls.
