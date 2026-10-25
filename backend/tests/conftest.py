"""Backend tests run against a real Postgres: DATABASE_URL if set (CI uses a postgres service container), otherwise an
embedded server started with `pgserver`. The schema is created with the Alembic migrations, as in production."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

_server = None
if not os.environ.get("TEST_DATABASE_URL"):
    import pgserver

    _dir = tempfile.mkdtemp(prefix="oncall-pg-")
    _server = pgserver.get_server(_dir, cleanup_mode="stop")
    _base = _server.get_uri()
    from sqlalchemy import create_engine, text as _sql

    _admin = create_engine(_base.replace("postgresql://", "postgresql+psycopg://"), isolation_level="AUTOCOMMIT")
    with _admin.connect() as _c:
        _c.execute(_sql("DROP DATABASE IF EXISTS oncall_test"))
        _c.execute(_sql("CREATE DATABASE oncall_test"))
    _admin.dispose()
    os.environ["TEST_DATABASE_URL"] = _base.rsplit("/", 1)[0] + "/oncall_test"

os.environ.update(
    DATABASE_URL=os.environ["TEST_DATABASE_URL"],
    JWT_SECRET="test-secret-" + "x" * 40,
    ALERT_INGEST_KEY="test-ingest-key-0123456789abcdef",
    STEP_DELAY_MS="0",
    APP_ENV="test",
)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from backend.app import db, runbook_store  # noqa: E402
from backend.app.main import app  # noqa: E402
from backend.app.security import throttle  # noqa: E402
from backend.app.seed import seed_basics  # noqa: E402

PASSWORD = "test-password-123"
INGEST = {"X-Alert-Key": "test-ingest-key-0123456789abcdef"}


@pytest.fixture(scope="session", autouse=True)
def schema():
    cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
    command.upgrade(cfg, "head")
    db.init(os.environ["DATABASE_URL"])
    with db.session_scope() as s:
        seed_basics(s, PASSWORD)
    yield
    db.engine().dispose()
    if _server is not None:
        _server.cleanup()
        shutil.rmtree(_dir, ignore_errors=True)


@pytest.fixture(autouse=True)
def clean():
    """Fresh incidents and runbook library for every test (users and services are kept)."""
    with db.engine().begin() as c:
        c.execute(text("TRUNCATE incidents, alerts, log_lines, incident_events, investigations, investigation_steps, runbooks, runbook_versions RESTART IDENTITY CASCADE"))
    runbook_store.invalidate()
    with db.session_scope() as s:
        runbook_store.seed_from_files(s)
    throttle.reset()
    yield


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def login(client, username: str) -> dict:
    r = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="session")
def lead(client):
    return login(client, "lead.demo")


@pytest.fixture(scope="session")
def eng(client):
    return login(client, "engineer.demo")


def db_outage_logs(n: int = 5) -> list[dict]:
    """A MongoDB outage as HOI logs it (same shape as the unit test in tests/test_copilot.py)."""
    exc = "Traceback...\npymongo.errors.ServerSelectionTimeoutError: db:27017: timed out"
    out = []
    for i in range(n):
        out.append({"level": "ERROR", "logger": "hoi.platform", "message": f"unhandled error rid=r{i} GET /rooms", "exc": exc})
        out.append({"level": "INFO", "logger": "hoi.platform", "message": f"rid=r{i} GET /rooms -> 500 4ms"})
    out.append({"level": "WARNING", "logger": "hoi.platform", "message": "readiness check failed: database ping did not succeed"})
    return out
