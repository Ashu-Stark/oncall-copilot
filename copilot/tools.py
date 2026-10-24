"""Read-only investigation tools over the log store (and an optional health probe).

The copilot can only look: no tool restarts, rolls back or changes anything. Every tool returns plain data plus the
ids of the log rows it used, so a diagnosis can cite them.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from .logstore import LogStore, template


@dataclass
class ToolResult:
    value: object
    evidence: list[int] = field(default_factory=list)


def _pct(values: list[int], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = min(len(s) - 1, max(0, round(q * (len(s) - 1))))
    return float(s[k])


class Tools:
    def __init__(self, store: LogStore, health: Callable[[], dict] | None = None):
        self.store = store
        self._health = health

    # -- requests
    def status_summary(self) -> ToolResult:
        rows = self.store.rows("status IS NOT NULL")
        by_class = Counter(f"{r.status // 100}xx" for r in rows)
        by_status = Counter(r.status for r in rows)
        total = len(rows)
        return ToolResult(
            {
                "requests": total,
                "by_class": dict(by_class),
                "by_status": {str(k): v for k, v in sorted(by_status.items())},
                "share_5xx": round(by_class.get("5xx", 0) / total, 3) if total else 0.0,
            },
            [r.id for r in rows if r.status >= 500][:10],
        )

    def status_count(self, status: int | str, path_prefix: str | None = None) -> ToolResult:
        """status: exact (401) or class ('5xx'). Optional path prefix, e.g. '/auth/login'."""
        if isinstance(status, str) and status.endswith("xx"):
            lo = int(status[0]) * 100
            where, params = "status >= ? AND status < ?", [lo, lo + 100]
        else:
            where, params = "status = ?", [int(status)]
        if path_prefix:
            where += " AND path LIKE ?"
            params.append(path_prefix + "%")
        rows = self.store.rows(where, tuple(params))
        total = len(self.store.rows("status IS NOT NULL"))
        return ToolResult({"count": len(rows), "share": round(len(rows) / total, 3) if total else 0.0}, [r.id for r in rows][:10])

    def latency(self) -> ToolResult:
        rows = self.store.rows("ms IS NOT NULL AND path NOT LIKE '/ready%' AND path NOT LIKE '/health%'")
        ms = [r.ms for r in rows]
        slow = sorted(rows, key=lambda r: -r.ms)[:5]
        return ToolResult({"p50_ms": _pct(ms, 0.5), "p95_ms": _pct(ms, 0.95), "max_ms": max(ms, default=0), "n": len(ms)}, [r.id for r in slow])

    def latency_trend(self) -> ToolResult:
        """p95 of the first and the last third of requests: separates a one-off slow start from sustained slowness."""
        rows = self.store.rows("ms IS NOT NULL AND path NOT LIKE '/ready%' AND path NOT LIKE '/health%'")
        if len(rows) < 6:
            return ToolResult({"first_p95_ms": 0.0, "last_p95_ms": 0.0, "slow_only_at_start": False})
        third = len(rows) // 3
        first, last = [r.ms for r in rows[:third]], [r.ms for r in rows[-third:]]
        f95, l95 = _pct(first, 0.95), _pct(last, 0.95)
        return ToolResult({"first_p95_ms": f95, "last_p95_ms": l95, "slow_only_at_start": f95 > 3 * max(l95, 1)}, [rows[0].id, rows[-1].id])

    def distinct_clients_401(self, path_prefix: str | None = None) -> ToolResult:
        """How spread out the 401s are: many paths/users (secret rotated) vs one login endpoint (password guessing)."""
        rows = self.store.rows("status = 401")
        paths = Counter((r.path or "").split("?")[0] for r in rows)
        login = sum(v for k, v in paths.items() if k.startswith("/auth/login"))
        return ToolResult({"total": len(rows), "on_login": login, "elsewhere": len(rows) - login, "paths": dict(paths.most_common(5))}, [r.id for r in rows][:10])

    # -- messages
    def search_logs(self, pattern: str, level: str | None = None, limit: int = 20) -> ToolResult:
        where, params = "(message LIKE ? OR exc LIKE ?)", ["%" + pattern + "%", "%" + pattern + "%"]
        if level:
            where += " AND level = ?"
            params.append(level.upper())
        rows = self.store.rows(where, tuple(params), limit=10_000)
        return ToolResult({"count": len(rows), "lines": [r.short() for r in rows[:limit]]}, [r.id for r in rows][:10])

    def top_errors(self, k: int = 5) -> ToolResult:
        """Most frequent WARNING+ message templates, with the exception's last line when there is one."""
        rows = self.store.rows("level IN ('WARNING','ERROR','CRITICAL')")
        groups: dict[str, list[int]] = {}
        for r in rows:
            key = template(r.message)
            if r.exc:
                key += " | " + r.exc.strip().splitlines()[-1]
            groups.setdefault(key, []).append(r.id)
        top = sorted(groups.items(), key=lambda kv: -len(kv[1]))[:k]
        return ToolResult([{"template": t, "count": len(ids)} for t, ids in top], [ids[0] for _, ids in top])

    def health(self) -> ToolResult:
        if self._health is None:
            return ToolResult({"available": False})
        try:
            return ToolResult({"available": True, **self._health()})
        except Exception as e:  # noqa: BLE001 - a dead service is a finding, not a crash
            return ToolResult({"available": True, "ready": False, "error": type(e).__name__})
