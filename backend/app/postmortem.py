"""Postmortem draft built from the incident record: timeline, copilot verdict with evidence, resolution, action items.

Template-based by default, so every sentence comes from data in the database. If an LLM key is configured on the
server, `polish=True` asks the model to rewrite only the summary paragraph from the facts; the rest stays templated.
"""

from __future__ import annotations

import json
import urllib.request

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .incidents import minutes
from .models import Incident, IncidentEvent, Investigation


def _fmt(dt) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC") if dt else "-"


def build(s: Session, inc: Incident) -> dict:
    events = s.scalars(select(IncidentEvent).where(IncidentEvent.incident_id == inc.id).order_by(IncidentEvent.at, IncidentEvent.id)).all()
    inv = s.scalars(select(Investigation).where(Investigation.incident_id == inc.id, Investigation.status == "done").order_by(Investigation.id.desc())).first()
    d = (inv.diagnosis or {}) if inv else {}
    label = d.get("label")
    tta, ttr = minutes(inc.created_at, inc.acknowledged_at), minutes(inc.created_at, inc.resolved_at)
    tta_s = f"{tta} min" if tta is not None else "not yet"
    ttr_s = f"{ttr} min" if ttr is not None else "not yet"

    if label and label not in ("NONE", "UNKNOWN"):
        cause = f"{label} · {d.get('title')}: {d.get('root_cause')}"
    elif label == "UNKNOWN":
        cause = "Not confirmed by the copilot (it abstained). Fill in the root cause found by the responders."
    else:
        cause = "No copilot verdict recorded."
    summary = (
        f"{inc.severity} incident on {inc.service.name}: {inc.title}. Detected {_fmt(inc.created_at)}, "
        + (f"acknowledged after {tta} min, " if tta is not None else "not acknowledged yet, ")
        + (f"resolved after {ttr} min." if ttr is not None else "not resolved yet.")
    )
    lines = [
        f"# Postmortem draft: incident #{inc.id}",
        "",
        f"> Draft generated from the incident record{' (demo data)' if inc.is_demo else ''}. Review every section before sharing.",
        "",
        "## Summary",
        summary,
        "",
        "## Impact",
        f"- Service: **{inc.service.name}** · Severity: **{inc.severity}** · Status: **{inc.status}**",
        f"- Alerts: " + ", ".join(f"{a.name} (x{a.count})" for a in inc.alerts),
        f"- Time to acknowledge: {tta_s} · Time to resolve: {ttr_s}",
        "",
        "## Root cause",
        cause,
    ]
    if d.get("evidence"):
        lines += ["", "**Evidence cited by the copilot (log lines):**", *[f"- `{e[:200]}`" for e in d["evidence"][:6]]]
    if inc.expected_label:
        verdict = "matches" if label == inc.expected_label else "does NOT match"
        lines += ["", f"**Simulation ground truth:** {inc.expected_label} (fault `{inc.simulated_fault}`); the copilot's verdict {verdict}."]
    lines += ["", "## Timeline", "", "| Time (UTC) | Who | What |", "|---|---|---|"]
    for e in events:
        if e.kind in ("note", "status", "alert", "alert_repeated", "verdict", "assigned", "severity", "investigation"):
            lines.append(f"| {e.at.strftime('%H:%M:%S')} | {e.actor} | {e.text.replace('|', '/')[:160]} |")
    lines += ["", "## Resolution", inc.resolution or "_Not resolved yet._", "", "## Action items"]
    steps = [x for x in d.get("next_steps", []) if x.startswith("[Mitigation]")][:3]
    items = [f"- [ ] Make permanent: {x.removeprefix('[Mitigation] ')}" for x in steps]
    if label == "UNKNOWN":
        items.append("- [ ] Write a runbook (with checks) for this failure, so the copilot recognises it next time")
    items += ["- [ ] Check that the alert fired early enough; adjust its threshold if not", "- [ ] Review this draft with the responders"]
    lines += items
    return {"markdown": "\n".join(lines) + "\n", "summary": summary, "polished": False}


def polish(draft: dict) -> dict:
    """Optional: rewrite the summary paragraph with an LLM (server-side key only)."""
    if not settings.llm_api_key:
        return draft
    body = {
        "model": settings.llm_model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": "Rewrite this incident summary as two clear sentences for a postmortem. Use only the facts given; add nothing."},
            {"role": "user", "content": draft["summary"]},
        ],
    }
    req = urllib.request.Request(
        settings.llm_base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {settings.llm_api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            text = json.loads(r.read())["choices"][0]["message"]["content"].strip()
    except Exception:  # noqa: BLE001 - the template draft is still valid
        return draft
    return {**draft, "markdown": draft["markdown"].replace(draft["summary"], text, 1), "polished": True}
