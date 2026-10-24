"""SQLite log store: captures Python log records from the service under test and makes them queryable.

HOI's platform API already writes one access line per request:
    rid=3f2a9c1d0b7e POST /auth/login -> 401 212ms
so request fields (rid, method, path, status, latency) are parsed out of that line into columns.
Every row keeps its integer id; the copilot cites evidence by these ids.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
import time
from dataclasses import dataclass

ACCESS = re.compile(r"^rid=(?P<rid>\S+) (?P<method>[A-Z]+) (?P<path>\S+) -> (?P<status>\d{3}) (?P<ms>\d+)ms$")
# ids, tokens and numbers vary between log lines; templates group lines that are "the same message"
_VARIABLE = [
    (re.compile(r"rid=\S+"), "rid=<rid>"),
    (re.compile(r"/public/guest/[^/\s]+"), "/public/guest/<token>"),
    (re.compile(r"/(jobs|rooms|photos|requests|pos|counts)/[^/\s]+"), r"/\1/<id>"),
    (re.compile(r"\b\d+(\.\d+)?ms\b"), "<ms>ms"),
    (re.compile(r"key #\d+"), "key #<n>"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    level TEXT NOT NULL,
    logger TEXT NOT NULL,
    message TEXT NOT NULL,
    exc TEXT,
    rid TEXT, method TEXT, path TEXT, status INTEGER, ms INTEGER
);
CREATE INDEX IF NOT EXISTS ix_logs_ts ON logs(ts);
CREATE INDEX IF NOT EXISTS ix_logs_status ON logs(status);
"""


def template(message: str) -> str:
    for rx, rep in _VARIABLE:
        message = rx.sub(rep, message)
    return message


@dataclass
class LogRow:
    id: int
    ts: float
    level: str
    logger: str
    message: str
    exc: str | None
    status: int | None
    ms: int | None
    path: str | None

    def short(self) -> str:
        exc = f" | {self.exc.strip().splitlines()[-1]}" if self.exc else ""
        return f"#{self.id} {self.level} {self.logger}: {self.message}{exc}"


class LogStore:
    def __init__(self, path: str = ":memory:"):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()

    def add(self, level: str, logger: str, message: str, exc: str | None = None, ts: float | None = None) -> int:
        m = ACCESS.match(message)
        f = m.groupdict() if m else {}
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO logs (ts, level, logger, message, exc, rid, method, path, status, ms) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    time.time() if ts is None else ts,
                    level,
                    logger,
                    message,
                    exc,
                    f.get("rid"),
                    f.get("method"),
                    f.get("path"),
                    int(f["status"]) if f else None,
                    int(f["ms"]) if f else None,
                ),
            )
            self._db.commit()
            return cur.lastrowid

    def rows(self, sql_where: str = "1=1", params: tuple = (), limit: int = 10_000) -> list[LogRow]:
        with self._lock:
            cur = self._db.execute(
                f"SELECT id, ts, level, logger, message, exc, status, ms, path FROM logs WHERE {sql_where} ORDER BY id LIMIT ?",
                (*params, limit),
            )
            return [LogRow(*r) for r in cur.fetchall()]

    def get(self, ids: list[int]) -> list[LogRow]:
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        return self.rows(f"id IN ({marks})", tuple(ids))

    def clear(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM logs")
            self._db.commit()

    def handler(self) -> logging.Handler:
        return _StoreHandler(self)


class _StoreHandler(logging.Handler):
    def __init__(self, store: LogStore):
        super().__init__(level=logging.INFO)
        self.store = store
        self._fmt = logging.Formatter()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            exc = self._fmt.formatException(record.exc_info) if record.exc_info else None
            self.store.add(record.levelname, record.name, record.getMessage(), exc, record.created)
        except Exception:  # noqa: BLE001 - logging must never break the service
            self.handleError(record)
