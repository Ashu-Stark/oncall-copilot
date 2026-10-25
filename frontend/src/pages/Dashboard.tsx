import { useEffect, useState } from "react";
import { get } from "../api";
import { BarChart } from "../components/BarChart";
import { mins, pct } from "../format";

interface Stats {
  n: number;
  mean: number | null;
  median: number | null;
}

interface Mode {
  accuracy_all: number;
  accuracy_on_detected_incidents: number;
  wrong_root_cause: number;
  abstained_unknown: number;
  median_ms: number;
}

interface DashboardData {
  window_days: number;
  open_by_severity: Record<string, number>;
  open_total: number;
  total: number;
  demo_total: number;
  mtta_minutes: Stats;
  mttr_minutes: Stats;
  by_service: Record<string, number>;
  by_day: Record<string, number>;
  verdicts: Record<string, number>;
  simulated: { total: number; verdict_matches_ground_truth: number };
  eval: {
    scenarios: number;
    incidents: number;
    detection_rate: number;
    false_alarm_rate: number;
    recall_at_1: number;
    recall_at_3: number;
    modes: Record<string, Mode>;
  } | null;
}

export function Dashboard() {
  const [d, setD] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    get<DashboardData>("/dashboard").then(setD).catch((e) => setError(e.message));
  }, []);
  if (error) return <p className="error">{error}</p>;
  if (!d) return (
      <div aria-busy="true" aria-label="Loading">
        <div className="skeleton" style={{ height: 140 }} />
        <div className="skeleton" style={{ height: 320 }} />
      </div>
    );
  return (
    <div className="dashboard">
      <section className="hero">
        <h1>Dashboard</h1>
        <p>
          Last {d.window_days} days: {d.total} incidents
          {d.demo_total ? ` (${d.demo_total} are demo incidents with made-up response times)` : ""}.
        </p>
      </section>
      <div className="stats">
        <div className="stat">
          <b>{d.open_total}</b>
          <span>open incidents</span>
        </div>
        <div className="stat">
          <b>{mins(d.mtta_minutes.median)}</b>
          <span>median time to acknowledge (n={d.mtta_minutes.n})</span>
        </div>
        <div className="stat">
          <b>{mins(d.mttr_minutes.median)}</b>
          <span>median time to resolve (n={d.mttr_minutes.n})</span>
        </div>
        <div className="stat">
          <b>
            {d.simulated.verdict_matches_ground_truth}/{d.simulated.total}
          </b>
          <span>simulated incidents where the verdict matched the injected fault</span>
        </div>
      </div>
      <div className="dash-grid">
        <section className="card" aria-labelledby="sev-h">
          <h2 id="sev-h">Open by severity</h2>
          <BarChart data={d.open_by_severity} label="Open incidents by severity" />
        </section>
        <section className="card" aria-labelledby="svc-h">
          <h2 id="svc-h">Incidents by service</h2>
          <BarChart data={d.by_service} label="Incidents by service" />
        </section>
        <section className="card" aria-labelledby="ver-h">
          <h2 id="ver-h">Copilot verdicts</h2>
          <BarChart data={d.verdicts} label="Copilot verdicts" />
        </section>
        <section className="card" aria-labelledby="day-h">
          <h2 id="day-h">Incidents per day</h2>
          <BarChart data={d.by_day} label="Incidents per day" byValue={false} />
        </section>
      </div>
      {d.eval && (
        <section className="card eval" aria-labelledby="eval-h">
          <h2 id="eval-h">Offline evaluation (eval/run_eval.py)</h2>
          <p className="small">
            {d.eval.scenarios} scenarios on the real HOI API ({d.eval.incidents} injected incidents). Detection {pct(d.eval.detection_rate)} · false alarms{" "}
            {pct(d.eval.false_alarm_rate)} · retrieval recall@1 {pct(d.eval.recall_at_1)}, recall@3 {pct(d.eval.recall_at_3)}.
          </p>
          <div className="table-scroll">
            <table className="eval-table">
              <thead>
                <tr>
                  <th scope="col">Mode</th>
                  <th scope="col">Accuracy (all)</th>
                  <th scope="col">On detected incidents</th>
                  <th scope="col">Wrong root cause</th>
                  <th scope="col">Abstained</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(d.eval.modes).map(([m, v]) => (
                  <tr key={m} className={m === "full" ? "hl" : ""}>
                    <th scope="row">{m === "full" ? "full (the copilot)" : m}</th>
                    <td>{pct(v.accuracy_all)}</td>
                    <td>{pct(v.accuracy_on_detected_incidents)}</td>
                    <td>{v.wrong_root_cause}</td>
                    <td>{v.abstained_unknown}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="note small">Optimistic by construction: the same person wrote the faults, the alert rules and the runbook checks.</p>
        </section>
      )}
    </div>
  );
}
