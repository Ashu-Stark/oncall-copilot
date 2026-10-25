import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { get, type RunbookSummary } from "../api";
import { useAuth } from "../auth";
import { ago } from "../format";

export function Runbooks() {
  const { user } = useAuth();
  const [rows, setRows] = useState<RunbookSummary[] | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");

  useEffect(() => {
    get<RunbookSummary[]>("/runbooks").then(setRows).catch((e) => setError(e.message));
  }, []);

  const shown = rows?.filter((r) => `${r.id} ${r.title} ${r.severity}`.toLowerCase().includes(filter.toLowerCase()));
  return (
    <div className="runbooks">
      <section className="hero">
        <h1>Runbook library</h1>
        <p>
          The copilot retrieves these runbooks and confirms one only when its <code>checks</code> pass on the incident's logs. Edits take effect on the next
          investigation; every save is a new version.
        </p>
      </section>
      <div className="filters">
        <label htmlFor="rbf" className="visually-hidden">
          Filter runbooks
        </label>
        <input id="rbf" type="search" placeholder="Filter by id, title or severity" value={filter} onChange={(e) => setFilter(e.target.value)} />
        {user?.role === "lead" && (
          <Link className="button-link" to="/runbooks/new">
            New runbook
          </Link>
        )}
      </div>
      {error && <p className="error">{error}</p>}
      <ul className="rb-grid">
        {shown?.map((r) => (
          <li key={r.id} className="card rb-card">
            <Link to={`/runbooks/${r.id}`}>
              <span className="rb-id">{r.id}</span>
              <span className="rb-title">{r.title}</span>
            </Link>
            <p className="muted small">
              {r.severity} · v{r.version} · edited {ago(r.updated_at)} by {r.updated_by}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}
