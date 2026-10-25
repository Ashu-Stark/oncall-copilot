"""The fault simulator against the real HOI platform API (skipped when HOI is not checked out next to this repo).

The key property: an incident investigated by the web app (logs stored in Postgres, replayed into the copilot's log
store, health probe replayed) gets the SAME diagnosis as the copilot investigating the live HOI instance directly."""

from __future__ import annotations

import pytest

from backend.app import simulator

pytestmark = pytest.mark.skipif(not simulator.available(), reason="HOI platform not found (set HOI_PLATFORM_PATH)")


def test_simulated_db_outage_opens_an_incident_with_the_right_verdict(client, eng):
    r = client.post("/api/simulator/run", json={"fault": "db_down", "seed": 7}, headers=eng)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["incident_id"] and out["expected"] == "RB01" and out["log_lines"] > 50
    inv = client.get(f"/api/investigations/{out['investigation_id']}", headers=eng).json()
    assert inv["label"] == "RB01"
    inc = client.get(f"/api/incidents/{out['incident_id']}", headers=eng).json()
    assert inc["expected_label"] == "RB01" and inc["simulated_fault"] == "db_down" and inc["severity"] == "SEV1"


def test_fault_without_user_impact_pages_nobody(client, eng):
    out = client.post("/api/simulator/run", json={"fault": "portal_down", "seed": 7}, headers=eng).json()
    assert out["incident_id"] is None and out["alerts"] == [] and "nobody is paged" in out["message"]


def test_unknown_fault_is_rejected(client, eng):
    assert client.post("/api/simulator/run", json={"fault": "meteor_strike"}, headers=eng).status_code == 422


@pytest.mark.parametrize("fault", ["db_down", "db_slow", "llm_rate_limited", "llm_key_missing", "llm_schema_drift", "jwt_secret_rotated", "password_guessing", "unsafe_prod_config", "rate_limit_misconfigured"])
def test_replayed_investigation_matches_the_live_one(fault):
    from copilot.agent import investigate
    from copilot.logstore import LogStore
    from copilot.retrieval import HybridRetriever
    from copilot.runbooks import load
    from copilot.tools import Tools
    from harness.faults import run_scenario

    from backend.app.investigations import replay_health

    retriever = HybridRetriever(load())

    def both(env):
        rows = env.store.rows("1=1", limit=1_000_000)
        try:
            health = env.health()
        except Exception as e:  # noqa: BLE001
            health = {"error": type(e).__name__}
        live = investigate(Tools(env.store, env.health), retriever)
        store = LogStore()
        for row in rows:
            store.add(row.level, row.logger, row.message, row.exc, row.ts)
        replayed = investigate(Tools(store, replay_health(health)), retriever)
        return live, replayed

    _, (live, replayed) = run_scenario(fault, 7, {"attempts": 25} if fault == "password_guessing" else {}, investigate=both)
    assert replayed.label == live.label
    assert replayed.evidence_ids == live.evidence_ids
