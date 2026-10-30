"""Minimal forward-looking developer lifecycle instrumentation."""

from sqlalchemy import Column, ForeignKey, Integer, JSON, String

from chartground.platform_m2.database import Base
from chartground.platform_m4.models import utc_now


class DeveloperLifecycleEvent(Base):
    __tablename__ = "m5_developer_lifecycle_events"
    id = Column(Integer, primary_key=True)
    event_key = Column(String(180), unique=True, nullable=False)
    organization_id = Column(String(80), ForeignKey("m2_organizations.id"), nullable=False, index=True)
    developer_id = Column(String(80), ForeignKey("m2_developers.id"), nullable=False, index=True)
    agent_id = Column(String(80), nullable=True)
    run_id = Column(String(36), ForeignKey("m2_runs.id"), nullable=True)
    event_type = Column(String(50), nullable=False, index=True)
    occurred_at = Column(String(40), nullable=False, default=utc_now)
    properties = Column(JSON, nullable=False)
