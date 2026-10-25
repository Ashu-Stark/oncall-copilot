import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { get, post } from "../api";

interface Fault {
  name: string;
  description: string;
  expected: string;
}

interface SimResult {
  incident_id: number | null;
  message: string;
  alerts: { name: string; summary: string }[];
  log_lines: number;
}

export function SimulatePanel({ onCreated }: { onCreated?: () => void }) {
  const [faults, setFaults] = useState<Fault[] | null>(null);
  const [available, setAvailable] = useState(true);
  const [fault, setFault] = useState("db_down");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<SimResult | null>(null);
  const [error, setError] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    get<{ available: boolean; faults: Fault[] }>("/simulator")
      .then((r) => {
        setAvailable(r.available);
        setFaults(r.faults);
        // keep the default only if this server offers it
        setFault((f) => (r.faults.some((x) => x.name === f) ? f : (r.faults[0]?.name ?? "")));
      })
      .catch(() => setAvailable(false));
  }, []);

  const run = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const r = await post<SimResult>("/simulator/run", { fault, seed: Math.floor(Math.random() * 1000) });
      setResult(r);
      onCreated?.();
      if (r.incident_id) navigate(`/incidents/${r.incident_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "simulation failed");
    } finally {
      setBusy(false);
    }
  };

  const chosen = faults?.find((f) => f.name === fault);
  return (
    <section className="card simulate" aria-labelledby="sim-h">
      <h2 id="sim-h">Simulate an incident</h2>
      {!available ? (
        <p className="muted">The simulator needs the HOI platform code next to this repo; alerts can still be posted to the API.</p>
      ) : (
        <form onSubmit={run}>
          <p className="muted small">
            Boots the real HOI hotel API in-process, injects a fault, sends traffic and files whatever alert rules fire.
          </p>
          <label htmlFor="fault">Fault to inject</label>
          <select id="fault" value={fault} onChange={(e) => setFault(e.target.value)} disabled={!faults}>
            {faults?.map((f) => (
              <option key={f.name} value={f.name}>
                {f.name}
              </option>
            ))}
          </select>
          {chosen && (
            <p className="fault-desc">
              {chosen.description} <span className="muted">(ground truth: {chosen.expected})</span>
            </p>
          )}
          <button type="submit" disabled={busy || !faults}>
            {busy ? "Injecting fault and sending traffic…" : "Inject fault"}
          </button>
          {busy && <p role="status" className="muted small">This takes a few seconds: HOI boots, serves ~60 requests, then the alert rules run.</p>}
          {result && !result.incident_id && (
            <p role="status" className="sim-result">
              {result.message} ({result.log_lines} log lines checked).
            </p>
          )}
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
        </form>
      )}
    </section>
  );
}
