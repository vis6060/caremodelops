"""Authenticated, tenant-scoped runs and observed Claude consumption."""

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .adapter import SubprocessAdapter, TOKEN_FIELDS, validate_result
from .database import Agent, Attempt, CaseGrant, Developer, Organization, Run, database


RESTRICTED_INPUT = re.compile(
    r"\b(?:mimic(?:-iv|-iv-note)?|subject_id|hadm_id|stay_id|note_id)\b|"
    r"MIMICdata|results[/\\]mimic_private",
    re.IGNORECASE,
)


def key_digest(key):
    return hashlib.sha256(key.encode()).hexdigest()


class RunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str = Field(pattern=r"^cg-syn-\d{3}$")
    question: str = Field(min_length=1, max_length=2000)
    agent_id: str = Field(min_length=1, max_length=80)
    provider: Literal["mock", "claude"] = "mock"
    model: str | None = Field(default=None, max_length=120)


def envelope(run):
    return dict(run_id=run.id, organization_id=run.organization_id, developer_id=run.developer_id,
                agent_id=run.agent_id, partner_id=run.partner_id, case_id=run.case_id,
                provider=run.provider, status=run.status, created_at=run.created_at, result=run.response)


def create_app(database_url=None, adapter=None, allow_claude=None, run_lifecycle=None):
    engine, sessions = database(database_url)
    app = FastAPI(title="ChartGround local developer platform", version="2.0")
    app.state.engine, app.state.sessions = engine, sessions
    execute = adapter or SubprocessAdapter()
    live_enabled = os.getenv("CHARTGROUND_M2_ALLOW_CLAUDE") == "1" if allow_claude is None else allow_claude
    bearer = HTTPBearer(auto_error=False)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        # FastAPI's default error body echoes input; avoid echoing submitted secrets.
        return JSONResponse(status_code=422, content={"detail": "Invalid request fields."})

    def identity(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(401, "API key required.")
        with sessions() as session:
            developer = session.scalar(select(Developer).where(Developer.key_hash == key_digest(credentials.credentials)))
            if developer is None:
                raise HTTPException(401, "Invalid API key.")
            org = session.get(Organization, developer.organization_id)
            return org.id, developer.id, org.partner_id, credentials.credentials

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/v1/cases")
    def cases(who=Depends(identity)):
        with sessions() as session:
            return {"organization_id": who[0], "case_ids": list(session.scalars(
                select(CaseGrant.case_id).where(CaseGrant.organization_id == who[0]).order_by(CaseGrant.case_id)))}

    @app.post("/v1/runs")
    def run(body: RunInput, idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128), who=Depends(identity)):
        data = body.model_dump()
        if who[3] in json.dumps(data) or who[3] in idempotency_key:
            raise HTTPException(422, "Credentials must not be included in request data.")
        if not body.question.strip():
            raise HTTPException(422, "Question is empty.")
        if RESTRICTED_INPUT.search(body.question):
            raise HTTPException(422, "Restricted-data markers are not permitted.")
        if body.provider == "claude" and not live_enabled:
            raise HTTPException(403, "Live execution is disabled on this server.")
        # Bind developer identity too: a tenant's other key cannot reuse a request to
        # impersonate its original developer or change attribution.
        fingerprint = key_digest(json.dumps({**data, "developer_id": who[1]}, sort_keys=True))
        with sessions() as session:
            agent = session.get(Agent, body.agent_id)
            if agent is None or agent.organization_id != who[0]:
                raise HTTPException(403, "Agent is not permitted.")
            if session.get(CaseGrant, (who[0], body.case_id)) is None:
                raise HTTPException(403, "Case is not permitted.")
            record = Run(id=str(uuid4()), organization_id=who[0], developer_id=who[1],
                         partner_id=who[2], agent_id=body.agent_id, idempotency_key=idempotency_key,
                         fingerprint=fingerprint, case_id=body.case_id, provider=body.provider,
                         status="pending", created_at=datetime.now(timezone.utc).isoformat())
            session.add(record)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                prior = session.scalar(select(Run).where(Run.organization_id == who[0], Run.idempotency_key == idempotency_key))
                if prior is None:
                    raise HTTPException(409, "Request could not be reserved.")
                if prior.fingerprint != fingerprint:
                    raise HTTPException(409, "Idempotency key already used for a different request.")
                replay_status = 202 if prior.status == "pending" else (429 if prior.status == "rejected" else 200)
                return JSONResponse(status_code=replay_status, content=envelope(prior))
            run_id = record.id
        if run_lifecycle is not None:
            decision = run_lifecycle.reserve(record, data)
            if not decision["approved"]:
                with sessions.begin() as session:
                    record = session.get(Run, run_id)
                    record.status = "rejected"
                    record.response = {"error": "Request rejected before execution.", "spending_control": decision}
                    response = envelope(record)
                return JSONResponse(status_code=429, content=response)
        # Reservation is durable before any subprocess can consume paid tokens.
        try:
            result = validate_result(execute(data), data)
            result = json.loads(json.dumps(result).replace(who[3], "[REDACTED]"))
        except Exception:
            with sessions.begin() as session:
                record = session.get(Run, run_id)
                record.status = "indeterminate"
                record.response = {"error": "Execution result unavailable; usage may be unknown. Do not automatically retry."}
                if run_lifecycle is not None:
                    run_lifecycle.mark_unreconciled(session, record, "Execution result unavailable; reserved spend retained.")
                return JSONResponse(status_code=502, content=envelope(record))
        with sessions.begin() as session:
            record = session.get(Run, run_id)
            record.status, record.response = result["status"], result
            attempts = []
            for attempt in result["usage"]["attempts"]:
                row = Attempt(run_id=run_id, number=attempt["attempt"], details=attempt,
                              **{field: attempt[field] for field in TOKEN_FIELDS})
                session.add(row)
                attempts.append(row)
            session.flush()
            if run_lifecycle is not None:
                run_lifecycle.reconcile(session, record, attempts)
            response = envelope(record)
        return response

    @app.get("/v1/runs/{run_id}")
    def get_run(run_id: str, who=Depends(identity)):
        with sessions() as session:
            record = session.scalar(select(Run).where(Run.id == run_id, Run.organization_id == who[0]))
            if record is None:
                raise HTTPException(404, "Run not found.")
            return envelope(record)

    @app.get("/v1/usage")
    def usage(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), who=Depends(identity)):
        with sessions() as session:
            scope = Run.organization_id == who[0]
            sums = session.execute(select(*(func.sum(getattr(Attempt, f)) for f in TOKEN_FIELDS)).join(Run, Attempt.run_id == Run.id).where(scope)).one()
            rows = session.execute(select(Attempt, Run).join(Run, Attempt.run_id == Run.id).where(scope).order_by(Run.created_at, Run.id, Attempt.number).offset(offset).limit(limit)).all()
            count = session.scalar(select(func.count()).select_from(Run).where(scope))
            attempt_count = session.scalar(select(func.count()).select_from(Attempt).join(Run, Attempt.run_id == Run.id).where(scope))
            known_counts = session.execute(select(*(func.count(getattr(Attempt, f)) for f in TOKEN_FIELDS)).join(Run, Attempt.run_id == Run.id).where(scope)).one()
            unresolved = session.scalar(select(func.count()).select_from(Run).where(scope, Run.status.in_(["pending", "indeterminate"])))
            attempts = []
            for attempt, record in rows:
                attempts.append({"run_id": record.id, "organization_id": record.organization_id,
                                 "developer_id": record.developer_id, "agent_id": record.agent_id,
                                 "partner_id": record.partner_id, **attempt.details})
            return {"organization_id": who[0], "request_count": count, "unresolved_requests": unresolved,
                    "attempt_count": attempt_count,
                    "unreported_attempt_counts": {f: attempt_count - n for f, n in zip(TOKEN_FIELDS, known_counts)},
                    "reported_token_totals": dict(zip(TOKEN_FIELDS, sums)),
                    "attempts": attempts, "limit": limit, "offset": offset,
                    "accounting_note": "Reported consumption only; null means unavailable. No pricing or billing."}

    return app
