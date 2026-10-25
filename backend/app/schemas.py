"""Request bodies (validated before anything touches the database) and response helpers."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .models import Incident, Investigation, User

Severity = Literal["SEV1", "SEV2", "SEV3", "SEV4"]


class Login(BaseModel):
    username: str = Field(min_length=2, max_length=40)
    password: str = Field(min_length=1, max_length=200)


class LogIn(BaseModel):
    ts: float | None = None
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    logger: str = Field(max_length=80)
    message: str = Field(max_length=4000)
    exc: str | None = Field(default=None, max_length=8000)


class AlertIn(BaseModel):
    service: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=2, max_length=80, pattern=r"^[A-Za-z0-9_.:\- +]+$")
    summary: str = Field(min_length=1, max_length=500)
    severity: Severity = "SEV3"
    fingerprint: str | None = Field(default=None, min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_\-:.]+$")
    labels: dict[str, str | int | float | bool | list[str]] = Field(default_factory=dict, max_length=20)
    logs: list[LogIn] = Field(default_factory=list, max_length=5000)
    health: dict | None = None
    investigate: bool = True


class StatusIn(BaseModel):
    status: Literal["acknowledged", "investigating", "resolved"]
    resolution: str = Field(default="", max_length=2000)


class AssignIn(BaseModel):
    user_id: int | None


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class SimulateIn(BaseModel):
    fault: str = Field(min_length=2, max_length=40)
    seed: int = Field(default=7, ge=0, le=10_000)
    intensity: dict[str, int | float | str] = Field(default_factory=dict, max_length=5)


class RunbookIn(BaseModel):
    markdown: str = Field(min_length=10, max_length=50_000)
    comment: str = Field(default="", max_length=200)
    base_version: int | None = None  # optimistic locking: the version the editor started from


class ValidateIn(BaseModel):
    markdown: str = Field(max_length=50_000)
    id: str | None = None


def user_out(u: User | None) -> dict | None:
    return None if u is None else {"id": u.id, "username": u.username, "name": u.name, "role": u.role}


def investigation_out(inv: Investigation | None, steps: bool = False) -> dict | None:
    if inv is None:
        return None
    out = {
        "id": inv.id,
        "status": inv.status,
        "label": inv.label,
        "requested_by": inv.requested_by,
        "created_at": inv.created_at,
        "finished_at": inv.finished_at,
        "error": inv.error,
        "diagnosis": inv.diagnosis,
        "runbook_versions": inv.runbook_versions,
    }
    if steps:
        out["steps"] = [step_out(st) for st in inv.steps]
    return out


def step_out(st) -> dict:
    return {"seq": st.seq, "kind": st.kind, "title": st.title, "data": st.data, "at": st.at}


def incident_out(inc: Incident, latest: Investigation | None = None) -> dict:
    return {
        "id": inc.id,
        "title": inc.title,
        "service": inc.service.name,
        "severity": inc.severity,
        "status": inc.status,
        "assignee": user_out(inc.assignee),
        "created_at": inc.created_at,
        "acknowledged_at": inc.acknowledged_at,
        "resolved_at": inc.resolved_at,
        "is_demo": inc.is_demo,
        "simulated_fault": inc.simulated_fault,
        "expected_label": inc.expected_label,
        "resolution": inc.resolution,
        "alert_count": sum(a.count for a in inc.alerts),
        "alerts": [
            {"id": a.id, "name": a.name, "summary": a.summary, "severity": a.severity, "source": a.source, "count": a.count, "labels": a.labels, "first_seen": a.first_seen, "last_seen": a.last_seen}
            for a in inc.alerts
        ],
        "verdict": None if latest is None else {"investigation_id": latest.id, "status": latest.status, "label": latest.label},
    }
