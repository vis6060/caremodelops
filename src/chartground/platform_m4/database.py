"""Create M4 tables alongside existing M2 and M3 data."""

from chartground.platform_m2.database import Base, database as m2_database

from . import models  # noqa: F401


def database(url=None):
    engine, sessions = m2_database(url)
    Base.metadata.create_all(engine)
    return engine, sessions
