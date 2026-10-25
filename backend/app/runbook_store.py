"""Runbooks in Postgres: validation of the markdown + checks DSL, version history, and the retriever built from them.

The copilot's own parser (`copilot.runbooks.parse_text`) is used, so a runbook that saves here is exactly what the
investigator will read.
"""

from __future__ import annotations

import inspect
import json
import re
import threading
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from copilot.agent import OPS
from copilot.retrieval import HybridRetriever
from copilot.runbooks import RUNBOOK_DIR, Runbook as CopilotRunbook, parse_text
from copilot.tools import Tools

from .models import Runbook, RunbookVersion, now

TOOLS = {n: f for n, f in inspect.getmembers(Tools, inspect.isfunction) if not n.startswith("_")}
_ID = re.compile(r"^RB\d{2,3}$")
_CHECKS_START = re.compile(r"```checks\s*\n?")
_SERVICE = re.compile(r"\*\*Service:\*\*\s*([^·*]+)")


def validate(markdown: str, expected_id: str | None = None) -> tuple[list[dict], CopilotRunbook | None]:
    """Returns (errors, parsed runbook). Each error: {"line": int | None, "message": str}."""
    errs: list[dict] = []

    def err(msg: str, line: int | None = None) -> None:
        errs.append({"line": line, "message": msg})

    if len(markdown) > 50_000:
        return [{"line": None, "message": "runbook is longer than 50,000 characters"}], None
    try:
        rb = parse_text(markdown, Path("editor.md"))
    except json.JSONDecodeError as e:  # before ValueError: it is a subclass
        m = _CHECKS_START.search(markdown)
        base = markdown[: m.end()].count("\n") if m else 0
        return [{"line": base + e.lineno, "message": f"checks block is not valid JSON: {e.msg}"}], None
    except ValueError:
        return [{"line": 1, "message": "the first line must be '# RBnn · Title' (for example '# RB17 · Queue backlog')"}], None

    if not _ID.match(rb.id):
        err("runbook id must look like RB17", 1)
    if expected_id and rb.id != expected_id:
        err(f"the title says {rb.id} but this is {expected_id}; ids cannot be changed", 1)
    if not rb.severity or not rb.root_cause:
        err("add a line '**Service:** … · **Severity:** SEVn · **Root cause:** …'", 2)
    elif not re.search(r"SEV[1-4]", rb.severity):
        err("severity must contain SEV1, SEV2, SEV3 or SEV4", 2)
    for section in ("Symptoms", "Diagnosis", "Mitigation"):
        if not rb.sections.get(section):
            err(f"missing or empty section '## {section}'")

    m = _CHECKS_START.search(markdown)
    first = markdown[: m.end()].count("\n") + 1 if m else None
    if not m:
        err("add a ```checks block: the investigator confirms a runbook only when its checks pass on the logs")
    elif not isinstance(rb.checks, list) or not rb.checks:
        err("the checks block must be a non-empty JSON list", first)
    else:
        for i, c in enumerate(rb.checks, 1):
            where = f"check {i}: "
            if not isinstance(c, dict):
                err(where + "must be an object", first)
                continue
            unknown = set(c) - {"tool", "args", "field", "op", "value"}
            if unknown:
                err(where + f"unknown keys {sorted(unknown)}", first)
            tool = c.get("tool")
            if tool not in TOOLS:
                err(where + f"unknown tool '{tool}'; available: {', '.join(sorted(TOOLS))}", first)
            else:
                args = c.get("args", {})
                if not isinstance(args, dict):
                    err(where + "args must be an object", first)
                else:
                    try:
                        inspect.signature(TOOLS[tool]).bind(None, **args)
                    except TypeError as e:
                        err(where + f"bad args for {tool}: {e}", first)
            if c.get("op") not in OPS:
                err(where + f"op must be one of {', '.join(OPS)}", first)
            if "value" not in c:
                err(where + "missing 'value'", first)
            elif not isinstance(c["value"], (int, float, bool, str)):
                err(where + "value must be a number, true/false or a string", first)
            if "field" in c and not isinstance(c["field"], str):
                err(where + "field must be a string", first)
    return errs, (rb if not errs else None)


def service_of(markdown: str) -> str:
    m = _SERVICE.search(markdown)
    return m.group(1).strip() if m else ""


def save(s: Session, markdown: str, user: str, comment: str = "", expected_id: str | None = None) -> Runbook:
    """Create or update (caller has validated). Every save is a new version; old versions are kept."""
    _, rb = validate(markdown, expected_id)
    assert rb is not None
    row = s.get(Runbook, rb.id, with_for_update=True)
    if row is None:
        row = Runbook(id=rb.id, version=0, markdown="")
        s.add(row)
    row.version += 1
    row.title, row.severity, row.markdown = rb.title, rb.severity, markdown
    row.service = service_of(markdown)
    row.updated_at, row.updated_by = now(), user
    s.add(RunbookVersion(runbook_id=rb.id, version=row.version, markdown=markdown, edited_by=user, comment=comment[:200]))
    s.flush()
    invalidate()
    return row


def seed_from_files(s: Session) -> int:
    """Load runbooks/*.md into an empty library."""
    if s.scalar(select(func.count()).select_from(Runbook)):
        return 0
    n = 0
    for p in sorted(Path(RUNBOOK_DIR).glob("RB*.md")):
        save(s, p.read_text(encoding="utf-8"), "seed", f"imported from runbooks/{p.name}")
        n += 1
    return n


# ---------------------------------------------------------------- retriever cache
_cache: dict = {"key": None, "retriever": None, "versions": {}}
_lock = threading.Lock()


def invalidate() -> None:
    with _lock:
        _cache["key"] = None


def retriever(s: Session) -> tuple[HybridRetriever, dict[str, int]]:
    """The hybrid retriever over the current library, rebuilt only when a runbook changed."""
    key = tuple(s.execute(select(Runbook.id, Runbook.version).order_by(Runbook.id)).all())
    with _lock:
        if _cache["key"] == key and _cache["retriever"] is not None:
            return _cache["retriever"], _cache["versions"]
    rows = s.scalars(select(Runbook).order_by(Runbook.id)).all()
    books = {r.id: parse_text(r.markdown, Path(f"{r.id}.md")) for r in rows}
    built = HybridRetriever(books)
    versions = {r.id: r.version for r in rows}
    with _lock:
        _cache.update(key=key, retriever=built, versions=versions)
    return built, versions
