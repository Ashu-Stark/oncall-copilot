"""LLM investigator: the model picks the tools (function calling) and writes the diagnosis.

Works with any OpenAI-compatible chat API (Groq by default, OpenAI, or local Ollama):
    LLM_API_KEY / GROQ_API_KEY, LLM_BASE_URL (default https://api.groq.com/openai/v1), LLM_MODEL.
The key is read from the environment at call time and never logged. Only log lines from the service under test are
sent (HOI's are synthetic demo data). Tools are read-only. The final answer goes through the same grounding gate as the
deterministic investigator (`agent.finalize`): unknown runbook ids or log ids that do not exist -> UNKNOWN.
With `use_runbooks=False` the model gets only runbook titles, not their content (the "no retrieval" baseline).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from .agent import Diagnosis, build_query, finalize, verify
from .alerts import evaluate
from .retrieval import HybridRetriever
from .tools import Tools

MAX_TURNS = 10

SYSTEM = """You are an on-call SRE copilot for the HOI hotel platform API. Find the root cause of the alerts.
Use the tools to look at the logs before deciding. Never invent log lines or numbers: cite only log ids returned by tools.
When done, reply with ONLY this JSON (no prose):
{"runbook_id": "RBnn" or null, "root_cause": "one sentence", "evidence_log_ids": [ints], "confidence": "high|medium|low"}
Use null when the evidence does not support any runbook; that is better than a wrong guess."""


def _schema(name: str, desc: str, props: dict | None = None, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {"name": name, "description": desc, "parameters": {"type": "object", "properties": props or {}, "required": required or []}},
    }


def tool_specs(use_runbooks: bool) -> list[dict]:
    specs = [
        _schema("status_summary", "Counts of HTTP responses by status in the incident window."),
        _schema(
            "status_count",
            "Number and share of responses with a status (e.g. 401) or class ('5xx'), optionally for a path prefix.",
            {"status": {"type": "string"}, "path_prefix": {"type": "string"}},
            ["status"],
        ),
        _schema("latency", "p50/p95/max latency in ms."),
        _schema("latency_trend", "p95 of the first vs last third of requests (slow only at start = cold start)."),
        _schema("distinct_clients_401", "Where the 401s are: on /auth/login vs elsewhere, top paths."),
        _schema("search_logs", "Log lines containing a substring (message or exception).", {"pattern": {"type": "string"}}, ["pattern"]),
        _schema("top_errors", "Most frequent warning/error message templates."),
        _schema("health", "Current readiness of the service."),
    ]
    if use_runbooks:
        specs += [
            _schema("search_runbooks", "Hybrid search over runbooks; returns ids and titles.", {"query": {"type": "string"}}, ["query"]),
            _schema("read_runbook", "Full text of a runbook including its checks.", {"runbook_id": {"type": "string"}}, ["runbook_id"]),
            _schema("run_runbook_checks", "Runs a runbook's checks against the logs; returns pass/fail per check.", {"runbook_id": {"type": "string"}}, ["runbook_id"]),
        ]
    return specs


class LlmClient:
    def __init__(self):
        self.key = os.environ.get("LLM_API_KEY") or os.environ.get("GROQ_API_KEY")
        self.base = (os.environ.get("LLM_BASE_URL") or "https://api.groq.com/openai/v1").rstrip("/")
        self.model = os.environ.get("LLM_MODEL") or "llama-3.3-70b-versatile"

    def available(self) -> bool:
        return bool(self.key)

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        body = json.dumps({"model": self.model, "messages": messages, "tools": tools, "temperature": 0}).encode()
        req = urllib.request.Request(
            self.base + "/chat/completions",
            data=body,
            headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"},
        )
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return json.loads(r.read())["choices"][0]["message"]
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 3:
                    time.sleep(float(e.headers.get("retry-after") or 5))
                    continue
                raise RuntimeError(f"LLM HTTP {e.code}") from None
        raise RuntimeError("LLM rate limited")


def _parse_final(text: str) -> dict:
    text = (text or "").strip()
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start : end + 1]) if start >= 0 else {}


def investigate_llm(t: Tools, retriever: HybridRetriever, client: LlmClient | None = None, use_runbooks: bool = True) -> Diagnosis:
    t0 = time.perf_counter()
    client = client or LlmClient()
    alerts = evaluate(t)
    if not alerts:
        return Diagnosis("NONE", note="no alert fired", mode="llm")
    seen_ids: set[int] = set()

    def call(name: str, args: dict) -> object:
        if name == "search_runbooks":
            return [{"id": h.runbook_id, "title": retriever.runbooks[h.runbook_id].title} for h in retriever.search(args.get("query", ""), 5)]
        if name == "read_runbook":
            rb = retriever.runbooks.get(args.get("runbook_id", ""))
            return rb.path.read_text(encoding="utf-8") if rb else "no such runbook"
        if name == "run_runbook_checks":
            rb = retriever.runbooks.get(args.get("runbook_id", ""))
            if not rb:
                return "no such runbook"
            ok, results = verify(t, rb)
            for r in results:
                seen_ids.update(r.evidence)
            return {"confirmed": ok, "checks": [{"check": f"{r.tool} {r.args} {r.field} {r.op} {r.expected}", "actual": r.actual, "passed": r.passed, "evidence_log_ids": r.evidence} for r in results]}
        fn = getattr(t, name, None)
        if fn is None:
            return f"unknown tool {name}"
        if name == "status_count" and str(args.get("status", "")).isdigit():
            args = {**args, "status": int(args["status"])}
        res = fn(**args)
        seen_ids.update(res.evidence)
        return {"value": res.value, "evidence_log_ids": res.evidence}

    catalog = "\n".join(f"- {rb.id}: {rb.title}" for rb in retriever.runbooks.values())
    user = f"Alerts:\n" + "\n".join(f"- {a.name}: {a.summary} (log ids {a.evidence[:5]})" for a in alerts)
    user += f"\n\nSearch hint: {build_query(t, alerts)}\n\nRunbooks that exist:\n{catalog}"
    for a in alerts:
        seen_ids.update(a.evidence)
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    specs = tool_specs(use_runbooks)
    d = Diagnosis("UNKNOWN", alerts=[a.name for a in alerts], query=user, mode="llm+rag" if use_runbooks else "llm-no-rag")
    try:
        for _ in range(MAX_TURNS):
            msg = client.chat(messages, specs)
            messages.append({k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")})
            calls = msg.get("tool_calls") or []
            if not calls:
                final = _parse_final(msg.get("content") or "")
                d.label = final.get("runbook_id") or "UNKNOWN"
                d.evidence_ids = [int(i) for i in final.get("evidence_log_ids") or [] if str(i).isdigit()]
                d.note = f"model confidence: {final.get('confidence', '?')}; model root cause: {final.get('root_cause', '')}"
                break
            for c in calls:
                try:
                    args = json.loads(c["function"].get("arguments") or "{}")
                    out = call(c["function"]["name"], args)
                except Exception as e:  # noqa: BLE001 - a bad tool call is reported back to the model
                    out = f"tool error: {type(e).__name__}: {e}"
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(out, default=str)[:6000]})
        else:
            d.note = "no final answer within the turn limit"
    except (RuntimeError, ValueError, KeyError) as e:
        d.label, d.note = "UNKNOWN", f"llm error: {e}"
    # grounding: cited ids must also have been SEEN by the model through a tool, not guessed
    if d.label not in ("NONE", "UNKNOWN") and not set(d.evidence_ids) <= seen_ids:
        d.note = "rejected: cited log ids the tools never returned. " + d.note
        d.label = "UNKNOWN"
    d = finalize(d, t, retriever.runbooks)
    d.elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    return d
