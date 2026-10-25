"""Seed an empty database: services, demo users, the runbook library, and (optionally) a few DEMO incidents.

    python -m backend.app.seed                  # users, services, runbooks
    python -m backend.app.seed --demo-incidents # also simulate past incidents for the dashboard

Demo incidents are real simulations (real HOI logs, real copilot investigations) but their acknowledge/resolve times
are made up and backdated, so the dashboard has history to show. They are flagged `is_demo` and marked "[demo]".
"""

from __future__ import annotations

import argparse
import os
import random
from datetime import timedelta

from sqlalchemy import select

from . import db, investigations, runbook_store, simulator
from .config import settings
from .incidents import event, ingest_alert
from .models import Incident, IncidentEvent, Service, User, now
from .security import hash_password

SERVICES = [
    ("hoi-platform", "hotel-platform", "HOI hotel operations API (FastAPI + MongoDB). The simulator injects faults into it."),
    ("hoi-guest-web", "hotel-platform", "Guest-facing web app (demo entry, no simulator)."),
    ("tourism-portal", "partner-integrations", "External tourism portal HOI calls for places (demo entry)."),
]
DEMO_HISTORY = [  # fault, days ago, minutes to acknowledge, minutes to resolve (made up), resolution
    ("db_down", 12, 4, 38, "Atlas access list was missing the new egress IP; added it and /ready went green."),
    ("jwt_secret_rotated", 9, 7, 25, "Restored the previous HOI_JWT_SECRET from the secret manager and redeployed."),
    ("llm_rate_limited", 6, 11, 52, "Raised the provider quota; guests got rule-based replies meanwhile."),
    ("db_slow", 3, 6, 70, "Added the missing index on requests.status; p95 back under 150 ms."),
    ("password_guessing", 1, 3, 15, "Blocked 203.0.113.7 at the proxy; no account was compromised."),
]


def seed_basics(s, password: str) -> None:
    for name, team, desc in SERVICES:
        if s.scalar(select(Service).where(Service.name == name)) is None:
            s.add(Service(name=name, team=team, description=desc))
    for username, name, role in (("lead.demo", "Asha Rao", "lead"), ("engineer.demo", "Ravi Kumar", "engineer")):
        if s.scalar(select(User).where(User.username == username)) is None:
            s.add(User(username=username, name=name, role=role, password_hash=hash_password(password)))
    s.commit()
    n = runbook_store.seed_from_files(s)
    s.commit()
    print(f"services, users ok; {n} runbooks imported")


def seed_demo_incidents(s) -> None:
    if not simulator.available():
        print("HOI platform not found next to this repo: skipping demo incidents")
        return
    if s.scalar(select(Incident).where(Incident.is_demo.is_(True))):
        print("demo incidents already present")
        return
    lead = s.scalar(select(User).where(User.username == "lead.demo"))
    rng = random.Random(1)
    for fault, days, tta, ttr, resolution in DEMO_HISTORY:
        res = simulator.run(fault, 7, {})
        if not res["alerts"]:
            continue
        names = [a["name"] for a in res["alerts"]]
        inc, _ = ingest_alert(
            s, service="hoi-platform", name=" + ".join(names), summary="; ".join(a["summary"] for a in res["alerts"]),
            severity=simulator.severity(names), source="simulator (seed)", fp=f"demo-{fault}", labels={"alerts": names, "demo": True},
            logs=res["logs"], health=res["health"], expected_label=res["expected"], simulated_fault=fault,
        )
        inv = investigations.start(s, inc, "copilot (auto)")
        investigations.run(inv.id, delay_ms=0)
        s.expire_all()
        inc = s.get(Incident, inc.id)
        t0 = now() - timedelta(days=days, hours=rng.randint(0, 10), minutes=rng.randint(0, 59))
        shift = t0 - inc.created_at
        for e in s.scalars(select(IncidentEvent).where(IncidentEvent.incident_id == inc.id)):
            e.at = e.at + shift
        inc.title = "[demo] " + inc.title[:190]
        inc.is_demo, inc.created_at = True, t0
        inc.assignee_id = lead.id
        inc.acknowledged_at, inc.resolved_at = t0 + timedelta(minutes=tta), t0 + timedelta(minutes=ttr)
        inc.status, inc.resolution = "resolved", resolution
        for a in inc.alerts:
            a.open_fingerprint = None
            a.first_seen = a.last_seen = t0
        event(s, inc, "status", lead.username, "triggered → acknowledged", {"from": "triggered", "to": "acknowledged"}, at=inc.acknowledged_at)
        event(s, inc, "status", lead.username, f"acknowledged → resolved: {resolution}", {"from": "acknowledged", "to": "resolved"}, at=inc.resolved_at)
        s.commit()
        print(f"demo incident #{inc.id}: {fault}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo-incidents", action="store_true")
    a = ap.parse_args()
    password = os.environ.get("DEMO_PASSWORD") or ("" if settings.env == "production" else "oncall-demo-2026")
    if not password:
        raise SystemExit("set DEMO_PASSWORD to seed demo users in production")
    db.init()
    with db.session_scope() as s:
        seed_basics(s, password)
        if a.demo_incidents:
            seed_demo_incidents(s)


if __name__ == "__main__":
    main()
