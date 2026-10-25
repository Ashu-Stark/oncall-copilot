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


def card(r: dict) -> str:
    d = r["d"]
    ok = d.label == r["truth"]
    badge = f'<span class="badge {"ok" if ok else "bad"}">{"correct" if ok else "miss"}</span>'
    head = f'<h3>{e(TITLES[r["fault"]])} {badge}</h3><p class="meta">{r["logs"]} log lines from the real HOI API · diagnosed in {d.elapsed_ms:.0f} ms</p>'
    if d.label == "NONE":
        return f'<article class="card">{head}<p><b>No incident.</b> No alert rule fired, so nobody is paged.</p></article>'
    alerts = "".join(f"<span class=chip>{e(a)}</span>" for a in d.alerts)
    if d.label == "UNKNOWN":
        return f'<article class="card">{head}<p>Alerts: {alerts}</p><p><b>UNKNOWN</b>: {e(d.note)}</p></article>'
    confirmed = next((c for c in d.checks if c["confirmed"]), None)
    rejected = [c["runbook"] for c in d.checks if not c["confirmed"]]
    checks = ""
    if confirmed:
        rows = "".join(
            f"<tr><td><code>{e(x['tool'])}({e(json.dumps(x['args']))})</code></td><td>{e(str(x['field']))} {e(x['op'])} {e(str(x['expected']))}</td><td>{e(str(x['actual']))}</td><td>{'✔' if x['passed'] else '✘'}</td></tr>"
            for x in confirmed["results"]
        )
        checks = f'<details><summary>Checks that confirmed {e(d.label)}{" (ruled out first: " + e(", ".join(rejected)) + ")" if rejected else ""}</summary><table><tr><th>Tool</th><th>Expected</th><th>Actual</th><th></th></tr>{rows}</table></details>'
    evidence = "".join(f"<li><code>{e(x[:180])}</code></li>" for x in d.evidence[:4])
    steps = "".join(f"<li>{e(s)}</li>" for s in d.next_steps[:4])
    return (
        f'<article class="card">{head}<p>Alerts: {alerts}</p>'
        f'<p><b>{e(d.label)} · {e(d.title)}</b> <span class="muted">({e(d.severity)})</span><br>{e(d.root_cause)}</p>'
        f"{checks}<p class=label>Evidence (log lines)</p><ul class=ev>{evidence}</ul>"
        f"<details><summary>Next steps</summary><ol>{steps}</ol></details></article>"
    )


def results_table() -> str:
    s = json.loads((ROOT / "eval" / "results.json").read_text(encoding="utf-8"))["summary"]
    names = {
        "full": "<b>Copilot: hybrid retrieval + log-verified checks</b>",
        "hybrid-top1": "Hybrid retrieval, top-1, no verification",
        "bm25-top1": "BM25 only, top-1",
        "dense-top1": "LSA vectors only, top-1",
        "bm25+checks": "BM25 + verification",
    }
    rows = "".join(
        f"<tr><td>{names.get(m, m)}</td><td>{v['accuracy_all']:.0%}</td><td>{v['accuracy_on_detected_incidents']:.0%}</td><td>{v['wrong_root_cause']}</td></tr>"
        for m, v in s["modes"].items()
    )
    return (
        f"<p>{s['scenarios']} scenarios (11 types × 5 variants with different seeds, fault strength and noise): "
        f"{s['incidents']} injected incidents, {s['no_incident']} with no incident. "
        f"False alarms: <b>{s['false_alarm_rate']:.0%}</b>. Detection: <b>{s['detection_rate']:.0%}</b>. "
        f"Right runbook in top 3: <b>{s['retrieval_recall@3']:.0%}</b>.</p>"
        f"<table><tr><th>Mode</th><th>Correct (all)</th><th>Correct (detected)</th><th>Wrong root cause</th></tr>{rows}</table>"
        "<p class=muted>Optimistic by construction: the same person wrote the faults, alert rules and runbook checks. "
        "Verification is what removes wrong answers (3 → 0).</p>"
    )


CSS = """
:root{--bg:#f6f7fb;--card:#fff;--text:#15181f;--muted:#5a6072;--line:#e2e5ee;--accent:#1d4ed8;--ok:#0f7b3f;--bad:#b42318}
@media (prefers-color-scheme:dark){:root{--bg:#0f1218;--card:#171b24;--text:#e8eaf0;--muted:#a0a7b8;--line:#2a3040;--accent:#7aa2ff;--ok:#4ade80;--bad:#f87171}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:980px;margin:0 auto;padding:28px 16px 60px}h1{font-size:1.8rem;margin:.2em 0}h2{margin-top:2em}
.lede{font-size:1.05rem;color:var(--muted)}a{color:var(--accent)}code{font:12.5px ui-monospace,Consolas,monospace;word-break:break-word}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(440px,1fr));gap:14px}@media(max-width:520px){.grid{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}.card h3{margin:0 0 2px;font-size:1.02rem}
.meta,.muted,.label{color:var(--muted);font-size:.85rem;margin:2px 0 8px}.label{margin-bottom:2px}
.badge{font-size:.72rem;padding:2px 8px;border-radius:99px;vertical-align:middle;color:#fff}.ok{background:var(--ok)}.bad{background:var(--bad)}
.chip{display:inline-block;border:1px solid var(--line);border-radius:6px;padding:0 6px;margin:0 4px 4px 0;font-size:.8rem}
ul.ev{padding-left:18px;margin:4px 0}table{border-collapse:collapse;width:100%;margin:8px 0;font-size:.88rem}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}details{margin:6px 0}summary{cursor:pointer;color:var(--accent)}
.flow{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;overflow-x:auto;font:13px ui-monospace,Consolas,monospace;white-space:pre}
"""


def page(results: list[dict]) -> str:
    correct = sum(r["d"].label == r["truth"] for r in results)
    cards = "".join(card(r) for r in results)
    flow = (
        "fault injector ──► HOI platform API (real code) ──► log store (SQLite) ──► alert rules\n"
        "                                                                          │\n"
        "        hybrid retrieval over 16 runbooks (BM25 + LSA, Reciprocal Rank Fusion) ◄──┘\n"
        "                         │ top 5 candidates\n"
        "        verify: run each runbook's checks with read-only tools against the logs\n"
        "                         │ first runbook whose checks all pass, else UNKNOWN\n"
        "        grounding gate (runbook exists, every cited log line exists) ──► incident note"
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>On-call Runbook Copilot</title><style>{CSS}</style></head><body><main>
<h1>On-call Runbook Copilot</h1>
<p class="lede">When an alert fires, it retrieves the matching runbook, <b>checks the runbook's claims against the service's own logs</b>,
and writes an incident note with the root cause, the log lines that prove it, and the next steps. If nothing is confirmed it says
UNKNOWN instead of guessing. <a href="https://github.com/Ashu-Stark/oncall-copilot">Source on GitHub</a>.</p>
<h2>How it works</h2><div class="flow">{e(flow)}</div>
<h2>Live incident gallery</h2>
<p class="muted">Each card below was produced by actually running the copilot against the real HOI platform API with that fault injected
(seed 7). Correct on {correct} of {len(results)}. Generated {date.today():%d %b %Y}.</p>
<div class="grid">{cards}</div>
<h2>Evaluation</h2>{results_table()}
</main></body></html>"""


if __name__ == "__main__":
    res = run_all()
    out = ROOT / "docs" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(page(res), encoding="utf-8")
    (ROOT / "docs" / ".nojekyll").write_text("", encoding="utf-8")
    print("wrote", out)
