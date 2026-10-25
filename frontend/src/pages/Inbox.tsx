import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { get, type Incident } from "../api";
import { SeverityBadge, StatusBadge, VerdictBadge } from "../components/Badges";
import { SimulatePanel } from "../components/SimulatePanel";
import { ago } from "../format";

export function Inbox() {
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "open";
  const severity = params.get("severity") ?? "";
  const q = params.get("q") ?? "";
  const [data, setData] = useState<{ items: Incident[]; total: number } | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    const qs = new URLSearchParams({ status, ...(severity ? { severity } : {}), ...(q ? { q } : {}) });
    get<{ items: Incident[]; total: number }>(`/incidents?${qs}`)
      .then((d) => {
        setData(d);
        setError("");
      })
      .catch((e) => setError(e.message));
  }, [status, severity, q]);

  useEffect(() => {
    load();
    const t = setInterval(load, 10_000); // new alerts appear without a reload
    return () => clearInterval(t);
  }, [load]);

  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    setParams(next, { replace: true });
  };

  return (
    <div className="inbox">
      <section className="hero">
        <h1>Incidents</h1>
        <p>Alerts from monitoring become incidents. The copilot investigates each one from its logs and cites the evidence.</p>
      </section>
      <div className="inbox-grid">
        <section aria-labelledby="list-h">
          <h2 id="list-h" className="visually-hidden">
            Incident list
          </h2>
          <div className="filters" role="group" aria-label="Filters">
            <div className="seg" role="radiogroup" aria-label="Status">
              {["open", "resolved", "all"].map((s) => (
                <button key={s} type="button" role="radio" aria-checked={status === s} className={status === s ? "on" : ""} onClick={() => set("status", s === "open" ? "" : s)}>
                  {s}
                </button>
              ))}
            </div>
            <label className="visually-hidden" htmlFor="sev">
              Severity
            </label>
            <select id="sev" value={severity} onChange={(e) => set("severity", e.target.value)}>
              <option value="">All severities</option>
              {["SEV1", "SEV2", "SEV3", "SEV4"].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
            <label className="visually-hidden" htmlFor="q">
              Search
            </label>
            <input id="q" type="search" placeholder="Search titles and resolutions" defaultValue={q} onKeyDown={(e) => e.key === "Enter" && set("q", e.currentTarget.value)} />
          </div>
          {error && <p className="error">{error}</p>}
          {!data && !error && (
            <div aria-busy="true" aria-label="Loading incidents">
              <div className="skeleton" />
              <div className="skeleton" />
              <div className="skeleton" />
            </div>
          )}
          {data && data.items.length === 0 && (
            <div className="empty card">
              <span className="empty-icon" aria-hidden="true">
                ✅
              </span>
              <p>
                <strong>No {status === "all" ? "" : status} incidents.</strong>
              </p>
              <p className="muted">All quiet. Inject a fault to watch the copilot investigate one.</p>
            </div>
          )}
          <ul className="incidents">
            {data?.items.map((i) => (
              <li key={i.id} className={`incident-card sev-border-${i.severity.toLowerCase()}`}>
                <Link to={`/incidents/${i.id}`} className="incident-link">
                  <div className="row1">
                    <SeverityBadge sev={i.severity} short />
                    <StatusBadge status={i.status} />
                    <VerdictBadge label={i.verdict?.label ?? null} status={i.verdict?.status} />
                    {i.is_demo && <span className="badge demo">demo</span>}
                    <span className="when">{ago(i.created_at)}</span>
                  </div>
                  <p className="title">
                    #{i.id} {i.title}
                  </p>
                  <p className="meta">
                    {i.service} · {i.alert_count} alert{i.alert_count === 1 ? "" : "s"}
                    {i.assignee ? ` · ${i.assignee.name}` : " · unassigned"}
                  </p>
                </Link>
              </li>
            ))}
          </ul>
          {data && data.total > data.items.length && <p className="muted">Showing {data.items.length} of {data.total}.</p>}
        </section>
        <aside>
          <SimulatePanel onCreated={load} />
        </aside>
      </div>
    </div>
  );
}
