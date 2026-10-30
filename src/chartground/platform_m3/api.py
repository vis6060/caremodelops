"""M2-compatible FastAPI app with tenant-scoped simulated monetization routes."""

import hashlib
from datetime import datetime
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from chartground.platform_m2.api import create_app as create_m2_app
from chartground.platform_m2.database import Developer, Organization

from .models import PartnerTerms  # noqa: F401 - register M3 tables before M2 initializes metadata
from .seed import seed
from .service import MonetizationService


class PeriodInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reporting_period_start: datetime
    reporting_period_end: datetime


class AdjustmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: str = Field(pattern=r"^-?\d+(?:\.\d{1,8})?$")
    reason: str = Field(min_length=3, max_length=500)


def create_app(database_url=None, adapter=None, allow_claude=None, seed_defaults=True, run_lifecycle=None):
    app = create_m2_app(database_url=database_url, adapter=adapter, allow_claude=allow_claude,
                        run_lifecycle=run_lifecycle)
    app.title = "ChartGround local developer platform with simulated monetization"
    app.version = "3.0"
    sessions = app.state.sessions
    if seed_defaults:
        with sessions() as session:
            ready = session.get(Organization, "oncopilot") is not None and session.get(Organization, "radpath") is not None
        if ready:
            seed(sessions)
    service = MonetizationService(sessions)
    app.state.monetization = service
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
            return organization.id, developer.id, organization.partner_id

    def estimate_for(who, start, end):
        try:
            return service.estimate(who[0], start, end)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @app.get("/v1/pricing/estimate")
    def pricing_estimate(reporting_period_start: datetime, reporting_period_end: datetime, who=Depends(identity)):
        return estimate_for(who, reporting_period_start, reporting_period_end)

    @app.post("/v1/invoices")
    def create_invoice(body: PeriodInput, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)], who=Depends(identity)):
        try:
            return service.create_invoice(who[0], body.reporting_period_start, body.reporting_period_end, idempotency_key)
        except ValueError as error:
            raise HTTPException(409 if "Idempotency" in str(error) else 422, str(error)) from error

    @app.get("/v1/invoices")
    def list_invoices(who=Depends(identity)):
        return {"organization_id": who[0], "invoices": service.list_invoices(who[0])}

    @app.get("/v1/invoices/{invoice_id}")
    def get_invoice(invoice_id: str, who=Depends(identity)):
        invoice = service.get_invoice(who[0], invoice_id)
        if invoice is None:
            raise HTTPException(404, "Invoice not found.")
        return invoice

    @app.post("/v1/invoices/{invoice_id}/adjustments")
    def create_adjustment(invoice_id: str, body: AdjustmentInput,
                          idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
                          who=Depends(identity)):
        try:
            return service.create_adjustment(who[0], invoice_id, body.amount, body.reason, idempotency_key)
        except LookupError as error:
            raise HTTPException(404, str(error)) from error
        except ValueError as error:
            raise HTTPException(409 if "Idempotency" in str(error) else 422, str(error)) from error

    @app.get("/v1/invoices/{invoice_id}/reconciliation")
    def reconciliation(invoice_id: str, who=Depends(identity)):
        result = service.reconcile(who[0], invoice_id)
        if result is None:
            raise HTTPException(404, "Invoice not found.")
        return result

    @app.get("/v1/partner-attribution")
    def partner_attribution(reporting_period_start: datetime, reporting_period_end: datetime, who=Depends(identity)):
        estimate = estimate_for(who, reporting_period_start, reporting_period_end)
        return {
            "organization_id": who[0], "channel": estimate["channel"], "partner_id": estimate["partner_id"],
            "partner_terms_version": estimate["partner_terms_version"],
            "illustrative_customer_charge": estimate["illustrative_customer_charge"],
            "simulated_partner_payout": estimate["simulated_partner_payout"],
            "access_scope": "Authenticated organization only; this is not a partner-wide endpoint.",
        }

    @app.get("/v1/unit-economics")
    def unit_economics(reporting_period_start: datetime, reporting_period_end: datetime, who=Depends(identity)):
        estimate = estimate_for(who, reporting_period_start, reporting_period_end)
        return {
            "organization_id": who[0], "estimated_upstream_cost": estimate["estimated_upstream_cost"],
            "known_upstream_cost_subtotal": estimate["known_upstream_cost_subtotal"],
            "unknown_upstream_attempts": estimate["unknown_upstream_attempts"],
            "illustrative_customer_charge": estimate["illustrative_customer_charge"],
            "simulated_partner_payout": estimate["simulated_partner_payout"],
            "simulated_gross_margin": estimate["simulated_gross_margin"],
            "pricing_plan_version": estimate["pricing_plan_version"],
        }

    return app
