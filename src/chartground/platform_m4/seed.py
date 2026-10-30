"""Conservative local defaults for the two fictional M2 tenants."""

from uuid import uuid4

from sqlalchemy import select

from .models import BudgetPolicy

DEFAULTS = (
    ("oncopilot", "organization", "oncopilot", "100.00", 100, 1000),
    ("oncopilot", "agent", "onco-agent", "50.00", 50, 500),
    ("radpath", "organization", "radpath", "100.00", 100, 1000),
    ("radpath", "agent", "rad-agent", "50.00", 50, 500),
)


def seed(sessions):
    with sessions.begin() as session:
        for organization_id, scope_type, scope_id, spend, daily, monthly in DEFAULTS:
            exists = session.scalar(select(BudgetPolicy).where(
                BudgetPolicy.organization_id == organization_id,
                BudgetPolicy.scope_type == scope_type,
                BudgetPolicy.scope_id == scope_id,
                BudgetPolicy.active == 1,
            ))
            if exists is None:
                session.add(BudgetPolicy(
                    id=str(uuid4()), organization_id=organization_id, scope_type=scope_type,
                    scope_id=scope_id, revision=1, active=1, monthly_spend_limit=spend,
                    daily_request_limit=daily, monthly_request_limit=monthly,
                    assumed_input_tokens=8000, max_output_tokens=4096, max_attempts=2,
                    model_id="claude-sonnet-5-5", created_by_developer_id=None,
                ))
