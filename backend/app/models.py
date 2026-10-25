"""Tables. Times are timezone-aware UTC."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

Json = JSON().with_variant(JSONB(), "postgresql")


def now() -> datetime:
    return datetime.now(UTC)


SEVERITIES = ("SEV1", "SEV2", "SEV3", "SEV4")
ROLES = ("engineer", "lead")


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(10), default="engineer")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Service(Base):
    __tablename__ = "services"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    team: Mapped[str] = mapped_column(String(60), default="")
    description: Mapped[str] = mapped_column(Text, default="")


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    severity: Mapped[str] = mapped_column(String(4))
    status: Mapped[str] = mapped_column(String(14), default="triggered", index=True)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # readiness probe result captured with the alert; replayed to the copilot's health tool
    health: Mapped[dict | None] = mapped_column(Json)
    # simulated incidents only: the runbook the injected fault really corresponds to (ground truth, shown in the UI)
    expected_label: Mapped[str | None] = mapped_column(String(10))
    simulated_fault: Mapped[str | None] = mapped_column(String(40))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    resolution: Mapped[str] = mapped_column(Text, default="")

    service: Mapped[Service] = relationship()
    assignee: Mapped[User | None] = relationship()
    alerts: Mapped[list[Alert]] = relationship(back_populates="incident", order_by="Alert.id")


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    # equals `fingerprint` while the incident is open and NULL after it is resolved; the unique constraint makes
    # "one open incident per fingerprint" hold even when two identical alerts arrive at the same moment
    open_fingerprint: Mapped[str | None] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    summary: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(4))
    source: Mapped[str] = mapped_column(String(40), default="api")
    labels: Mapped[dict] = mapped_column(Json, default=dict)
    count: Mapped[int] = mapped_column(Integer, default=1)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    incident: Mapped[Incident] = relationship(back_populates="alerts")


class LogLine(Base):
    """The log window attached to an incident. `seq` is 1..n in arrival order and is the id the copilot cites."""

    __tablename__ = "log_lines"
    __table_args__ = (UniqueConstraint("incident_id", "seq"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    ts: Mapped[float] = mapped_column(Float)
    level: Mapped[str] = mapped_column(String(10))
    logger: Mapped[str] = mapped_column(String(80))
    message: Mapped[str] = mapped_column(Text)
    exc: Mapped[str | None] = mapped_column(Text)


class IncidentEvent(Base):
    """Timeline: alerts, state changes, assignment, notes, investigation progress and verdicts."""

    __tablename__ = "incident_events"
    __table_args__ = (Index("ix_events_incident_at", "incident_id", "at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    kind: Mapped[str] = mapped_column(String(30))
    actor: Mapped[str] = mapped_column(String(60))
    text: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(Json, default=dict)


class Investigation(Base):
    __tablename__ = "investigations"
    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(10), default="queued")  # queued, running, done, failed
    requested_by: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    label: Mapped[str | None] = mapped_column(String(10))  # RBnn, UNKNOWN or NONE
    diagnosis: Mapped[dict | None] = mapped_column(Json)
    error: Mapped[str] = mapped_column(Text, default="")
    runbook_versions: Mapped[dict] = mapped_column(Json, default=dict)  # which runbook versions were used

    steps: Mapped[list[InvestigationStep]] = relationship(order_by="InvestigationStep.seq")


class InvestigationStep(Base):
    __tablename__ = "investigation_steps"
    __table_args__ = (UniqueConstraint("investigation_id", "seq"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    investigation_id: Mapped[int] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))  # alerts, query, retrieval, check, verdict
    title: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(Json, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Runbook(Base):
    """The markdown is the source of truth (same format as runbooks/*.md); the other columns are parsed from it."""

    __tablename__ = "runbooks"
    id: Mapped[str] = mapped_column(String(10), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    service: Mapped[str] = mapped_column(String(60), default="")
    severity: Mapped[str] = mapped_column(String(40), default="")
    markdown: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_by: Mapped[str] = mapped_column(String(60), default="seed")


class RunbookVersion(Base):
    __tablename__ = "runbook_versions"
    __table_args__ = (UniqueConstraint("runbook_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    runbook_id: Mapped[str] = mapped_column(ForeignKey("runbooks.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    markdown: Mapped[str] = mapped_column(Text)
    edited_by: Mapped[str] = mapped_column(String(60))
    comment: Mapped[str] = mapped_column(String(200), default="")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
