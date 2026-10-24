"""Inject one fault into the real HOI platform API and print the copilot's incident note.

    python demo.py db_down
    python demo.py jwt_secret_rotated --llm      # LLM investigator (needs LLM_API_KEY or GROQ_API_KEY)
    python demo.py --list
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness.faults import FAULTS, run_scenario  # noqa: E402  (first: puts HOI on sys.path)

from copilot.agent import investigate, render  # noqa: E402
from copilot.retrieval import HybridRetriever  # noqa: E402
from copilot.runbooks import load  # noqa: E402
from copilot.tools import Tools  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("fault", nargs="?", default="db_down", help="fault name, or 'healthy'")
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    if a.list:
        for f in FAULTS.values():
            print(f"{f.name:<26} -> {f.label}")
        return
    logging.disable(logging.CRITICAL)  # keep HOI's own console logs out of the demo (they are still captured)
    retriever = HybridRetriever(load())

    def look(env):
        logging.disable(logging.NOTSET)
        t = Tools(env.store, env.health)
        if a.llm:
            from copilot.llm_agent import investigate_llm

            return investigate_llm(t, retriever)
        return investigate(t, retriever)

    logging.disable(logging.NOTSET)
    root = logging.getLogger()
    for h in list(root.handlers):
        if isinstance(h, logging.StreamHandler) and not hasattr(h, "store"):
            root.removeHandler(h)
    _, d = run_scenario(None if a.fault == "healthy" else a.fault, a.seed, investigate=look)
    print(f"\n## Incident note ({d.mode}, {d.elapsed_ms:.0f} ms)\n")
    print(render(d))


if __name__ == "__main__":
    main()
