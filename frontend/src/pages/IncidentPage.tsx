import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { get, patch, type Incident, type Status, type TimelineEvent, type User } from "../api";
import { SeverityBadge, StatusBadge } from "../components/Badges";
import { InvestigationPanel } from "../components/InvestigationPanel";
import { Timeline } from "../components/Timeline";
import { dateTime, mins } from "../format";

const NEXT: Record<Status, { to: Status; label: string }[]> = {
  triggered: [
    { to: "acknowledged", label: "Acknowledge" },
    { to: "resolved", label: "Resolve (false alarm)" },
  ],
  acknowledged: [
    { to: "investigating", label: "Start investigating" },
    { to: "resolved", label: "Resolve" },
  ],
  investigating: [{ to: "resolved", label: "Resolve" }],
  resolved: [],
};

function minutesBetween(a: string, b: string | null): number | null {
  return b ? Math.round((new Date(b).getTime() - new Date(a).getTime()) / 6000) / 10 : null;
}

export function IncidentPage() {
  const { id } = useParams();
  const iid = Number(id);
  const [inc, setInc] = useState<Incident | null>(null);
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState("");
  const [resolving, setResolving] = useState(false);
  const [resolution, setResolution] = useState("");

  const load = useCallback(() => {
    Promise.all([get<Incident>(`/incidents/${iid}`), get<TimelineEvent[]>(`/incidents/${iid}/timeline`)])
      .then(([i, tl]) => {
        setInc(i);
        setEvents(tl);
      })
      .catch((e) => setError(e.message));
  }, [iid]);

  useEffect(() => {
    load();
    get<User[]>("/users").then(setUsers).catch(() => {});
  }, [load]);

  const move = async (to: Status, text = "") => {
    if (to === "resolved" && !text) {
      setResolving(true);
      return;
    }
    try {
      setInc(await patch<Incident>(`/incidents/${iid}/status`, { status: to, resolution: text }));
      setResolving(false);
      setResolution("");
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "could not change status");
    }
  };

  const assign = async (userId: string) => {
    try {
      await patch(`/incidents/${iid}/assignee`, { user_id: userId ? Number(userId) : null });
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "could not assign");
    }
  };

  if (error && !inc) return <p className="error">{error}</p>;
  if (!inc) return (
      <div aria-busy="true" aria-label="Loading">
        <div className="skeleton" style={{ height: 140 }} />
        <div className="skeleton" style={{ height: 320 }} />
      </div>
    );

  return (
    <div className="incident-page">
      <nav aria-label="Breadcrumb" className="crumbs">
        <Link to="/">Incidents</Link> / #{inc.id}
      </nav>
      <header className={`incident-head sev-border-${inc.severity.toLowerCase()}`}>
        <div className="badges">
          <SeverityBadge sev={inc.severity} />
          <StatusBadge status={inc.status} />
          {inc.is_demo && <span className="badge demo">demo</span>}
          {inc.simulated_fault && <span className="badge sim">simulated: {inc.simulated_fault}</span>}
        </div>
        <h1>{inc.title}</h1>
        <dl className="facts">
          <div>
            <dt>Service</dt>
            <dd>{inc.service}</dd>
          </div>
          <div>
            <dt>Opened</dt>
            <dd>{dateTime(inc.created_at)}</dd>
          </div>
          <div>
            <dt>Time to acknowledge</dt>
            <dd>{mins(minutesBetween(inc.created_at, inc.acknowledged_at))}</dd>
          </div>
          <div>
            <dt>Time to resolve</dt>
            <dd>{mins(minutesBetween(inc.created_at, inc.resolved_at))}</dd>
          </div>
          <div>
            <dt>Log window</dt>
            <dd>{inc.log_lines ?? 0} lines</dd>
          </div>
        </dl>
        <div className="actions">
          <label htmlFor="assignee">Assignee</label>
          <select id="assignee" value={inc.assignee?.id ?? ""} onChange={(e) => assign(e.target.value)} disabled={inc.status === "resolved"}>
            <option value="">Unassigned</option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
              </option>
            ))}
          </select>
          {NEXT[inc.status].map((n) => (
            <button key={n.to} type="button" className={n.to === "resolved" ? "secondary" : ""} onClick={() => move(n.to)}>
              {n.label}
            </button>
          ))}
          <Link className="button-link" to={`/incidents/${inc.id}/postmortem`}>
            Postmortem draft
          </Link>
        </div>
        {resolving && (
          <form
            className="resolve-form"
            onSubmit={(e) => {
              e.preventDefault();
              if (resolution.trim()) move("resolved", resolution.trim());
            }}
          >
            <label htmlFor="res">How was it resolved?</label>
            <textarea id="res" rows={2} value={resolution} onChange={(e) => setResolution(e.target.value)} autoFocus />
            <div className="row-btns">
              <button type="submit" disabled={!resolution.trim()}>
                Resolve incident
              </button>
              <button type="button" className="ghost-dark" onClick={() => setResolving(false)}>
                Cancel
              </button>
            </div>
          </form>
        )}
        {inc.resolution && (
          <p className="resolution">
            <strong>Resolution:</strong> {inc.resolution}
          </p>
        )}
        {error && <p className="error" role="alert">{error}</p>}
      </header>
      <div className="incident-grid">
        <InvestigationPanel
          incidentId={inc.id}
          investigationId={inc.verdict?.investigation_id ?? null}
          expected={inc.expected_label}
          hasLogs={(inc.log_lines ?? 0) > 0}
          onFinished={load}
        />
        <div>
          <section className="card" aria-labelledby="al-h">
            <h2 id="al-h">Alerts</h2>
            <ul className="alerts">
              {inc.alerts.map((a) => (
                <li key={a.id}>
                  <p>
                    <strong>{a.name}</strong> <span className="muted">×{a.count}</span>
                  </p>
                  <p className="small">{a.summary}</p>
                  <p className="muted small">from {a.source}</p>
                </li>
              ))}
            </ul>
          </section>
          <Timeline incidentId={inc.id} events={events} onAdded={load} />
        </div>
      </div>
    </div>
  );
}
