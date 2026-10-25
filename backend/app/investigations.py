"""Runs the copilot on an incident's stored log window and records every step, so the UI can stream them.

The log lines go back into the copilot's own LogStore in their original order, so the ids it cites are the incident's
`seq` numbers. The readiness result captured with the alert is replayed to the `health` tool. Nothing about the
diagnosis logic changes: it is `copilot.agent.investigate` with an observer attached.
"""

from __future__ import annotations

import logging
import time
import traceback

from sqlalchemy import select
from sqlalchemy.orm import Session

from copilot.agent import investigate
from copilot.logstore import LogStore
from copilot.tools import Tools

from . import runbook_store
from .config import settings
from .db import session_scope
from .incidents import event
from .models import Incident, Investigation, InvestigationStep, LogLine, now

log = logging.getLogger("oncall.investigations")


def replay_health(snapshot: dict | None):
    """None -> no probe available. {"error": "ConnectionError"} -> the probe itself failed (service not running)."""
    if snapshot is None:
        return None

    def probe() -> dict:
        if "error" in snapshot:
            raise ConnectionError(snapshot["error"])
        return dict(snapshot)

    return probe


def load_store(s: Session, incident_id: int) -> LogStore:
    store = LogStore()
    rows = s.scalars(select(LogLine).where(LogLine.incident_id == incident_id).order_by(LogLine.seq)).all()
    for r in rows:
        new_id = store.add(r.level, r.logger, r.message, r.exc, r.ts or None)
        assert new_id == r.seq, "log ids must match the incident's seq numbers"
    return store


def _title(kind: str, data: dict) -> str:
    if kind == "alerts":
        names = [a["name"] for a in data["alerts"]]
        return f"Alert rules on the log window: {', '.join(names)}" if names else "No alert rule fired on the log window"
    if kind == "query":
        return "Built a search query from the alerts and the most frequent errors"
    if kind == "retrieval":
        return f"Retrieved {len(data['candidates'])} candidate runbooks ({data['ranker']} search)"
    if kind == "check":
        passed = sum(r["passed"] for r in data["results"])
        verdict = "confirmed" if data["confirmed"] else "rejected"
        return f"{data['runbook']}: {passed}/{len(data['results'])} checks passed, {verdict}"
    return kind


def _with_lines(store: LogStore, data: dict) -> dict:
    """Attach the cited log lines to a check step, so the UI can show the evidence next to each check."""
    for r in data.get("results", []):
        r["evidence_lines"] = [row.short()[:300] for row in store.get(r.get("evidence", [])[:5])]
    return data


def start(s: Session, incident: Incident, actor: str) -> Investigation:
    inv = Investigation(incident_id=incident.id, requested_by=actor)
    s.add(inv)
    s.flush()
    event(s, incident, "investigation", actor, "Copilot investigation started", {"investigation_id": inv.id})
    s.commit()
    return inv


def run(investigation_id: int, delay_ms: int | None = None) -> None:
    """Background task. Each step is committed as it happens (the SSE stream reads them from the database)."""
    delay = (settings.step_delay_ms if delay_ms is None else delay_ms) / 1000
    try:
        with session_scope() as s:
            inv = s.get(Investigation, investigation_id)
            inc = s.get(Incident, inv.incident_id)
            inv.status = "running"
            s.commit()
            store = load_store(s, inc.id)
            retriever, versions = runbook_store.retriever(s)
            seq, paced = 0, 0.0

            def add_step(kind: str, data: dict) -> None:
                nonlocal seq, paced
                seq += 1
                if kind == "check":
                    data = _with_lines(store, data)
                s.add(InvestigationStep(investigation_id=inv.id, seq=seq, kind=kind, title=_title(kind, data), data=data))
                s.commit()
                if delay:
                    t = time.perf_counter()
                    time.sleep(delay)
                    paced += time.perf_counter() - t

            d = investigate(Tools(store, replay_health(inc.health)), retriever, on_step=add_step)
            result = d.to_dict()
            # elapsed_ms is the copilot's own time: the display pacing between steps is not part of it
            result["elapsed_ms"] = round(max(0.0, d.elapsed_ms - paced * 1000), 1)
            result["paced_ms"] = round(paced * 1000)
            checks_used = next((c for c in d.checks if c["confirmed"]), None)
            result["verification"] = (
                {"runbook": d.label, "passed": len(checks_used["results"]), "total": len(checks_used["results"])} if checks_used else None
            )
            seq += 1
            title = {"NONE": "No incident: no alert rule fired", "UNKNOWN": "Abstained: no runbook was confirmed by the logs"}.get(
                d.label, f"Root cause: {d.label} · {d.title}"
            )
            s.add(InvestigationStep(investigation_id=inv.id, seq=seq, kind="verdict", title=title, data=result))
            inv.status, inv.label, inv.diagnosis, inv.finished_at = "done", d.label, result, now()
            inv.runbook_versions = {k: versions[k] for k in [c["runbook"] for c in d.candidates] if k in versions}
            event(s, inc, "verdict", "copilot", title, {"investigation_id": inv.id, "label": d.label, "evidence_ids": d.evidence_ids})
            # a confirmed runbook carries a severity; record it if it differs from the alert's guess
            if d.label not in ("NONE", "UNKNOWN") and d.severity[:4] in ("SEV1", "SEV2", "SEV3", "SEV4") and d.severity[:4] != inc.severity:
                event(s, inc, "severity", "copilot", f"Runbook {d.label} rates this {d.severity[:4]} (alert said {inc.severity}); severity updated")
                inc.severity = d.severity[:4]
            s.commit()
    except Exception as e:  # noqa: BLE001 - record the failure for the UI instead of losing it in a thread
        log.error("investigation %s failed: %s", investigation_id, type(e).__name__)
        with session_scope() as s:
            inv = s.get(Investigation, investigation_id)
            if inv is not None:
                inv.status, inv.error, inv.finished_at = "failed", "".join(traceback.format_exception_only(e)).strip()[:500], now()
