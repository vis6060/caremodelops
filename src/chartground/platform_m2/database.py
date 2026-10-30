"""Portable SQLAlchemy persistence; tenant identity is supplied by authentication."""

import os
from pathlib import Path

from sqlalchemy import Column, ForeignKey, Integer, JSON, String, UniqueConstraint, create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

ROOT = Path(__file__).resolve().parents[3]
LOCAL = ROOT / "results/m2_local"
Base = declarative_base()


class Partner(Base):
    __tablename__ = "m2_partners"
    id = Column(String(80), primary_key=True)
    name = Column(String(120), nullable=False)


class Organization(Base):
    __tablename__ = "m2_organizations"
    id = Column(String(80), primary_key=True)
    name = Column(String(120), nullable=False)
    channel = Column(String(20), nullable=False)
    partner_id = Column(String(80), ForeignKey(Partner.id), nullable=True)


class Developer(Base):
    __tablename__ = "m2_developers"
    id = Column(String(80), primary_key=True)
    organization_id = Column(String(80), ForeignKey(Organization.id), nullable=False)
    key_hash = Column(String(64), unique=True, nullable=False)


class Agent(Base):
    __tablename__ = "m2_agents"
    id = Column(String(80), primary_key=True)
    organization_id = Column(String(80), ForeignKey(Organization.id), nullable=False)


class CaseGrant(Base):
    __tablename__ = "m2_case_grants"
    organization_id = Column(String(80), ForeignKey(Organization.id), primary_key=True)
    case_id = Column(String(40), primary_key=True)


class Run(Base):
    __tablename__ = "m2_runs"
    __table_args__ = (UniqueConstraint("organization_id", "idempotency_key"),)
    id = Column(String(36), primary_key=True)
    organization_id = Column(String(80), ForeignKey(Organization.id), nullable=False, index=True)
    developer_id = Column(String(80), ForeignKey(Developer.id), nullable=False)
    agent_id = Column(String(80), ForeignKey(Agent.id), nullable=False)
    partner_id = Column(String(80), nullable=True)
    idempotency_key = Column(String(128), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    case_id = Column(String(40), nullable=False)
    provider = Column(String(10), nullable=False)
    status = Column(String(24), nullable=False)
    created_at = Column(String(40), nullable=False)
    response = Column(JSON, nullable=True)


class Attempt(Base):
    __tablename__ = "m2_attempts"
    __table_args__ = (UniqueConstraint("run_id", "number"),)
    id = Column(Integer, primary_key=True)
    run_id = Column(String(36), ForeignKey(Run.id), nullable=False, index=True)
    number = Column(Integer, nullable=False)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    cache_creation_tokens = Column(Integer, nullable=True)
    cache_read_tokens = Column(Integer, nullable=True)
    details = Column(JSON, nullable=False)


def database(url=None):
    url = url or os.getenv("CHARTGROUND_M2_DATABASE_URL")
    if not url:
        LOCAL.mkdir(parents=True, exist_ok=True)
        url = "sqlite:///" + (LOCAL / "platform.sqlite3").as_posix()
    if not url.startswith(("sqlite:///", "postgresql+psycopg://")):
        raise ValueError("Use SQLite or postgresql+psycopg database URLs.")
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30} if url.startswith("sqlite") else {}, hide_parameters=True)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(engine, expire_on_commit=False)
