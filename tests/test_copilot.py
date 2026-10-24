"""Unit tests that need no HOI instance: log parsing, BM25, runbook parsing, checks, the grounding gate."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from copilot.agent import Diagnosis, finalize, investigate, run_check  # noqa: E402
from copilot.logstore import LogStore, template  # noqa: E402
from copilot.retrieval import BM25, HybridRetriever, tokens  # noqa: E402
from copilot.runbooks import load  # noqa: E402
from copilot.tools import Tools  # noqa: E402

RUNBOOKS = load()
RETRIEVER = HybridRetriever(RUNBOOKS)


def store_with(lines):
    s = LogStore()
    for level, msg, *exc in lines:
        s.add(level, "hoi.platform", msg, exc[0] if exc else None)
    return s


def test_access_line_is_parsed_into_columns():
    s = store_with([("INFO", "rid=abc123 GET /rooms -> 503 41ms")])
    (r,) = s.rows()
    assert (r.status, r.ms, r.path) == (503, 41, "/rooms")


def test_template_hides_ids_and_tokens():
    assert template("rid=9f POST /public/guest/Xy_12/chat -> 429 3ms") == "rid=<rid> POST /public/guest/<token>/chat -> 429 <ms>ms"


def test_tokens_split_camel_case_error_names():
    t = tokens("ServerSelectionTimeoutError")
    assert {"serverselectiontimeouterror", "server", "selection", "timeout", "error"} <= set(t)


def test_bm25_prefers_rare_matching_terms():
    bm = BM25([["database", "timeout"], ["login", "password"], ["database", "slow"]])
    s = bm.scores(["timeout"])
    assert s.argmax() == 0 and s[1] == 0


def test_every_runbook_parses_with_checks_and_steps():
    assert len(RUNBOOKS) == 16
    for rb in RUNBOOKS.values():
        assert rb.checks, rb.id
        assert rb.root_cause and rb.severity, rb.id
        assert rb.steps(), rb.id


def test_retrieval_finds_the_database_runbook_for_a_db_error():
    hits = RETRIEVER.search("HighErrorRate | unhandled error | pymongo.errors.ServerSelectionTimeoutError: timed out", 3)
    assert hits[0].runbook_id == "RB01"


def test_check_passes_and_fails_on_real_numbers():
    s = store_with([("INFO", f"rid=r{i} GET /rooms -> 500 5ms") for i in range(6)] + [("INFO", "rid=ok GET /rooms -> 200 5ms")])
    t = Tools(s)
    assert run_check(t, {"tool": "status_count", "args": {"status": "5xx"}, "field": "share", "op": ">=", "value": 0.5}).passed
    assert not run_check(t, {"tool": "status_count", "args": {"status": 401}, "field": "count", "op": ">=", "value": 1}).passed


def test_quiet_logs_mean_no_incident():
    s = store_with([("INFO", f"rid=r{i} GET /rooms -> 200 5ms") for i in range(30)])
    assert investigate(Tools(s), RETRIEVER).label == "NONE"


def test_db_outage_is_diagnosed_with_cited_evidence():
    exc = "Traceback...\npymongo.errors.ServerSelectionTimeoutError: db:27017: timed out"
    lines = [("ERROR", f"unhandled error rid=r{i} GET /rooms", exc) for i in range(5)]
    lines += [("INFO", f"rid=r{i} GET /rooms -> 500 4ms") for i in range(5)]
    lines += [("WARNING", "readiness check failed: database ping did not succeed")]
    d = investigate(Tools(store_with(lines), health=lambda: {"ready": False}), RETRIEVER)
    assert d.label == "RB01"
    assert d.evidence and all(e.startswith("#") for e in d.evidence)


def test_alerts_that_no_runbook_explains_give_unknown_not_a_guess():
    lines = [("INFO", f"rid=r{i} GET /rooms -> 500 4ms") for i in range(8)]  # 5xx with no recognisable cause
    d = investigate(Tools(store_with(lines), health=lambda: {"ready": True}), RETRIEVER)
    assert d.label == "UNKNOWN"


def test_grounding_gate_rejects_made_up_log_ids():
    s = store_with([("INFO", "rid=a GET /rooms -> 500 4ms")])
    d = finalize(Diagnosis("RB01", evidence_ids=[999]), Tools(s), RUNBOOKS)
    assert d.label == "UNKNOWN" and "do not exist" in d.note
