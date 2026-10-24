"""Alert rules over the log store. An alert only says WHAT looks wrong; the copilot works out WHY.

Thresholds are assumptions for a small service (tens of requests per window), not tuned on production traffic.
"""

from __future__ import annotations

from dataclasses import dataclass

from .tools import Tools


@dataclass
class Alert:
    name: str
    summary: str
    evidence: list[int]


def evaluate(t: Tools) -> list[Alert]:
    out: list[Alert] = []
    s = t.status_summary()
    total = s.value["requests"]

    crit = t.search_logs("startup failed", level="CRITICAL")
    if crit.value["count"]:
        out.append(Alert("ServiceDown", "service process failed to start; no requests are being served", crit.evidence))

    if total >= 5 and s.value["share_5xx"] >= 0.10:
        out.append(Alert("HighErrorRate", f"{s.value['share_5xx']:.0%} of {total} requests returned 5xx", s.evidence))

    ready = t.search_logs("readiness check failed")
    if ready.value["count"]:
        out.append(Alert("ReadinessFailing", f"readiness probe failed {ready.value['count']} times", ready.evidence))

    lat = t.latency()
    if lat.value["n"] >= 5 and lat.value["p95_ms"] >= 400:
        out.append(Alert("HighLatency", f"p95 latency {lat.value['p95_ms']:.0f} ms over {lat.value['n']} requests", lat.evidence))

    a401 = t.status_count(401)
    if a401.value["count"] >= 8 and a401.value["share"] >= 0.25:
        out.append(Alert("AuthFailureSpike", f"{a401.value['count']} requests got 401 ({a401.value['share']:.0%})", a401.evidence))

    a429 = t.status_count(429)
    if a429.value["count"] >= 3:
        out.append(Alert("RateLimitSpike", f"{a429.value['count']} requests got 429", a429.evidence))

    # the LLM could not be used at all (call failed / not configured) or kept producing unusable output;
    # single rejections by the grounding checks are normal and are not counted
    fb = t.search_logs("concierge fallback to rules: llm call failed")
    fb_cfg = t.search_logs("concierge fallback to rules: set ")
    fb_schema = t.search_logs("llm reply rejected: invalid JSON")
    n_fb = fb.value["count"] + fb_cfg.value["count"] + fb_schema.value["count"]
    if n_fb >= 3:
        ev = (fb.evidence + fb_cfg.evidence + fb_schema.evidence)[:10]
        out.append(Alert("AiFallbackSpike", f"guest concierge could not use the LLM {n_fb} times and answered from rules", ev))

    dep = t.search_logs("portal places")
    dep2 = t.search_logs("places lookup failed")
    n_dep = dep.value["count"] + dep2.value["count"]
    if n_dep >= 3:
        out.append(Alert("DependencyErrors", f"{n_dep} failed calls to the tourism portal", (dep.evidence + dep2.evidence)[:10]))
    return out
