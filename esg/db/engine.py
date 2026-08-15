"""
Engine and session construction.

One place decides how we talk to the database, so the same code runs against
SQLite on a laptop and Postgres in a deployed environment. The scope hooks are
installed on the sessionmaker here, which is what makes deal isolation
non-optional for every consumer.
"""

from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from esg.config import settings
from esg.db import scope
from esg.db.models import Base

_engine = None
_Session = None


def _configure_sqlite(engine):
    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()


def engine():
    global _engine
    if _engine is None:
        cfg = settings()
        url = cfg.resolved_database_url()
        kwargs = {"echo": cfg.sql_echo, "future": True}
        if url.startswith("postgresql"):
            kwargs.update(pool_pre_ping=True, pool_size=5, max_overflow=10)
        _engine = create_engine(url, **kwargs)
        if url.startswith("sqlite"):
            _configure_sqlite(_engine)
    return _engine


def session_factory():
    global _Session
    if _Session is None:
        _Session = scope.install(
            sessionmaker(bind=engine(), expire_on_commit=False, future=True)
        )
    return _Session


@contextmanager
def session():
    """Transactional session. Commits on clean exit, rolls back on any error."""
    s = session_factory()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def create_all():
    """Dev/test convenience. Deployed environments use Alembic migrations."""
    Base.metadata.create_all(engine())


def reset_engine():
    """Test hook — drop cached engine/sessionmaker so a new URL takes effect."""
    global _engine, _Session
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _Session = None


def health():
    with engine().connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"url": settings().resolved_database_url().split("@")[-1],
            "dialect": engine().dialect.name}
