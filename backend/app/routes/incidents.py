from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .. import investigations, postmortem
from ..db import get_session, session_scope
from ..incidents import OPEN, change_status, event, ingest_alert
from ..models import Incident, IncidentEvent, Investigation, InvestigationStep, LogLine, Service, User
from ..schemas import AlertIn, AssignIn, NoteIn, StatusIn, incident_out, investigation_out, step_out
from ..security import alert_source, current_user

router = APIRouter(tags=["incidents"])


def _incident(s: Session, iid: int) -> Incident:
    inc = s.get(Incident, iid, options=[selectinload(Incident.alerts), selectinload(Incident.service), selectinload(Incident.assignee)])
    if inc is None:
        raise HTTPException(404, "incident not found")
    return inc


def _latest(s: Session, iid: int) -> Investigation | None:
    return s.scalars(select(Investigation).where(Investigation.incident_id == iid).order_by(Investigation.id.desc())).first()


def _has_logs(s: Session, iid: int) -> bool:
    return bool(s.scalar(select(func.count()).select_from(LogLine).where(LogLine.incident_id == iid)))


@router.post("/alerts", status_code=201)
def post_alert(body: AlertIn, bg: BackgroundTasks, source: str = Depends(alert_source), s: Session = Depends(get_session)) -> dict:
    inc, created = ingest_alert(
        s,
        service=body.service,
        name=body.name,
        summary=body.summary,
        severity=body.severity,
        source=source,
        fp=body.fingerprint,
        labels=body.labels,
        logs=[line.model_dump() for line in body.logs],
        health=body.health,
    )
    inv_id = None
    if created and body.investigate and body.logs:
        inv = investigations.start(s, inc, "copilot (auto)")
        bg.add_task(investigations.run, inv.id)
        inv_id = inv.id
    return {"incident_id": inc.id, "created": created, "deduplicated": not created, "investigation_id": inv_id}


@router.get("/services")
def services(_: User = Depends(current_user), s: Session = Depends(get_session)) -> list[dict]:
    return [{"id": x.id, "name": x.name, "team": x.team, "description": x.description} for x in s.scalars(select(Service).order_by(Service.name))]


@router.get("/incidents")
def list_incidents(
    status: str = Query("open", pattern="^(open|resolved|all)$"),
    severity: str | None = Query(None, pattern="^SEV[1-4]$"),
    service: str | None = None,
    q: str | None = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: User = Depends(current_user),
    s: Session = Depends(get_session),
) -> dict:
    stmt = select(Incident).options(selectinload(Incident.alerts), selectinload(Incident.service), selectinload(Incident.assignee))
    if status == "open":
        stmt = stmt.where(Incident.status.in_(OPEN))
    elif status == "resolved":
        stmt = stmt.where(Incident.status == "resolved")
    if severity:
        stmt = stmt.where(Incident.severity == severity)
    if service:
        stmt = stmt.join(Service).where(Service.name == service)
    if q:
        stmt = stmt.where(or_(Incident.title.ilike(f"%{q}%"), Incident.resolution.ilike(f"%{q}%")))
    total = s.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = s.scalars(stmt.order_by(Incident.created_at.desc()).limit(limit).offset(offset)).all()
    latest = {}
    if rows:
        ids = [r.id for r in rows]
        sub = select(func.max(Investigation.id)).where(Investigation.incident_id.in_(ids)).group_by(Investigation.incident_id)
        latest = {i.incident_id: i for i in s.scalars(select(Investigation).where(Investigation.id.in_(sub)))}
    return {"items": [incident_out(r, latest.get(r.id)) for r in rows], "total": total}


