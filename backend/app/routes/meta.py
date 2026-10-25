from __future__ import annotations

import json
from collections import Counter
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import select, text
from sqlalchemy.orm import Session, selectinload

from .. import investigations, simulator
from ..config import ROOT
from ..db import get_session
from ..incidents import OPEN, ingest_alert, mtta_mttr
from ..models import Incident, Investigation, User, now
from ..observability import metrics
from ..schemas import SimulateIn
from ..security import current_user

router = APIRouter(tags=["meta"])


def eval_summary() -> dict | None:
    """The offline evaluation's numbers (eval/run_eval.py), shown as they are: not recomputed or rounded up."""
    p = ROOT / "eval" / "results.json"
    if not p.exists():
        return None
    s = json.loads(p.read_text(encoding="utf-8"))["summary"]
    return {
        "scenarios": s["scenarios"],
        "incidents": s["incidents"],
        "detection_rate": s["detection_rate"],
        "false_alarm_rate": s["false_alarm_rate"],
        "recall_at_1": s["retrieval_recall@1"],
        "recall_at_3": s["retrieval_recall@3"],
        "modes": s["modes"],
    }


@router.get("/health")
def health(s: Session = Depends(get_session)) -> dict:
    s.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/metrics")
def get_metrics(_: User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    incs = s.scalars(select(Incident).where(Incident.created_at >= now() - timedelta(days=30))).all()
    return {"http": metrics.snapshot(), "incidents_30d": len(incs), **mtta_mttr(incs)}


@router.get("/dashboard")
def dashboard(_: User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    incs = s.scalars(select(Incident).options(selectinload(Incident.service)).where(Incident.created_at >= now() - timedelta(days=30))).all()
    open_ = [i for i in incs if i.status in OPEN]
    latest: dict[int, Investigation] = {}
    for inv in s.scalars(select(Investigation).where(Investigation.status == "done").order_by(Investigation.id)):
        latest[inv.incident_id] = inv
    verdicts = Counter("confirmed runbook" if (v := latest.get(i.id)) and v.label not in ("UNKNOWN", "NONE") else (v.label.lower() if v else "not investigated") for i in incs)
    simulated = [i for i in incs if i.expected_label and i.id in latest]
    by_day = Counter(i.created_at.date().isoformat() for i in incs)
    return {
        "window_days": 30,
        "open_by_severity": dict(Counter(i.severity for i in open_)),
        "open_total": len(open_),
        "total": len(incs),
        "demo_total": sum(i.is_demo for i in incs),
        **mtta_mttr(incs),
        "by_service": dict(Counter(i.service.name for i in incs)),
        "by_day": dict(sorted(by_day.items())),
        "verdicts": dict(verdicts),
        "simulated": {"total": len(simulated), "verdict_matches_ground_truth": sum(latest[i.id].label == i.expected_label for i in simulated)},
        "eval": eval_summary(),
    }


@router.get("/simulator")
def simulator_info(_: User = Depends(current_user)) -> dict:
    ok = simulator.available()
    return {"available": ok, "faults": simulator.faults() if ok else []}


@router.post("/simulator/run")
def simulate(body: SimulateIn, bg: BackgroundTasks, user: User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    res = simulator.run(body.fault, body.seed, dict(body.intensity))  # sync route: runs in the threadpool
    out = {"fault": body.fault, "expected": res["expected"], "alerts": res["alerts"], "log_lines": len(res["logs"]), "incident_id": None, "investigation_id": None}
    if not res["alerts"]:
        out["message"] = "No alert rule fired, so nobody is paged" + (" (correct: this fault has no user impact)" if res["expected"] == "NONE" else " (the fault was too weak to trip an alert)")
        return out
    names = [a["name"] for a in res["alerts"]]
    inc, _ = ingest_alert(
        s,
        service="hoi-platform",
        name=" + ".join(names),
        summary="; ".join(a["summary"] for a in res["alerts"]),
        severity=simulator.severity(names),
        source=f"simulator ({user.username})",
        fp=f"sim-{res['run_id']}",
        labels={"alerts": names, "simulated_fault": body.fault, "seed": body.seed},
        logs=res["logs"],
        health=res["health"],
        expected_label=res["expected"],
        simulated_fault=body.fault,
    )
    inv = investigations.start(s, inc, "copilot (auto)")
    bg.add_task(investigations.run, inv.id)
    out.update(incident_id=inc.id, investigation_id=inv.id, message=f"{', '.join(names)} fired; incident #{inc.id} opened and the copilot is investigating")
    return out
