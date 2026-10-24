"""Evaluate the copilot on injected HOI incidents with known root causes.

    python eval/run_eval.py                # deterministic modes (offline)
    python eval/run_eval.py --llm          # also the LLM modes (needs LLM_API_KEY or GROQ_API_KEY)

11 scenario types x 5 variants = 55 scenarios: 9 real faults, 1 dependency outage with no user impact, and healthy
traffic. Variants change the seed, the fault intensity and the background noise (typo logins, 404s), so some faults
are deliberately too weak to trip an alert.

Modes (ablation):
  full        hybrid retrieval + runbook checks verified against the logs (the copilot)
  hybrid-top1 hybrid retrieval, take the top runbook, no verification
  bm25-top1   keyword retrieval only, no verification
  dense-top1  LSA vectors only, no verification
  bm25+checks keyword retrieval + verification (is the dense half worth it?)
  llm+rag     LLM chooses tools, can search/read/check runbooks       (--llm)
  llm-no-rag  LLM sees only runbook titles + log tools                 (--llm)

CAVEAT (also in the README): the same person wrote the faults, the alert rules and the runbook checks, so these numbers
are optimistic. They show the pipeline works end to end on a real codebase and how the parts compare; they are not an
estimate of accuracy on unseen production incidents.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.faults import FAULTS, run_scenario  # noqa: E402  (first: puts HOI on sys.path)

from copilot.agent import investigate  # noqa: E402
from copilot.retrieval import HybridRetriever  # noqa: E402
from copilot.runbooks import load  # noqa: E402
from copilot.tools import Tools  # noqa: E402

NOISE = [0.03, 0.05, 0.08, 0.12, 0.15]
INTENSITY = {
    "db_slow": [{"delay_ms": d} for d in (40, 80, 120, 160, 220)],
    "password_guessing": [{"attempts": a} for a in (8, 12, 18, 25, 35)],
    "rate_limit_misconfigured": [{"per_minute": n} for n in (1, 2, 3, 5, 8)],
    "llm_schema_drift": [{"style": s} for s in ("prose", "json", "prose", "json", "prose")],
    "portal_down": [{"mode": m} for m in ("timeout", "refused", "http", "timeout", "http")],
}


def scenarios() -> list[dict]:
    out = []
    for name in [*FAULTS, None]:
        for i in range(5):
            out.append(
                {
                    "id": f"{name or 'healthy'}-{i}",
                    "fault": name,
                    "label": FAULTS[name].label if name else "NONE",
                    "seed": 100 + i,
                    "noise": NOISE[i],
                    "kw": INTENSITY.get(name, [{}] * 5)[i] if name else {},
                }
            )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--only", help="comma-separated scenario name prefixes")
    args = ap.parse_args()

    retriever = HybridRetriever(load())
    modes = {
        "full": dict(verify_checks=True, ranker="hybrid"),
        "hybrid-top1": dict(verify_checks=False, ranker="hybrid"),
        "bm25-top1": dict(verify_checks=False, ranker="bm25"),
        "dense-top1": dict(verify_checks=False, ranker="dense"),
        "bm25+checks": dict(verify_checks=True, ranker="bm25"),
    }
    llm = None
    if args.llm:
        from copilot.llm_agent import LlmClient, investigate_llm

        llm = LlmClient()
        if not llm.available():
            sys.exit("--llm needs LLM_API_KEY or GROQ_API_KEY in the environment")

    rows = []
    todo = [s for s in scenarios() if not args.only or any(s["id"].startswith(p) for p in args.only.split(","))]
    for n, sc in enumerate(todo, 1):

        def look(env, sc=sc):
            t = Tools(env.store, env.health)
            out = {m: investigate(t, retriever, **kw) for m, kw in modes.items()}
            if llm:
                out["llm+rag"] = investigate_llm(t, retriever, llm, use_runbooks=True)
                out["llm-no-rag"] = investigate_llm(t, retriever, llm, use_runbooks=False)
            # retrieval quality is measured on the hybrid ranking, independent of verification
            full = out["full"]
            ranked = [c["runbook"] for c in full.candidates]
            return out, ranked, env.store.rows("1=1", limit=1_000_000).__len__()

        t0 = time.time()
        _, (res, ranked, n_logs) = run_scenario(sc["fault"], sc["seed"], sc["kw"], noise=sc["noise"], investigate=look)
        row = {**sc, "log_lines": n_logs, "ranked": ranked, "seconds": round(time.time() - t0, 1), "modes": {}}
        for m, d in res.items():
            row["modes"][m] = {
                "pred": d.label,
                "correct": d.label == sc["label"],
                "alerts": d.alerts,
                "evidence_ids": d.evidence_ids,
                "actionable": d.actionable,
                "ms": d.elapsed_ms,
                "note": d.note,
            }
        rows.append(row)
        f = row["modes"]["full"]
        print(f"[{n:2}/{len(todo)}] {sc['id']:<28} truth={sc['label']:<7} full={f['pred']:<7} {'OK ' if f['correct'] else 'MISS'} alerts={f['alerts']}", flush=True)

    summary = summarize(rows, list(rows[0]["modes"]) if rows else [])
    out_dir = ROOT / "eval"
    (out_dir / "results.json").write_text(json.dumps({"summary": summary, "scenarios": rows}, indent=1, default=str), encoding="utf-8")
    (out_dir / "results.md").write_text(to_markdown(summary, rows), encoding="utf-8")
    print(json.dumps(summary, indent=1))


def summarize(rows: list[dict], modes: list[str]) -> dict:
    inc = [r for r in rows if r["label"] != "NONE"]
    quiet = [r for r in rows if r["label"] == "NONE"]
    detected = [r for r in inc if r["modes"]["full"]["alerts"]]
    s: dict = {
        "scenarios": len(rows),
        "incidents": len(inc),
        "no_incident": len(quiet),
        "detection_rate": round(len(detected) / len(inc), 3) if inc else None,
        "false_alarm_rate": round(sum(bool(r["modes"]["full"]["alerts"]) for r in quiet) / len(quiet), 3) if quiet else None,
        "retrieval_recall@1": round(sum(r["ranked"][:1] == [r["label"]] for r in detected) / len(detected), 3) if detected else None,
        "retrieval_recall@3": round(sum(r["label"] in r["ranked"][:3] for r in detected) / len(detected), 3) if detected else None,
        "modes": {},
    }
    for m in modes:
        res = [r["modes"][m] for r in rows]
        det = [r["modes"][m] for r in detected]
        wrong_confident = sum(1 for r in rows if r["modes"][m]["pred"] not in ("UNKNOWN", r["label"]) and r["modes"][m]["pred"] != "NONE")
        s["modes"][m] = {
            "accuracy_all": round(sum(x["correct"] for x in res) / len(res), 3),
            "accuracy_on_detected_incidents": round(sum(x["correct"] for x in det) / len(det), 3) if det else None,
            "wrong_root_cause": wrong_confident,
            "abstained_unknown": sum(x["pred"] == "UNKNOWN" for x in res),
            "median_ms": sorted(x["ms"] for x in res)[len(res) // 2],
        }
    per_fault = defaultdict(lambda: [0, 0])
    for r in rows:
        k = r["fault"] or "healthy"
        per_fault[k][0] += r["modes"]["full"]["correct"]
        per_fault[k][1] += 1
    s["full_by_scenario_type"] = {k: f"{a}/{b}" for k, (a, b) in per_fault.items()}
    return s


def to_markdown(s: dict, rows: list[dict]) -> str:
    lines = [
        "# Evaluation results",
        "",
        f"{s['scenarios']} scenarios on the real HOI platform API (in-process, synthetic demo data): {s['incidents']} injected incidents, {s['no_incident']} with no incident.",
        "",
        "> Optimistic by construction: faults, alert rules and runbook checks were written by the same author.",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Detection rate (an alert fired for an incident) | {s['detection_rate']:.0%} |",
        f"| False-alarm rate (alert fired with no incident) | {s['false_alarm_rate']:.0%} |",
        f"| Retrieval recall@1 (hybrid, detected incidents) | {s['retrieval_recall@1']:.0%} |",
        f"| Retrieval recall@3 (hybrid, detected incidents) | {s['retrieval_recall@3']:.0%} |",
        "",
        "| Mode | Accuracy (all) | Accuracy (detected incidents) | Wrong root cause | Abstained | Median ms |",
        "|---|---|---|---|---|---|",
    ]
    for m, v in s["modes"].items():
        lines.append(f"| {m} | {v['accuracy_all']:.0%} | {v['accuracy_on_detected_incidents']:.0%} | {v['wrong_root_cause']} | {v['abstained_unknown']} | {v['median_ms']} |")
    lines += ["", "## Full copilot by scenario type", "", "| Scenario | Correct |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in s["full_by_scenario_type"].items()]
    lines += ["", "## Misses (full copilot)", ""]
    for r in rows:
        f = r["modes"]["full"]
        if not f["correct"]:
            lines.append(f"- `{r['id']}` truth {r['label']}, predicted {f['pred']}, alerts {f['alerts'] or 'none'}, params {r['kw']}, noise {r['noise']}. {f['note']}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