@router.get("/incidents/{iid}")
def get_incident(iid: int, _: User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    inc = _incident(s, iid)
    out = incident_out(inc, _latest(s, iid))
    out["log_lines"] = s.scalar(select(func.count()).select_from(LogLine).where(LogLine.incident_id == iid))
    out["health"] = inc.health
    return out


@router.patch("/incidents/{iid}/status")
def set_status(iid: int, body: StatusIn, user: User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    inc = _incident(s, iid)
    if body.status == "resolved" and not body.resolution.strip():
        raise HTTPException(422, "say how it was resolved")
    change_status(s, inc, body.status, user.username, body.resolution.strip())
    return incident_out(inc, _latest(s, iid))


@router.patch("/incidents/{iid}/assignee")
def assign(iid: int, body: AssignIn, user: User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    inc = _incident(s, iid)
    target = None
    if body.user_id is not None:
        target = s.get(User, body.user_id)
        if target is None or not target.active:
            raise HTTPException(422, "unknown user")
    inc.assignee_id = target.id if target else None
    event(s, inc, "assigned", user.username, f"assigned to {target.name}" if target else "unassigned", {"user_id": body.user_id})
    s.commit()
    s.refresh(inc)
    return incident_out(inc, _latest(s, iid))


@router.post("/incidents/{iid}/notes", status_code=201)
def add_note(iid: int, body: NoteIn, user: User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    inc = _incident(s, iid)
    e = event(s, inc, "note", user.username, body.text.strip())
    s.commit()
    return {"id": e.id, "at": e.at, "kind": e.kind, "actor": e.actor, "text": e.text, "data": e.data}


@router.get("/incidents/{iid}/timeline")
def timeline(iid: int, _: User = Depends(current_user), s: Session = Depends(get_session)) -> list[dict]:
    _incident(s, iid)
    rows = s.scalars(select(IncidentEvent).where(IncidentEvent.incident_id == iid).order_by(IncidentEvent.at, IncidentEvent.id))
    return [{"id": e.id, "at": e.at, "kind": e.kind, "actor": e.actor, "text": e.text, "data": e.data} for e in rows]


@router.get("/incidents/{iid}/logs")
def logs(
    iid: int,
    ids: str | None = Query(None, max_length=500, description="comma-separated seq numbers"),
    level: str | None = Query(None, pattern="^(INFO|WARNING|ERROR|CRITICAL)$"),
    limit: int = Query(200, ge=1, le=1000),
    _: User = Depends(current_user),
    s: Session = Depends(get_session),
) -> list[dict]:
    _incident(s, iid)
    stmt = select(LogLine).where(LogLine.incident_id == iid)
    if ids:
        try:
            wanted = [int(x) for x in ids.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(422, "ids must be numbers") from None
        stmt = stmt.where(LogLine.seq.in_(wanted))
    if level:
        stmt = stmt.where(LogLine.level == level)
    return [{"seq": r.seq, "ts": r.ts, "level": r.level, "logger": r.logger, "message": r.message, "exc": r.exc} for r in s.scalars(stmt.order_by(LogLine.seq).limit(limit))]


@router.post("/incidents/{iid}/investigations", status_code=202)
def new_investigation(iid: int, bg: BackgroundTasks, user: User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    inc = _incident(s, iid)
    if not _has_logs(s, iid):
        raise HTTPException(409, "this incident has no log window; the copilot only diagnoses from logs")
    running = s.scalar(select(Investigation).where(Investigation.incident_id == iid, Investigation.status.in_(("queued", "running"))))
    if running is not None:
        return investigation_out(running)
    inv = investigations.start(s, inc, user.username)
    bg.add_task(investigations.run, inv.id)
    return investigation_out(inv)


@router.get("/incidents/{iid}/investigations")
def list_investigations(iid: int, _: User = Depends(current_user), s: Session = Depends(get_session)) -> list[dict]:
    _incident(s, iid)
    return [investigation_out(i) for i in s.scalars(select(Investigation).where(Investigation.incident_id == iid).order_by(Investigation.id.desc()))]


@router.get("/investigations/{inv_id}")
def get_investigation(inv_id: int, _: User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    inv = s.get(Investigation, inv_id, options=[selectinload(Investigation.steps)])
    if inv is None:
        raise HTTPException(404, "investigation not found")
    return investigation_out(inv, steps=True)


def _poll(inv_id: int, after: int) -> tuple[str | None, list[dict]]:
    with session_scope() as s:
        inv = s.get(Investigation, inv_id)
        if inv is None:
            return None, []
        steps = s.scalars(select(InvestigationStep).where(InvestigationStep.investigation_id == inv_id, InvestigationStep.seq > after).order_by(InvestigationStep.seq)).all()
        return inv.status, [step_out(x) for x in steps]


@router.get("/investigations/{inv_id}/stream")
async def stream(
    inv_id: int,
    request: Request,
    last_event_id: str | None = Header(default=None),
    _: User = Depends(current_user),
) -> StreamingResponse:
    """Server-Sent Events: one `step` event per investigation step (id = step number), then `done`.
    A client that reconnects with Last-Event-ID resumes after the last step it saw."""
    status, _steps = await run_in_threadpool(_poll, inv_id, 0)
    if status is None:
        raise HTTPException(404, "investigation not found")
    start = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0

    async def events():
        sent, idle = start, 0.0
        while True:
            status, steps = await run_in_threadpool(_poll, inv_id, sent)
            for st in steps:
                sent = st["seq"]
                yield f"id: {sent}\nevent: step\ndata: {json.dumps(st, default=str)}\n\n"
            if status in ("done", "failed") and not steps:
                yield f"event: done\ndata: {json.dumps({'status': status})}\n\n"
                return
            if await request.is_disconnected():
                return
            await asyncio.sleep(0.25)
            idle += 0.25
            if idle >= 10:
                idle = 0.0
                yield ": keep-alive\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/incidents/{iid}/postmortem")
def get_postmortem(iid: int, polish: bool = False, _: User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    draft = postmortem.build(s, _incident(s, iid))
    return postmortem.polish(draft) if polish else draft
