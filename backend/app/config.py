"""Settings from the environment. Read once at import, BEFORE the HOI harness is imported (the harness removes LLM keys
from os.environ so the system under test can never reach a real model)."""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # repo root: copilot/, harness/, runbooks/, eval/
log = logging.getLogger("oncall.config")


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    env: str = field(default_factory=lambda: os.environ.get("APP_ENV", "development"))
    database_url: str = field(default_factory=lambda: os.environ.get("DATABASE_URL", ""))
    jwt_secret: str = field(default_factory=lambda: os.environ.get("JWT_SECRET", ""))
    jwt_minutes: int = field(default_factory=lambda: int(os.environ.get("JWT_MINUTES", "480")))
    alert_ingest_key: str = field(default_factory=lambda: os.environ.get("ALERT_INGEST_KEY", ""))
    cors_origins: list[str] = field(
        default_factory=lambda: [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:5184,http://127.0.0.1:5184").split(",") if o.strip()]
    )
    # the investigation itself takes a few ms; steps are paced so a person can follow them in the UI (0 in tests)
    step_delay_ms: int = field(default_factory=lambda: int(os.environ.get("STEP_DELAY_MS", "350")))
    simulator_enabled: bool = field(default_factory=lambda: _bool("SIMULATOR_ENABLED", True))
    llm_api_key: str = field(default_factory=lambda: os.environ.get("LLM_API_KEY") or os.environ.get("GROQ_API_KEY") or "")
    llm_base_url: str = field(default_factory=lambda: os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1"))
    llm_model: str = field(default_factory=lambda: os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile"))

    def check(self) -> None:
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is not set (postgresql+psycopg://user:pass@host/db)")
        if self.env == "production":
            if len(self.jwt_secret) < 32:
                raise RuntimeError("production needs JWT_SECRET (at least 32 characters)")
            if len(self.alert_ingest_key) < 24:
                raise RuntimeError("production needs ALERT_INGEST_KEY (at least 24 characters)")
        elif not self.jwt_secret:
            # development only: sessions end when the process restarts
            self.jwt_secret = secrets.token_urlsafe(48)
            log.warning("JWT_SECRET not set; using a random one for this process (development only)")


settings = Settings()


def normalise_db_url(url: str) -> str:
    """Render and Heroku hand out postgres:// URLs; SQLAlchemy needs the driver named."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url
