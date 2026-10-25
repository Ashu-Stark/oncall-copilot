"""Builds the public demo page (docs/index.html, served by GitHub Pages).

For every fault type it runs the REAL pipeline: boot HOI in-process, inject the fault, send traffic, run the copilot,
and render the incident note it produced. Nothing on the page is written by hand except the headings.

    python site/build_site.py
"""

from __future__ import annotations

import html
import json
import logging
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.faults import FAULTS, run_scenario  # noqa: E402  (first: puts HOI on sys.path)

from copilot.agent import investigate  # noqa: E402
from copilot.retrieval import HybridRetriever  # noqa: E402
from copilot.runbooks import load  # noqa: E402
from copilot.tools import Tools  # noqa: E402

TITLES = {
    "db_down": "Database unreachable",
    "db_slow": "Database slow",
    "llm_rate_limited": "LLM provider rate-limited (HTTP 429)",
    "llm_key_missing": "LLM API key missing after a deploy",
    "llm_schema_drift": "LLM replies no longer match the schema",
    "jwt_secret_rotated": "Token signing secret changed",
    "password_guessing": "Password guessing on /auth/login",
    "unsafe_prod_config": "Deploy refused: unsafe production config",
    "rate_limit_misconfigured": "Rate limit set too low",
    "portal_down": "Tourism portal down (absorbed by cache)",
    None: "Healthy traffic",
}

e = html.escape


def run_all() -> list[dict]:
    # do NOT call logging.disable here: the copilot reads HOI's own log records
    retriever = HybridRetriever(load())
    out = []
    for name in [*FAULTS, None]:
        def look(env, name=name):
            t = Tools(env.store, env.health)
            d = investigate(t, retriever)
            return d, len(env.store.rows("1=1", limit=1_000_000))

        _, (d, n_logs) = run_scenario(name, seed=7, investigate=look, before=20, after=40)
        truth = FAULTS[name].label if name else "NONE"
        out.append({"fault": name, "truth": truth, "d": d, "logs": n_logs})
        print(f"{name or 'healthy':<26} truth={truth:<5} -> {d.label}", flush=True)
    return out


SEV_CLASS = {"SEV1": "sev1", "SEV2": "sev2", "SEV3": "sev3", "SEV4": "sev4"}


def sev_of(d) -> str:
    for k in SEV_CLASS:
        if k in (d.severity or ""):
            return k
    return ""


def card(r: dict) -> str:
    d = r["d"]
    ok = d.label == r["truth"]
    badge = f'<span class="badge {"ok" if ok else "bad"}">{"✔ correct" if ok else "✘ miss"}</span>'
    meta = f'<p class="meta">{r["logs"]} log lines from the real HOI API · diagnosed in {d.elapsed_ms:.0f} ms</p>'
    if d.label == "NONE":
        return (
            f'<article class="card calm"><header><h3>{e(TITLES[r["fault"]])}</h3>{badge}</header>{meta}'
            '<p class="verdict calmtext">No incident: no alert rule fired, so nobody is paged.</p></article>'
        )
    alerts = "".join(f'<span class="chip">{e(a)}</span>' for a in d.alerts)
    if d.label == "UNKNOWN":
        return f'<article class="card"><header><h3>{e(TITLES[r["fault"]])}</h3>{badge}</header>{meta}<div class="chips">{alerts}</div><p class="verdict">UNKNOWN: {e(d.note)}</p></article>'
    sev = sev_of(d)
    confirmed = next((c for c in d.checks if c["confirmed"]), None)
    rejected = [c["runbook"] for c in d.checks if not c["confirmed"]]
    checks = ""
    if confirmed:
        rows = "".join(
            f"<tr><td><code>{e(x['tool'])}</code></td><td>{e(str(x['field']))} {e(x['op'])} {e(str(x['expected']))}</td><td><b>{e(str(x['actual']))}</b></td><td class='{'pass' if x['passed'] else 'fail'}'>{'✔' if x['passed'] else '✘'}</td></tr>"
            for x in confirmed["results"]
        )
        ruled = f'<p class="ruled">Ruled out first: {e(", ".join(rejected))}</p>' if rejected else ""
        checks = f'<details open><summary>Proof from the logs</summary><table><tr><th>Check</th><th>Expected</th><th>Actual</th><th></th></tr>{rows}</table>{ruled}</details>'
    evidence = "".join(f"<li><code>{e(x[:160])}</code></li>" for x in d.evidence[:3])
    steps = "".join(f"<li>{e(s.split('] ', 1)[-1])}</li>" for s in d.next_steps[:4])
    return (
        f'<article class="card {SEV_CLASS.get(sev, "")}"><header><h3>{e(TITLES[r["fault"]])}</h3>{badge}</header>{meta}'
        f'<div class="chips">{alerts}</div>'
        f'<p class="verdict"><span class="sev">{e(sev)}</span> <b>{e(d.label)} · {e(d.title)}</b></p>'
        f'<p class="cause">{e(d.root_cause)}</p>{checks}'
        f'<details><summary>Cited log lines</summary><ul class="ev">{evidence}</ul></details>'
        f'<details><summary>Next steps</summary><ol>{steps}</ol></details></article>'
    )


