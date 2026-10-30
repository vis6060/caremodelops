"""Documented, versioned defaults for the fictional M3 commercial model."""

from .models import OrganizationPlan, PartnerTerms, PricingPlan, RateCard

ANTHROPIC_PRICING_URL = "https://platform.claude.com/docs/en/models/sonnet-5-5/overview"

DEFAULT_RATE_CARDS = (
    dict(
        id="anthropic-claude-sonnet-5-5-2026-09-28",
        provider="anthropic",
        model_id="claude-sonnet-5-5",
        effective_from="2026-09-28T00:00:00+00:00",
        effective_to=None,
        currency="USD",
        input_per_million="2.00",
        output_per_million="10.00",
        cache_write_5m_per_million="2.50",
        cache_write_1h_per_million="4.00",
        cache_read_per_million="0.10",
        source_name="Anthropic Claude Sonnet 5.5 model documentation",
        source_url=ANTHROPIC_PRICING_URL,
    ),
)

DEFAULT_PLANS = (
    dict(
        id="illustrative-payg-2026-10-01",
        code="pay_as_you_go",
        effective_from="2026-10-01T00:00:00+00:00",
        effective_to=None,
        currency="USD",
        usage_multiplier="1.50",
        successful_response_fee="0.05",
        minimum_commitment="0.00",
        description="Illustrative customer charge: 1.5x estimated upstream usage plus $0.05 per successful response.",
    ),
    dict(
        id="illustrative-committed-2026-10-01",
        code="committed_use",
        effective_from="2026-10-01T00:00:00+00:00",
        effective_to=None,
        currency="USD",
        usage_multiplier="1.20",
        successful_response_fee="0.00",
        minimum_commitment="25.00",
        description="Illustrative customer charge: 1.2x estimated upstream usage with a $25 minimum per reporting period.",
    ),
)

DEFAULT_ORG_PLANS = (
    dict(organization_id="oncopilot", effective_from="2026-10-01T00:00:00+00:00", effective_to=None,
         pricing_plan_id="illustrative-payg-2026-10-01"),
    dict(organization_id="radpath", effective_from="2026-10-01T00:00:00+00:00", effective_to=None,
         pricing_plan_id="illustrative-committed-2026-10-01"),
)

DEFAULT_PARTNER_TERMS = (
    dict(
        id="meddata-partners-illustrative-2026-10-01",
        partner_id="meddata-partners",
        effective_from="2026-10-01T00:00:00+00:00",
        effective_to=None,
        revenue_share_rate="0.20",
        description="Illustrative 20% share of simulated RadPath customer charges; not a real contract or payout.",
    ),
)


def seed(sessions, rate_cards=DEFAULT_RATE_CARDS, plans=DEFAULT_PLANS,
         organization_plans=DEFAULT_ORG_PLANS, partner_terms=DEFAULT_PARTNER_TERMS):
    """Insert missing versions only; existing commercial configuration is immutable."""
    with sessions.begin() as session:
        for model, rows in ((RateCard, rate_cards), (PricingPlan, plans),
                            (OrganizationPlan, organization_plans), (PartnerTerms, partner_terms)):
            for values in rows:
                identity = values["id"] if "id" in values else (values["organization_id"], values["effective_from"])
                if session.get(model, identity) is None:
                    session.add(model(**values))
