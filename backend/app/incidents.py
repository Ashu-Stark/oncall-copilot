"""Incident rules: alert deduplication, the status workflow, the timeline, and MTTA/MTTR."""

from __future__ import annotations

import hashlib
import statistics
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import Alert, Incident, IncidentEvent, LogLine, Service, now

# triggered -> acknowledged -> investigating -> resolved; a false alarm can be resolved straight away
TRANSITIONS = {
    "triggered": {"acknowledged", "resolved"},
    "acknowledged": {"investigating", "resolved"},
    "investigating": {"resolved"},
    "resolved": set(),
}
OPEN = ("triggered", "acknowledged", "investigating")
MAX_LOG_LINES = 5000


def fingerprint(service: str, name: str) -> str:
    return hashlib.sha256(f"{service}|{name}".encode()).hexdigest()[:40]


def event(s: Session, inc: Incident, kind: str, actor: str, text: str, data: dict | None = None, at: datetime | None = None) -> IncidentEvent:
    e = IncidentEvent(incident_id=inc.id, kind=kind, actor=actor, text=text, data=data or {}, at=at or now())
    s.add(e)
    return e


def ingest_alert(
    s: Session,
    *,
    service: str,
    name: str,
    summary: str,
    severity: str,
    source: str,
    fp: str | None = None,
    labels: dict | None = None,
    logs: list[dict] | None = None,
    health: dict | None = None,
    expected_label: str | None = None,
    simulated_fault: str | None = None,
) -> tuple[Incident, bool]:
    """Returns (incident, created). An alert whose fingerprint matches an OPEN incident is folded into it
    (count + 1, timeline entry) instead of paging again."""
    svc = s.scalar(select(Service).where(Service.name == service))
    if svc is None:
        raise HTTPException(422, f"unknown service '{service}'")
    fp = fp or fingerprint(service, name)
    for _ in range(2):
        dup = s.scalar(select(Alert).where(Alert.open_fingerprint == fp).with_for_update())
        if dup is not None:
            dup.count += 1
            dup.last_seen = now()
            inc = dup.incident
            event(s, inc, "alert_repeated", source, f"{name} fired again ({dup.count} times so far); not paged again", {"alert_id": dup.id})
            s.commit()
            return inc, False
        try:
            inc = Incident(
                title=f"{name}: {summary}"[:200],
                service_id=svc.id,
                severity=severity,
                health=health,
                expected_label=expected_label,
                simulated_fault=simulated_fault,
            )
            s.add(inc)
            s.flush()
            a = Alert(incident_id=inc.id, fingerprint=fp, open_fingerprint=fp, name=name, summary=summary, severity=severity, source=source, labels=labels or {})
            s.add(a)
            s.flush()  # the unique open_fingerprint is checked here
        except IntegrityError:
            s.rollback()  # another request opened the incident first: fold into it
            continue
        for i, line in enumerate((logs or [])[:MAX_LOG_LINES], 1):
            s.add(LogLine(incident_id=inc.id, seq=i, ts=float(line.get("ts") or 0), level=line["level"], logger=line["logger"], message=line["message"], exc=line.get("exc")))
        event(s, inc, "alert", source, f"{name}: {summary}", {"severity": severity, "labels": labels or {}, "log_lines": min(len(logs or []), MAX_LOG_LINES)})
        s.commit()
        return inc, True
    raise HTTPException(409, "could not record the alert; retry")


def change_status(s: Session, inc: Incident, to: str, actor: str, resolution: str = "") -> Incident:
    if to not in TRANSITIONS.get(inc.status, set()):
        allowed = ", ".join(sorted(TRANSITIONS.get(inc.status, set()))) or "none (resolved is final)"
        raise HTTPException(409, f"cannot move an incident from '{inc.status}' to '{to}'; allowed: {allowed}")
    t = now()
    if to == "acknowledged" or (to in ("investigating", "resolved") and inc.acknowledged_at is None):
        inc.acknowledged_at = inc.acknowledged_at or t
    if to == "resolved":
        inc.resolved_at = t
        inc.resolution = resolution
        for a in inc.alerts:
            a.open_fingerprint = None  # a new alert with the same fingerprint opens a new incident
    before, inc.status = inc.status, to
    event(s, inc, "status", actor, f"{before} → {to}" + (f": {resolution}" if resolution else ""), {"from": before, "to": to})
    s.commit()
    return inc


def minutes(a: datetime | None, b: datetime | None) -> float | None:
    if a is None or b is None:
        return None
    return round((b - a).total_seconds() / 60, 1)


def mtta_mttr(incidents: list[Incident]) -> dict:
    """Mean and median time to acknowledge / resolve, in minutes, over incidents that reached that state."""
    tta = [m for i in incidents if (m := minutes(i.created_at, i.acknowledged_at)) is not None]
    ttr = [m for i in incidents if (m := minutes(i.created_at, i.resolved_at)) is not None]

    def stats(xs: list[float]) -> dict:
        if not xs:
            return {"n": 0, "mean": None, "median": None}
        return {"n": len(xs), "mean": round(statistics.fmean(xs), 1), "median": round(statistics.median(xs), 1)}

    return {"mtta_minutes": stats(tta), "mttr_minutes": stats(ttr)}
