# Milestone 2: local multi-tenant developer platform

Milestone 2 adds FastAPI and SQLAlchemy around the unchanged
scripts/developer_platform_demo.py. The adapter launches that script with the
server's Python interpreter, a fixed repository working directory, an argument
list (no shell), and a 180-second timeout. It does not implement another Claude
client. Only public cg-syn-NNN cases may be requested; the Milestone 1 source,
patient, path and citation checks remain in force. Supply synthetic-only questions.
No MIMIC sources, custom data paths or uploads are accepted.
Questions containing explicit MIMIC names, private-output paths, or common private
identifier labels are rejected before dispatch. This is a local guardrail, not a
general deidentification engine; use only synthetic ChartGround questions.

## PowerShell setup

Run from the ChartGround repository root:

```powershell
conda activate chartground-claude
python -m pip install -r requirements-m2.txt
python scripts/seed_m2.py
python -m uvicorn chartground.platform_m2.api:create_app --factory --app-dir src --host 127.0.0.1 --port 8000
```

In a second terminal, with the same environment and working directory:

```powershell
conda activate chartground-claude
python scripts/m2_demo.py
```

The demo makes mock-only local requests for both tenants, replays their idempotency
keys, and prints actions, attribution and reported totals. It never prints keys.
Stop the local server with Ctrl+C. No dashboard, pricing or billing is implemented.

## Fictional seed data

| Organization | Channel | Partner | Developer | Agent | Allowed cases |
| --- | --- | --- | --- | --- | --- |
| OncoPilot | direct | none | onco-dev | onco-agent | cg-syn-001, cg-syn-012 |
| RadPath | partner | MedData Partners | rad-dev | rad-agent | cg-syn-002, cg-syn-013 |

The seed creates separate random high-entropy API keys, saving them only in the
ignored results/m2_local/credentials.json. SQLite and credentials stay under that
ignored folder. The database stores SHA-256 key hashes, never the raw keys. Repeat
seeding preserves existing keys and grants; mismatched credentials fail without
rotation. Protect this local credentials file as a secret. Git ignore is not
encryption. Do not paste keys into prompts, query strings, logs or documentation.

## API contract

All /v1 endpoints require Authorization: Bearer with a tenant's local key.
/health is an unauthenticated readiness check. The API schema is at /docs.

- GET /v1/cases lists only the authenticated organization's granted cases.
- POST /v1/runs requires Idempotency-Key and a JSON body with case_id, question,
  agent_id, optional provider (default mock), and optional model.
- GET /v1/runs/{run_id} returns an owned run; foreign or unknown IDs return 404.
- GET /v1/usage returns owned request counts, reported token sums, unknown-token
  counts and an attempt ledger. limit (1-100) and offset paginate attempts; totals
  always cover the entire authenticated organization.

Organization, developer and partner attribution are resolved from the key and
database, never accepted from model output or caller-supplied attribution fields.
The selected agent must also belong to that organization. There is no partner-wide
endpoint and no global usage endpoint. Each run snapshots attribution.

Example request body (the local demo attaches credentials without displaying them):

```json
{
  "case_id": "cg-syn-012",
  "question": "What medication conflicts are present?",
  "agent_id": "onco-agent",
  "provider": "mock"
}
```

## Idempotency and consumption accounting

A unique (organization, idempotency key) database reservation is committed before
starting the subprocess. Identical replays return the saved response; a concurrent
pending replay returns 202. Reusing a key with changed input or developer identity
returns 409. Different organizations can independently use the same key string.
Run results and their attempt rows commit in a single transaction, preventing
replays from creating duplicate ledger entries.

The ledger imports only actual per-attempt fields emitted by Milestone 1: model,
request ID, timestamp, latency, stop reason, API/generation status, input/output
tokens, and cache creation/read tokens. Both a truncated first response and its
retry are recorded. Top-level Milestone 1 totals are not added again. Null counts
remain unknown, not zero. Summaries total reported values and explicitly count
unreported attempt fields. Mock runs produce no Claude consumption rows. Test
fixtures simulate usage and are never presented as measured Claude performance.

A timeout, crash or invalid subprocess result is marked indeterminate and is not
automatically retried. API consumption may already have occurred. A server crash
after reservation can leave pending rows; a crash between the API response and
database commit can leave unrecorded consumption. These require manual local
reconciliation against the existing private run logs before issuing a new key.
This prototype provides at-most-once dispatch per key, not transactional exactly-once
execution across a remote model API and the database. No scheduler retries requests.

## Explicit live opt-in

Live calls were not run for this milestone. Both conditions are required:

1. Start the server with CHARTGROUND_M2_ALLOW_CLAUDE=1 in its process environment.
2. Submit a request explicitly containing provider=claude.

Configure ANTHROPIC_API_KEY and ANTHROPIC_MODEL in the private root .env as in
Milestone 1. The subprocess loads them; keys never enter the API database or
responses. The API request's optional model overrides that configured model.
Restart with the live opt-in unset to disable Claude again. Do not enable live
mode for the offline demo/tests.

## PostgreSQL configuration

SQLite is the default. For an existing local PostgreSQL database, set its URL before
seeding and starting the server:

```powershell
$env:CHARTGROUND_M2_DATABASE_URL = "postgresql+psycopg://<user>:<password>@localhost:5432/chartground"
python scripts/seed_m2.py
python -m uvicorn chartground.platform_m2.api:create_app --factory --app-dir src --host 127.0.0.1 --port 8000
```

The same SQLAlchemy models and uniqueness constraints are used for both databases.
Tables are created if absent. PostgreSQL DDL is compiled in offline tests, but an
actual PostgreSQL server has not been integration-tested. Database creation,
migrations, key rotation/revocation UI, production deployment and quotas are beyond
this local milestone. Use a fresh database for this schema; create_all is not a
migration system. The server is intended for localhost, not public hosting.

## Offline validation

```powershell
conda activate chartground-claude
python -m pytest tests/test_platform_m2.py -v
python -m pytest -v
```

Tests exercise authentication, tenant isolation, case/agent permissions, attribution,
idempotent restart/replay and concurrent requests, failed execution, per-attempt
accounting, PostgreSQL schema compilation, and the real Milestone 1 subprocess in
mock mode. Simulated Claude results never invoke a paid API. Windows asyncio's
internal loopback sockets are permitted; external sockets are blocked in M2 tests.
