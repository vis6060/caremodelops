"""Additive M3 tables. Existing M2 rows and tables are never rewritten."""

from datetime import datetime, timezone

from sqlalchemy import Column, ForeignKey, Integer, JSON, String, UniqueConstraint, event

from chartground.platform_m2.database import Base


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class RateCard(Base):
    __tablename__ = "m3_rate_cards"
    id = Column(String(120), primary_key=True)
    provider = Column(String(40), nullable=False)
    model_id = Column(String(120), nullable=False, index=True)
    effective_from = Column(String(40), nullable=False)
    effective_to = Column(String(40), nullable=True)
    currency = Column(String(3), nullable=False)
    input_per_million = Column(String(40), nullable=False)
    output_per_million = Column(String(40), nullable=False)
    cache_write_5m_per_million = Column(String(40), nullable=False)
    cache_write_1h_per_million = Column(String(40), nullable=False)
    cache_read_per_million = Column(String(40), nullable=False)
    source_name = Column(String(160), nullable=False)
    source_url = Column(String(500), nullable=False)
    created_at = Column(String(40), nullable=False, default=utc_now)


class PricingPlan(Base):
    __tablename__ = "m3_pricing_plans"
    id = Column(String(100), primary_key=True)
    code = Column(String(40), nullable=False, index=True)
    effective_from = Column(String(40), nullable=False)
    effective_to = Column(String(40), nullable=True)
    currency = Column(String(3), nullable=False)
    usage_multiplier = Column(String(40), nullable=False)
    successful_response_fee = Column(String(40), nullable=False)
    minimum_commitment = Column(String(40), nullable=False)
    description = Column(String(500), nullable=False)
    illustrative = Column(Integer, nullable=False, default=1)
    created_at = Column(String(40), nullable=False, default=utc_now)


class OrganizationPlan(Base):
    __tablename__ = "m3_organization_plans"
    organization_id = Column(String(80), ForeignKey("m2_organizations.id"), primary_key=True)
    effective_from = Column(String(40), primary_key=True)
    effective_to = Column(String(40), nullable=True)
    pricing_plan_id = Column(String(100), ForeignKey(PricingPlan.id), nullable=False)
    created_at = Column(String(40), nullable=False, default=utc_now)


class PartnerTerms(Base):
    __tablename__ = "m3_partner_terms"
    id = Column(String(100), primary_key=True)
    partner_id = Column(String(80), ForeignKey("m2_partners.id"), nullable=False, index=True)
    effective_from = Column(String(40), nullable=False)
    effective_to = Column(String(40), nullable=True)
    revenue_share_rate = Column(String(40), nullable=False)
    description = Column(String(500), nullable=False)
    illustrative = Column(Integer, nullable=False, default=1)
    created_at = Column(String(40), nullable=False, default=utc_now)


class Invoice(Base):
    __tablename__ = "m3_invoices"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key"),
        UniqueConstraint("organization_id", "billing_key"),
    )
    id = Column(String(36), primary_key=True)
    organization_id = Column(String(80), ForeignKey("m2_organizations.id"), nullable=False, index=True)
    invoice_type = Column(String(20), nullable=False)
    reporting_period_start = Column(String(40), nullable=False)
    reporting_period_end = Column(String(40), nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    billing_key = Column(String(300), nullable=False)
    correction_of_invoice_id = Column(String(36), ForeignKey("m3_invoices.id"), nullable=True)
    status = Column(String(24), nullable=False)
    currency = Column(String(3), nullable=False)
    pricing_plan_version = Column(String(100), nullable=False)
    partner_terms_version = Column(String(100), nullable=True)
    estimated_upstream_cost = Column(String(40), nullable=True)
    customer_charge = Column(String(40), nullable=True)
    partner_payout = Column(String(40), nullable=True)
    gross_margin = Column(String(40), nullable=True)
    pricing_snapshot = Column(JSON, nullable=False)
    created_at = Column(String(40), nullable=False, default=utc_now)


class InvoiceLine(Base):
    __tablename__ = "m3_invoice_lines"
    __table_args__ = (UniqueConstraint("invoice_id", "line_key"),)
    id = Column(Integer, primary_key=True)
    invoice_id = Column(String(36), ForeignKey(Invoice.id), nullable=False, index=True)
    line_key = Column(String(180), nullable=False)
    line_type = Column(String(30), nullable=False)
    run_id = Column(String(36), nullable=True)
    attempt_id = Column(Integer, nullable=True)
    description = Column(String(500), nullable=False)
    upstream_cost = Column(String(40), nullable=True)
    customer_charge = Column(String(40), nullable=True)
    waived = Column(Integer, nullable=False, default=0)
    rate_card_version = Column(String(120), nullable=True)
    pricing_plan_version = Column(String(100), nullable=False)
    details = Column(JSON, nullable=False)


def _immutable(_mapper, _connection, target):
    raise ValueError(f"{type(target).__name__} records are immutable; add a new version.")


for immutable_model in (RateCard, PricingPlan, OrganizationPlan, PartnerTerms):
    event.listen(immutable_model, "before_update", _immutable)
    event.listen(immutable_model, "before_delete", _immutable)
