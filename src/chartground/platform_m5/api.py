"""M4 platform plus minimal tenant-scoped analytics read APIs."""

import hashlib
from datetime import datetime

from fastapi import Depends, Query
from fastapi.exceptions import HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from chartground.platform_m2.database import Developer, Organization, Run
from chartground.platform_m4.api import create_app as create_m4_app

from .lifecycle import DeveloperLifecycleService, LifecycleObserverProxy
from .models import DeveloperLifecycleEvent  # noqa: F401 - register table before app initialization


def create_app(database_url=None, adapter=None, allow_claude=None, seed_defaults=True):
    observer = LifecycleObserverProxy()
    app = create_m4_app(database_url=database_url, adapter=adapter, allow_claude=allow_claude,
                        seed_defaults=seed_defaults, analytics_observer=observer)
    app.title = "ChartGround local developer analytics platform"
    app.version = "5.0"
    sessions = app.state.sessions
    lifecycle = DeveloperLifecycleService()
    observer.target = lifecycle
    app.state.lifecycle = lifecycle
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

    @app.get("/v1/analytics/runs")
    def runs(start: datetime | None = None, end: datetime | None = None,
             limit: int = Query(500, ge=1, le=2000), offset: int = Query(0, ge=0),
             who=Depends(identity)):
        with sessions() as session:
            rows = list(session.scalars(select(Run).where(
                Run.organization_id == who[0]
            ).order_by(Run.created_at, Run.id)))
            if start is not None:
                rows = [row for row in rows if datetime.fromisoformat(row.created_at.replace("Z", "+00:00")) >= start]
            if end is not None:
                rows = [row for row in rows if datetime.fromisoformat(row.created_at.replace("Z", "+00:00")) < end]
            total = len(rows)
            rows = rows[offset:offset + limit]
            return {"organization_id": who[0], "total": total, "limit": limit, "offset": offset,
                    "runs": [{"run_id": row.id, "developer_id": row.developer_id,
                              "agent_id": row.agent_id, "partner_id": row.partner_id,
                              "case_id": row.case_id, "provider": row.provider,
                              "status": row.status, "action": (row.response or {}).get("action"),
                              "created_at": row.created_at} for row in rows]}

    @app.get("/v1/analytics/lifecycle-events")
    def lifecycle_events(limit: int = Query(500, ge=1, le=2000), offset: int = Query(0, ge=0),
                         who=Depends(identity)):
        with sessions() as session:
            rows = lifecycle.events(session, who[0])
            total = len(rows)
            rows = rows[offset:offset + limit]
            return {"organization_id": who[0], "total": total, "limit": limit, "offset": offset,
                    "events": [{"event_id": row.id, "developer_id": row.developer_id,
                                "agent_id": row.agent_id, "run_id": row.run_id,
                                "event_type": row.event_type, "occurred_at": row.occurred_at,
                                "properties": row.properties} for row in rows]}

    return app
