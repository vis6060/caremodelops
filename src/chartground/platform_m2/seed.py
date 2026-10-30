"""Fictional local tenants. Only hashes of high-entropy keys enter the database."""

from .api import key_digest
from .database import Agent, CaseGrant, Developer, Organization, Partner

TENANTS = (
    ("oncopilot", "OncoPilot", "direct", None, "onco-dev", "onco-agent", ("cg-syn-001", "cg-syn-012")),
    ("radpath", "RadPath", "partner", "meddata-partners", "rad-dev", "rad-agent", ("cg-syn-002", "cg-syn-013")),
)


def seed(sessions, keys):
    if len(set(keys.values())) != 2 or any(len(v) < 32 for v in keys.values()):
        raise ValueError("Provide distinct high-entropy tenant credentials.")
    with sessions.begin() as session:
        if session.get(Partner, "meddata-partners") is None:
            session.add(Partner(id="meddata-partners", name="MedData Partners"))
            session.flush()
        for org_id, name, channel, partner, developer, agent, cases in TENANTS:
            if session.get(Organization, org_id) is None:
                session.add(Organization(id=org_id, name=name, channel=channel, partner_id=partner))
                session.flush()
            existing = session.get(Developer, developer)
            digest = key_digest(keys[org_id])
            if existing is not None and existing.key_hash != digest:
                raise ValueError("Seed credentials do not match existing database; keys were not rotated.")
            if existing is None:
                session.add(Developer(id=developer, organization_id=org_id, key_hash=digest))
            if session.get(Agent, agent) is None:
                session.add(Agent(id=agent, organization_id=org_id))
            for case_id in cases:
                if session.get(CaseGrant, (org_id, case_id)) is None:
                    session.add(CaseGrant(organization_id=org_id, case_id=case_id))
