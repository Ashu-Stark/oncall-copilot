"""SQLAlchemy engine and sessions (Postgres)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import normalise_db_url, settings


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_Session: sessionmaker | None = None


def init(url: str | None = None) -> Engine:
    """Create (or replace) the engine. Tests call this with their own database URL."""
    global _engine, _Session
    if _engine is not None:
        _engine.dispose()
    _engine = create_engine(normalise_db_url(url or settings.database_url), pool_pre_ping=True, pool_size=10, max_overflow=10)
    _Session = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def engine() -> Engine:
    if _engine is None:
        init()
    return _engine


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    engine()
    with _Session() as s:
        yield s


@contextmanager
def session_scope() -> Iterator[Session]:
    """For background work (investigations): commit on success, roll back on error."""
    engine()
    s = _Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
