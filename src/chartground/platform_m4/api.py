"""M3-compatible API with tenant-scoped enterprise spending controls."""

import hashlib
from datetime import datetime

from fastapi import Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from chartground.platform_m2.database import Agent, Developer, Organization
from chartground.platform_m3.api import create_app as create_m3_app
from chartground.platform_m3.costing import decimal_value

from .control import LifecycleProxy, SpendingController
from .models import BudgetPolicy  # noqa: F401 - register M4 tables before app initialization
from .seed import seed


class PolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    monthly_spend_limit: str = Field(pattern=r"^\d+(?:\.\d{1,8})?$")
    daily_request_limit: int = Field(ge=1, le=1_000_000)
    monthly_request_limit: int = Field(ge=1, le=10_000_000)
    assumed_input_tokens: int = Field(ge=1, le=1_000_000)
    max_output_tokens: int = Field(ge=256, le=8192)
    max_attempts: int = Field(ge=1, le=2)
    model_id: str = Field(min_length=1, max_length=120)


class PreflightInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str = Field(min_length=1, max_length=80)
    model: str | None = Field(default=None, max_length=120)


def create_app(database_url=None, adapter=None, allow_claude=None, seed_defaults=True,
               analytics_observer=None):
    lifecycle = LifecycleProxy()
    app = create_m3_app(database_url=database_url, adapter=adapter, allow_claude=allow_claude,
                        seed_defaults=seed_defaults, run_lifecycle=lifecycle)
    app.title = "ChartGround local developer platform with enterprise spending controls"
    app.version = "4.0"
    sessions, engine = app.state.sessions, app.state.engine
    if seed_defaults:
        with sessions() as session:
            ready = session.get(Organization, "oncopilot") is not None and session.get(Organization, "radpath") is not None
        if ready:
            seed(sessions)
    controller = SpendingController(sessions, engine, analytics_observer=analytics_observer)
    lifecycle.target = controller
    app.state.spending = controller
    bearer = HTTPBearer(auto_error=False)

    def identity(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(401, "API key required.")
        digest = hashlib.sha256(credentials.credentials.encode()).hexdigest()
        with sessions() as session:
            developer = session.scalar(select(Developer).where(Developer.key_hash == digest))
            if developer is None:
                raise HTTPException(401, "Invalid API key.")
            organization = session.get(Organization, developer.organization_id)
            return organization.id, developer.id

    def values(body):
        data = body.model_dump()
        if decimal_value(data["monthly_spend_limit"]) <= 0:
            raise HTTPException(422, "Monthly spend limit must be positive.")
        if data["monthly_request_limit"] < data["daily_request_limit"]:
            raise HTTPException(422, "Monthly request limit must not be below the daily limit.")
        return data

    @app.get("/v1/spending-controls/policies")
    def policies(who=Depends(identity)):
        return {"organization_id": who[0], "policies": controller.policies(who[0])}

    @app.put("/v1/spending-controls/organization")
    def set_organization_policy(body: PolicyInput, who=Depends(identity)):
        return controller.set_policy(who[0], "organization", who[0], values(body), who[1])

    @app.put("/v1/spending-controls/agents/{agent_id}")
    def set_agent_policy(agent_id: str, body: PolicyInput, who=Depends(identity)):
        try:
            return controller.set_policy(who[0], "agent", agent_id, values(body), who[1])
        except LookupError as error:
            raise HTTPException(404, str(error)) from error

    @app.post("/v1/spending-controls/preflight")
    def preflight(body: PreflightInput, who=Depends(identity)):
        with sessions() as session:
            agent = session.get(Agent, body.agent_id)
            if agent is None or agent.organization_id != who[0]:
                raise HTTPException(404, "Agent not found.")
        return controller.preflight(who[0], body.agent_id, body.model)

    @app.get("/v1/spending-controls/status")
    def organization_status(who=Depends(identity)):
        return controller.status(who[0])

    @app.get("/v1/spending-controls/agents/{agent_id}/status")
    def agent_status(agent_id: str, who=Depends(identity)):
        with sessions() as session:
            agent = session.get(Agent, agent_id)
            if agent is None or agent.organization_id != who[0]:
                raise HTTPException(404, "Agent not found.")
        return controller.status(who[0], agent_id)

    @app.get("/v1/spending-controls/reservations")
    def reservations(who=Depends(identity)):
        return {"organization_id": who[0], "reservations": controller.reservations(who[0])}

    @app.get("/v1/spending-controls/alerts")
    def alerts(who=Depends(identity)):
        return {"organization_id": who[0], "alerts": controller.alerts(who[0]),
                "delivery": "Stored locally; no email or external notification was sent."}

    @app.get("/v1/spending-controls/audit")
    def audit(limit: int = Query(100, ge=1, le=500), who=Depends(identity)):
        return {"organization_id": who[0], "audit": controller.audit(who[0], limit)}

    return app
