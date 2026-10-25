from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import runbook_store
from ..db import get_session
from ..models import Runbook, RunbookVersion, User
from ..schemas import RunbookIn, ValidateIn
from ..security import current_user, require_lead

router = APIRouter(tags=["runbooks"])


def _summary(r: Runbook) -> dict:
    return {"id": r.id, "title": r.title, "severity": r.severity, "service": r.service, "version": r.version, "updated_at": r.updated_at, "updated_by": r.updated_by}


def _parsed(markdown: str) -> dict | None:
    errors, rb = runbook_store.validate(markdown)
    if rb is None:
        return None
    return {"id": rb.id, "title": rb.title, "severity": rb.severity, "root_cause": rb.root_cause, "checks": rb.checks, "steps": rb.steps(), "sections": list(rb.sections)}


@router.get("/runbooks")
def list_runbooks(_: User = Depends(current_user), s: Session = Depends(get_session)) -> list[dict]:
    return [_summary(r) for r in s.scalars(select(Runbook).order_by(Runbook.id))]


@router.get("/runbooks/{rid}")
def get_runbook(rid: str, _: User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    r = s.get(Runbook, rid)
    if r is None:
        raise HTTPException(404, "runbook not found")
    versions = s.scalars(select(RunbookVersion).where(RunbookVersion.runbook_id == rid).order_by(RunbookVersion.version.desc()))
    return {
        **_summary(r),
        "markdown": r.markdown,
        "parsed": _parsed(r.markdown),
        "versions": [{"version": v.version, "edited_by": v.edited_by, "comment": v.comment, "at": v.at} for v in versions],
    }


@router.get("/runbooks/{rid}/versions/{version}")
def get_version(rid: str, version: int, _: User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    v = s.scalar(select(RunbookVersion).where(RunbookVersion.runbook_id == rid, RunbookVersion.version == version))
    if v is None:
        raise HTTPException(404, "version not found")
    return {"version": v.version, "markdown": v.markdown, "edited_by": v.edited_by, "comment": v.comment, "at": v.at}


@router.post("/runbooks/validate")
def validate(body: ValidateIn, _: User = Depends(current_user)) -> dict:
    errors, rb = runbook_store.validate(body.markdown, body.id)
    return {"valid": not errors, "errors": errors, "parsed": _parsed(body.markdown) if not errors else None}


@router.post("/runbooks", status_code=201)
def create_runbook(body: RunbookIn, user: User = Depends(require_lead), s: Session = Depends(get_session)) -> dict:
    errors, rb = runbook_store.validate(body.markdown)
    if errors:
        raise HTTPException(422, {"errors": errors})
    if s.get(Runbook, rb.id) is not None:
        raise HTTPException(409, f"{rb.id} already exists; edit it or pick a new id")
    r = runbook_store.save(s, body.markdown, user.username, body.comment or "created")
    s.commit()
    return _summary(r)


@router.put("/runbooks/{rid}")
def update_runbook(rid: str, body: RunbookIn, user: User = Depends(require_lead), s: Session = Depends(get_session)) -> dict:
    current = s.get(Runbook, rid, with_for_update=True)
    if current is None:
        raise HTTPException(404, "runbook not found")
    if body.base_version is not None and body.base_version != current.version:
        raise HTTPException(409, f"{rid} was changed by {current.updated_by} (now version {current.version}); reload and reapply your edit")
    errors, _ = runbook_store.validate(body.markdown, rid)
    if errors:
        raise HTTPException(422, {"errors": errors})
    if body.markdown == current.markdown:
        return _summary(current)
    r = runbook_store.save(s, body.markdown, user.username, body.comment, rid)
    s.commit()
    return _summary(r)
