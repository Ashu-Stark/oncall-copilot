"""Request IDs, one JSON log line per request, and per-route latency/status counters for /metrics."""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
import uuid
from collections import Counter, defaultdict, deque

from fastapi import Request

log = logging.getLogger("oncall.access")


def setup_logging() -> None:
    """The app's loggers write to stdout and do NOT propagate to the root logger: during a simulation the HOI harness
    captures root-logger records as the incident's log window, and this app's own lines must not end up in it."""
    root = logging.getLogger("oncall")
    if not root.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        root.addHandler(h)
    root.setLevel(logging.INFO)
    root.propagate = False


class Metrics:
    def __init__(self):
        self._lock = threading.Lock()
        self.status: Counter = Counter()
        self.lat: dict[str, deque] = defaultdict(lambda: deque(maxlen=500))

    def record(self, route: str, status: int, ms: float) -> None:
        with self._lock:
            self.status[f"{route} {status}"] += 1
            self.lat[route].append(ms)

    def snapshot(self) -> dict:
        def pct(xs: list[float], q: float) -> float:
            s = sorted(xs)
            return round(s[min(len(s) - 1, int(q * (len(s) - 1) + 0.5))], 1) if s else 0.0

        with self._lock:
            return {
                "requests": dict(self.status),
                "latency_ms": {r: {"p50": pct(list(v), 0.5), "p95": pct(list(v), 0.95), "n": len(v)} for r, v in self.lat.items()},
            }


metrics = Metrics()


async def middleware(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    t0 = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - t0) * 1000
    route = getattr(request.scope.get("route"), "path", "unmatched")
    if not route.endswith("/stream"):  # streams stay open; their duration is not a latency
        metrics.record(f"{request.method} {route}", response.status_code, ms)
    response.headers["X-Request-ID"] = rid
    log.info(json.dumps({"rid": rid, "method": request.method, "route": route, "status": response.status_code, "ms": round(ms, 1)}))
    return response
