"""Create M3 tables alongside M2 without destructive migrations."""

from chartground.platform_m2.database import Base, database as m2_database

from . import models  # noqa: F401 - registers additive tables on the shared metadata


def database(url=None):
    engine, sessions = m2_database(url)
    Base.metadata.create_all(engine)
    return engine, sessions
