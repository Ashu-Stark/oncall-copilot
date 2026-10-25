import { useEffect, useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { get } from "../api";
import { useAuth } from "../auth";

export function Login() {
  const { user, login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [demo, setDemo] = useState<{ enabled: boolean; accounts?: string[]; password?: string } | null>(null);

  useEffect(() => {
    get<{ enabled: boolean; accounts?: string[]; password?: string }>("/auth/demo").then(setDemo).catch(() => setDemo(null));
  }, []);

  if (user) return <Navigate to="/" replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login(username.trim(), password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "sign-in failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap">
      <section className="login-hero">
        <p className="eyebrow">Incident response</p>
        <h1>On-call Runbook Copilot</h1>
        <p>
          When an alert fires, the copilot finds the matching runbook, proves the root cause from the service's own logs and cites the
          log lines, or says "unknown" instead of guessing.
        </p>
        <ul className="login-points">
          <li>🔎 Hybrid runbook search (BM25 + embeddings)</li>
          <li>🧪 Every diagnosis verified by checks on the incident's logs</li>
          <li>📝 Timeline and postmortem draft built from the record</li>
        </ul>
      </section>
      <main className="card login-card">
        <h2>Sign in</h2>
        <form onSubmit={submit} noValidate>
          <label htmlFor="u">Username</label>
          <input id="u" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
          <label htmlFor="p">Password</label>
          <input id="p" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button type="submit" disabled={busy || !username || !password}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
        {demo?.enabled && (
          <p className="demo-hint">
            Demo accounts:{" "}
            {demo.accounts?.map((a, i) => (
              <span key={a}>
                {i > 0 && " or "}
                <code>{a}</code>
              </span>
            ))}{" "}
            · password <code>{demo.password}</code>
          </p>
        )}
      </main>
    </div>
  );
}
