"""The on-call copilot: alert -> retrieve runbooks -> verify each against the logs -> diagnosis with citations.

Two investigators share the same tools and output:
- `investigate` (default, deterministic): runs the checks written in each retrieved runbook, in retrieval order, and
  confirms the first runbook whose checks all pass. Abstains ("UNKNOWN") when none does.
- `copilot.llm_agent.investigate_llm`: an LLM that chooses the tools itself (needs an API key).
Every diagnosis is validated the same way: the runbook must exist and every cited log id must exist in the store.
"""

from __future__ import annotations

import operator
import time
from dataclasses import asdict, dataclass, field

from .alerts import Alert, evaluate
from .logstore import template
from .retrieval import HybridRetriever
from .runbooks import Runbook
from .tools import ToolResult, Tools

OPS = {">=": operator.ge, "<=": operator.le, ">": operator.gt, "<": operator.lt, "==": operator.eq}
NOT_ACTIONABLE = ("SEV4",)  # runbooks that describe expected behaviour


@dataclass
class CheckResult:
    tool: str
    args: dict
    field: str
    op: str
    expected: object
    actual: object
    passed: bool
    evidence: list[int]


@dataclass
class Diagnosis:
    label: str  # runbook id, "NONE" (no incident) or "UNKNOWN" (alerts fired but nothing confirmed)
    title: str = ""
    severity: str = ""
    root_cause: str = ""
    alerts: list[str] = field(default_factory=list)
    query: str = ""
    candidates: list[dict] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)  # "#id LEVEL logger: message" lines
    evidence_ids: list[int] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    actionable: bool = True
    elapsed_ms: float = 0.0
    mode: str = "runbook-guided"
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def run_check(t: Tools, check: dict) -> CheckResult:
    fn = getattr(t, check["tool"], None)
    if fn is None:
        return CheckResult(check["tool"], check.get("args", {}), check.get("field", ""), check["op"], check["value"], None, False, [])
    res: ToolResult = fn(**check.get("args", {}))
    val = res.value
    actual = val.get(check["field"]) if isinstance(val, dict) and check.get("field") else val
    try:
        ok = actual is not None and OPS[check["op"]](actual, check["value"])
    except TypeError:
        ok = False
    return CheckResult(check["tool"], check.get("args", {}), check.get("field", ""), check["op"], check["value"], actual, bool(ok), res.evidence)


def build_query(t: Tools, alerts: list[Alert]) -> str:
    """What an engineer would type: the alerts plus the most frequent warning/error messages and fallback reasons."""
    parts = [f"{a.name}: {a.summary}" for a in alerts]
    parts += [e["template"] for e in t.top_errors(3).value]
    fb = [r for r in t.store.rows("message LIKE 'concierge fallback to rules:%' AND message NOT LIKE '%places question%'")]
    if fb:
        common = {}
        for r in fb:
            k = template(r.message)
            common[k] = common.get(k, 0) + 1
        parts.append(max(common, key=common.get))
    return " | ".join(parts)


def verify(t: Tools, rb: Runbook) -> tuple[bool, list[CheckResult]]:
    results = [run_check(t, c) for c in rb.checks]
    return bool(results) and all(r.passed for r in results), results


def finalize(d: Diagnosis, t: Tools, runbooks: dict[str, Runbook]) -> Diagnosis:
    """Shared grounding gate: unknown runbook or a cited log id that does not exist -> UNKNOWN."""
    if d.label not in ("NONE", "UNKNOWN"):
        rb = runbooks.get(d.label)
        rows = t.store.get(d.evidence_ids)
        if rb is None:
            d.note = f"rejected: runbook {d.label} does not exist"
            d.label = "UNKNOWN"
        elif len(rows) != len(set(d.evidence_ids)) or not rows:
            d.note = "rejected: diagnosis cited log lines that do not exist (or none)"
            d.label = "UNKNOWN"
        else:
            d.evidence = [r.short() for r in rows]
            d.title, d.severity, d.root_cause = rb.title, rb.severity, rb.root_cause
            d.next_steps = d.next_steps or rb.steps()
            d.actionable = not any(s in rb.severity for s in NOT_ACTIONABLE)
    return d


def investigate(
    t: Tools,
    retriever: HybridRetriever,
    k: int = 5,
    verify_checks: bool = True,
    ranker: str = "hybrid",
) -> Diagnosis:
    t0 = time.perf_counter()
    alerts = evaluate(t)
    if not alerts:
        return Diagnosis("NONE", note="no alert fired", elapsed_ms=round((time.perf_counter() - t0) * 1000, 1))
    query = build_query(t, alerts)
    if ranker == "bm25":
        cands = [(rb, f"bm25 {s:.2f}") for rb, s, _ in retriever.bm25_only(query)[:k]]
    elif ranker == "dense":
        cands = [(rb, f"dense {s:.2f}") for rb, s, _ in retriever.dense_only(query)[:k]]
    else:
        cands = [(h.runbook_id, f"rrf {h.score} (bm25 #{h.bm25_rank}, dense #{h.dense_rank}) via {h.best_chunk}") for h in retriever.search(query, k)]
    d = Diagnosis("UNKNOWN", alerts=[a.name for a in alerts], query=query, candidates=[{"runbook": rb, "why": w} for rb, w in cands])
    d.mode = f"{ranker}{'+checks' if verify_checks else ''}"
    if not verify_checks:
        top = cands[0][0]
        d.label = top
        d.evidence_ids = sorted({i for a in alerts for i in a.evidence})[:10]
    else:
        for rb_id, _ in cands:
            ok, results = verify(t, retriever.runbooks[rb_id])
            d.checks.append({"runbook": rb_id, "confirmed": ok, "results": [asdict(r) for r in results]})
            if ok:
                d.label = rb_id
                d.evidence_ids = sorted({i for r in results for i in r.evidence})[:10]
                break
        if d.label == "UNKNOWN":
            d.note = f"none of the top {k} runbooks was confirmed by the logs; escalate to a human"
    d = finalize(d, t, retriever.runbooks)
    d.elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    return d


def render(d: Diagnosis) -> str:
    """Markdown incident note for the on-call engineer."""
    if d.label == "NONE":
        return "**No incident:** no alert rule fired."
    lines = [f"**Alerts:** {', '.join(d.alerts)}"]
    if d.label == "UNKNOWN":
        lines += ["**Diagnosis:** UNKNOWN. " + d.note, "**Runbooks considered:** " + ", ".join(c["runbook"] for c in d.candidates)]
        return "\n".join(lines)
    lines += [
        f"**Diagnosis:** {d.label} - {d.title} ({d.severity}){'' if d.actionable else ' (expected behaviour, no action needed)'}",
        f"**Root cause:** {d.root_cause}",
        "**Evidence:**",
        *[f"- `{e[:220]}`" for e in d.evidence[:6]],
        "**Next steps:**",
        *[f"{i}. {s}" for i, s in enumerate(d.next_steps, 1)],
    ]
    return "\n".join(lines)
