"""Alembic environment: migrates the database in DATABASE_URL (or the URL a caller put in the config)."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine

from backend.app import models  # noqa: F401  (registers the tables)
from backend.app.config import normalise_db_url, settings
from backend.app.db import Base

url = context.config.get_main_option("sqlalchemy.url") or settings.database_url
if not url:
    raise SystemExit("set DATABASE_URL")


def run() -> None:
    engine = create_engine(normalise_db_url(url))
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run()
