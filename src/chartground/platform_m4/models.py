"""Additive M4 policy, reservation, alert, and audit tables."""

from datetime import datetime, timezone

from sqlalchemy import Column, ForeignKey, Integer, JSON, String, UniqueConstraint

from chartground.platform_m2.database import Base


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class BudgetPolicy(Base):
    __tablename__ = "m4_budget_policies"
    __table_args__ = (UniqueConstraint("organization_id", "scope_type", "scope_id", "revision"),)
    id = Column(String(36), primary_key=True)
    organization_id = Column(String(80), ForeignKey("m2_organizations.id"), nullable=False, index=True)
    scope_type = Column(String(20), nullable=False)
    scope_id = Column(String(80), nullable=False)
    revision = Column(Integer, nullable=False)
    active = Column(Integer, nullable=False, default=1)
    monthly_spend_limit = Column(String(40), nullable=False)
    daily_request_limit = Column(Integer, nullable=False)
    monthly_request_limit = Column(Integer, nullable=False)
    assumed_input_tokens = Column(Integer, nullable=False)
    max_output_tokens = Column(Integer, nullable=False)
    max_attempts = Column(Integer, nullable=False)
    model_id = Column(String(120), nullable=False)
    created_by_developer_id = Column(String(80), ForeignKey("m2_developers.id"), nullable=True)
    created_at = Column(String(40), nullable=False, default=utc_now)


class SpendReservation(Base):
    __tablename__ = "m4_spend_reservations"
    id = Column(String(36), primary_key=True)
    run_id = Column(String(36), ForeignKey("m2_runs.id"), unique=True, nullable=False)
    organization_id = Column(String(80), ForeignKey("m2_organizations.id"), nullable=False, index=True)
    agent_id = Column(String(80), ForeignKey("m2_agents.id"), nullable=False, index=True)
    day_key = Column(String(10), nullable=False, index=True)
    month_key = Column(String(7), nullable=False, index=True)
    model_id = Column(String(120), nullable=False)
    rate_card_version = Column(String(120), nullable=False)
    reserved_cost = Column(String(40), nullable=False)
    held_cost = Column(String(40), nullable=False)
    actual_cost = Column(String(40), nullable=True)
    status = Column(String(24), nullable=False)
    preflight = Column(JSON, nullable=False)
    reconciliation = Column(JSON, nullable=True)
    created_at = Column(String(40), nullable=False, default=utc_now)
    reconciled_at = Column(String(40), nullable=True)


class SpendAlert(Base):
    __tablename__ = "m4_spend_alerts"
    __table_args__ = (UniqueConstraint("organization_id", "scope_type", "scope_id", "month_key", "threshold_percent"),)
    id = Column(Integer, primary_key=True)
    organization_id = Column(String(80), ForeignKey("m2_organizations.id"), nullable=False, index=True)
    scope_type = Column(String(20), nullable=False)
    scope_id = Column(String(80), nullable=False)
    month_key = Column(String(7), nullable=False)
    threshold_percent = Column(Integer, nullable=False)
    spend_at_trigger = Column(String(40), nullable=False)
    budget_limit = Column(String(40), nullable=False)
    created_at = Column(String(40), nullable=False, default=utc_now)


class SpendAudit(Base):
    __tablename__ = "m4_spend_audit"
    id = Column(Integer, primary_key=True)
    organization_id = Column(String(80), ForeignKey("m2_organizations.id"), nullable=False, index=True)
    agent_id = Column(String(80), nullable=True)
    run_id = Column(String(36), nullable=True)
    actor_developer_id = Column(String(80), nullable=True)
    event_type = Column(String(40), nullable=False)
    outcome = Column(String(24), nullable=False)
    details = Column(JSON, nullable=False)
    created_at = Column(String(40), nullable=False, default=utc_now)