def summary() -> dict:
    return json.loads((ROOT / "eval" / "results.json").read_text(encoding="utf-8"))["summary"]


def stats_row(s: dict) -> str:
    full, top1 = s["modes"]["full"], s["modes"]["hybrid-top1"]
    items = [
        (f"{s['false_alarm_rate']:.0%}", "false alarms on healthy traffic"),
        (f"{full['accuracy_on_detected_incidents']:.0%}", "correct root cause on detected incidents"),
        (f"{top1['wrong_root_cause']} → {full['wrong_root_cause']}", "wrong diagnoses, without → with log verification"),
        (str(s["scenarios"]), "faults injected into the real HOI API"),
    ]
    return '<div class="stats">' + "".join(f'<div class="stat"><b>{v}</b><span>{t}</span></div>' for v, t in items) + "</div>"


def pipeline() -> str:
    steps = [
        ("Alert fires", "rules over HOI's own logs: error rate, latency, 401/429 spikes, readiness"),
        ("Retrieve", "hybrid search over 16 runbooks: BM25 + LSA, Reciprocal Rank Fusion"),
        ("Verify", "run each runbook's checks against the logs with read-only tools"),
        ("Ground", "the runbook must exist and every cited log line must exist"),
        ("Report", "root cause, evidence, next steps, or UNKNOWN"),
    ]
    return '<div class="pipe">' + "".join(
        f'<div class="step"><span class="n">{i}</span><b>{e(t)}</b><span>{e(d)}</span></div>' for i, (t, d) in enumerate(steps, 1)
    ) + "</div>"


def results_table(s: dict) -> str:
    names = {
        "full": "<b>Copilot: hybrid retrieval + log-verified checks</b>",
        "hybrid-top1": "Hybrid retrieval, top-1, no verification",
        "bm25-top1": "BM25 only, top-1",
        "dense-top1": "LSA vectors only, top-1",
        "bm25+checks": "BM25 + verification",
    }
    rows = "".join(
        f"<tr{' class=hl' if m == 'full' else ''}><td>{names.get(m, m)}</td><td>{v['accuracy_all']:.0%}</td><td>{v['accuracy_on_detected_incidents']:.0%}</td><td>{v['wrong_root_cause']}</td></tr>"
        for m, v in s["modes"].items()
    )
    return (
        f"<p>{s['scenarios']} scenarios (11 types × 5 variants with different seeds, fault strength and background noise): "
        f"{s['incidents']} injected incidents and {s['no_incident']} with nothing wrong. Detection rate {s['detection_rate']:.0%}; "
        f"the right runbook is in the top 3 for {s['retrieval_recall@3']:.0%} of detected incidents.</p>"
        f"<table><tr><th>Mode</th><th>Correct (all 55)</th><th>Correct (detected)</th><th>Wrong root cause</th></tr>{rows}</table>"
        "<p class=muted>Honest caveat: the same person wrote the faults, the alert rules and the runbook checks, so these numbers are optimistic. "
        "They show the pipeline works end to end on a real codebase and how its parts compare.</p>"
    )


