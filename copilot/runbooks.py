"""Runbooks: markdown files with a title, sections and a machine-checkable ```checks``` block.

A runbook is split into chunks (one per section) for retrieval; the checks block is what the investigator runs
against the logs to confirm or reject the runbook's root cause.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

RUNBOOK_DIR = Path(__file__).resolve().parent.parent / "runbooks"
_TITLE = re.compile(r"^#\s+(RB\d+)\s+·\s+(.+)$", re.M)
_META = re.compile(r"\*\*Severity:\*\*\s*([^·]+)·\s*\*\*Root cause:\*\*\s*(.+)$", re.M)
_SECTION = re.compile(r"^##\s+(.+)$", re.M)
_CHECKS = re.compile(r"```checks\s*(.+?)```", re.S)


@dataclass
class Chunk:
    runbook_id: str
    section: str
    text: str

    @property
    def ref(self) -> str:
        return f"{self.runbook_id}#{self.section.lower().replace(' ', '-')}"


@dataclass
class Runbook:
    id: str
    title: str
    severity: str
    root_cause: str
    sections: dict[str, str]
    checks: list[dict]
    path: Path
    chunks: list[Chunk] = field(default_factory=list)

    def steps(self) -> list[str]:
        """Diagnosis then mitigation steps, as lines."""
        out = []
        for name in ("Diagnosis", "Mitigation"):
            for line in self.sections.get(name, "").splitlines():
                line = line.strip()
                if line:
                    out.append(f"[{name}] " + re.sub(r"^(\d+\.|-)\s*", "", line))
        return out


def parse(path: Path) -> Runbook:
    text = path.read_text(encoding="utf-8")
    m = _TITLE.search(text)
    if not m:
        raise ValueError(f"{path.name}: first line must be '# RBnn · Title'")
    rb_id, title = m.group(1), m.group(2).strip()
    meta = _META.search(text)
    severity, root = (meta.group(1).strip(), meta.group(2).strip()) if meta else ("", "")
    cm = _CHECKS.search(text)
    checks = json.loads(cm.group(1)) if cm else []
    heads = list(_SECTION.finditer(text))
    sections: dict[str, str] = {}
    for i, h in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[h.end() : end]
        body = _CHECKS.sub("", body).strip()
        sections[h.group(1).strip()] = body
    rb = Runbook(rb_id, title, severity, root, sections, checks, path)
    # chunk 0 is the header (title + root cause): short and very informative; the rest are the prose sections
    rb.chunks.append(Chunk(rb_id, "Summary", f"{title}. {root}"))
    for name, body in sections.items():
        if name != "Checks" and body:
            rb.chunks.append(Chunk(rb_id, name, f"{title}. {body}"))
    return rb


def load(directory: Path = RUNBOOK_DIR) -> dict[str, Runbook]:
    books = [parse(p) for p in sorted(directory.glob("RB*.md"))]
    return {b.id: b for b in books}