CSS = """
:root{--bg:#f5f7fb;--card:#fff;--text:#121620;--muted:#5a6175;--line:#e3e7ef;--accent:#2952e3;--accent2:#7c3aed;
--ok:#0f7b3f;--bad:#b42318;--sev1:#d92d20;--sev2:#ea7a0c;--sev3:#c99a06;--sev4:#64748b;--calm:#12a150}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--card:#161b24;--text:#e7eaf0;--muted:#9aa3b5;--line:#272e3b;--accent:#7c9cff;--accent2:#b794f6;--ok:#4ade80;--bad:#f87171}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.6 "Segoe UI",system-ui,-apple-system,Roboto,sans-serif}
main{max-width:1120px;margin:0 auto;padding:0 18px 70px}a{color:var(--accent)}
.hero{background:linear-gradient(135deg,#1e40af,#6d28d9);color:#fff;padding:46px 18px 40px;margin-bottom:26px}
.hero .in{max-width:1120px;margin:0 auto}.hero h1{font-size:2.3rem;margin:0 0 8px;letter-spacing:-.5px}
.hero p{max-width:760px;font-size:1.08rem;opacity:.95;margin:0}.hero a{color:#fff;text-decoration:underline}
.tag{display:inline-block;background:rgba(255,255,255,.18);border-radius:99px;padding:2px 12px;font-size:.8rem;margin-bottom:12px}
h2{font-size:1.35rem;margin:38px 0 12px}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:-52px;position:relative}
.stat{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;box-shadow:0 6px 18px rgba(16,24,40,.06)}
.stat b{display:block;font-size:1.9rem;line-height:1.1;color:var(--accent)}.stat span{color:var(--muted);font-size:.86rem}
.pipe{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}
.step{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;position:relative}
.step .n{display:inline-grid;place-items:center;width:24px;height:24px;border-radius:7px;background:var(--accent);color:#fff;font-size:.8rem;font-weight:700;margin-right:6px}
.step b{font-size:.98rem}.step span:last-child{display:block;color:var(--muted);font-size:.84rem;margin-top:4px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(500px,1fr));gap:16px}
.card{background:var(--card);border:1px solid var(--line);border-left:6px solid var(--sev4);border-radius:14px;padding:16px 18px;box-shadow:0 2px 8px rgba(16,24,40,.04)}
.card.sev1{border-left-color:var(--sev1)}.card.sev2{border-left-color:var(--sev2)}.card.sev3{border-left-color:var(--sev3)}.card.calm{border-left-color:var(--calm)}
.card header{display:flex;justify-content:space-between;align-items:center;gap:10px}.card h3{margin:0;font-size:1.06rem}
.meta{color:var(--muted);font-size:.82rem;margin:2px 0 8px}
.badge{font-size:.74rem;font-weight:600;padding:3px 10px;border-radius:99px;color:#fff;white-space:nowrap}.ok{background:var(--ok)}.bad{background:var(--bad)}
.chips{margin:4px 0 6px}.chip{display:inline-block;background:var(--bg);border:1px solid var(--line);border-radius:7px;padding:1px 8px;margin:0 6px 4px 0;font-size:.8rem;font-family:Consolas,ui-monospace,monospace}
.verdict{margin:6px 0 2px}.sev{font-size:.72rem;font-weight:700;color:#fff;background:var(--sev4);border-radius:5px;padding:2px 6px;margin-right:4px}
.sev1 .sev{background:var(--sev1)}.sev2 .sev{background:var(--sev2)}.sev3 .sev{background:var(--sev3)}
.cause{color:var(--muted);font-size:.9rem;margin:2px 0 8px}.calmtext{color:var(--calm);font-weight:600}
details{margin:6px 0}summary{cursor:pointer;color:var(--accent);font-weight:600;font-size:.9rem}
table{border-collapse:collapse;width:100%;margin:8px 0;font-size:.86rem}th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600}.pass{color:var(--ok);font-weight:700}.fail{color:var(--bad);font-weight:700}tr.hl td{background:rgba(41,82,227,.07)}
.ruled{color:var(--muted);font-size:.82rem;margin:2px 0}ul.ev{padding-left:18px;margin:6px 0}code{font:12.5px Consolas,ui-monospace,monospace;word-break:break-word}
.muted{color:var(--muted);font-size:.88rem}footer{color:var(--muted);font-size:.85rem;margin-top:40px;border-top:1px solid var(--line);padding-top:14px}
@media(max-width:860px){.stats{grid-template-columns:repeat(2,1fr)}.pipe{grid-template-columns:1fr}.grid{grid-template-columns:1fr}}
"""


def page(results: list[dict]) -> str:
    s = summary()
    correct = sum(r["d"].label == r["truth"] for r in results)
    cards = "".join(card(r) for r in results)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>On-call Runbook Copilot</title><meta name="description" content="An on-call assistant that proves root causes from live logs.">
<style>{CSS}</style></head><body>
<section class="hero"><div class="in"><span class="tag">RAG + agent · evaluated on 55 injected faults</span>
<h1>On-call Runbook Copilot</h1>
<p>When an alert fires, it finds the matching runbook, <b>proves the root cause from the service's own logs</b>, cites the
log lines and lists next steps. If the logs confirm nothing, it says UNKNOWN instead of guessing.
<a href="https://github.com/Ashu-Stark/oncall-copilot">Source code</a> · <a href="https://github.com/Ashu-Stark/oncall-copilot/blob/main/docs/On-call_Runbook_Copilot_Documentation.pdf">Documentation (PDF)</a></p></div></section>
<main>
{stats_row(s)}
<h2>How it works</h2>{pipeline()}
<h2>Live incident gallery</h2>
<p class="muted">Each card was produced by actually running the copilot against the real HOI platform API with that fault injected
(seed 7): {correct} of {len(results)} correct. Generated {date.today():%d %b %Y}.</p>
<div class="grid">{cards}</div>
<h2>Evaluation</h2>{results_table(s)}
<footer>Built by Ashutosh · Python, BM25, LSA, SQLite, FastAPI (HOI) · all HOI data is synthetic demo data.</footer>
</main></body></html>"""


if __name__ == "__main__":
    res = run_all()
    out = ROOT / "docs" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(page(res), encoding="utf-8")
    (ROOT / "docs" / ".nojekyll").write_text("", encoding="utf-8")
    print("wrote", out)
