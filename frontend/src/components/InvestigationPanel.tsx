import { useCallback, useEffect, useRef, useState } from "react";
import { authHeaders, get, post, streamUrl, type CheckResult, type Investigation, type Step } from "../api";
import { readStream } from "../sse";

const STATUS = /-> [45]\d\d/;

function escape(re: string): string {
  return re.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Wraps the parts of `text` that matched a check (its search pattern, or an error status code) in <mark>. */
function highlight(text: string, patterns: string[]) {
  const parts = [...patterns.filter(Boolean).map(escape), STATUS.source];
  const rx = new RegExp(`(${parts.join("|")})`, "gi");
  return text.split(rx).map((chunk, i) => (i % 2 ? <mark key={i}>{chunk}</mark> : chunk));
}

function LogLine({ line, patterns = [] }: { line: string; patterns?: string[] }) {
  const m = /^#(\d+) (CRITICAL|ERROR|WARNING|INFO|DEBUG) (.*)$/.exec(line);
  if (!m) return <li className="log">{line}</li>;
  return (
    <li className={`log log-${m[2].toLowerCase()}`}>
      <span className="log-id">#{m[1]}</span> <span className="log-level">{m[2]}</span> {highlight(m[3], patterns)}
    </li>
  );
}

function patternsOf(results: CheckResult[] = []): string[] {
  return results.map((r) => (typeof r.args?.pattern === "string" ? (r.args.pattern as string) : "")).filter(Boolean);
}

function fmt(v: unknown): string {
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(3);
  return JSON.stringify(v);
}

function CheckTable({ results }: { results: CheckResult[] }) {
  return (
    <table className="checks">
      <thead>
        <tr>
          <th scope="col">Check</th>
          <th scope="col">Expected</th>
          <th scope="col">Found in logs</th>
          <th scope="col">
            <span className="visually-hidden">Result</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {results.map((r, i) => (
          <tr key={i} className={r.passed ? "pass" : "fail"}>
            <td>
              <code>
                {r.tool}({Object.entries(r.args).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ")})
                {r.field ? `.${r.field}` : ""}
              </code>
            </td>
            <td>
              {r.op} {fmt(r.expected)}
            </td>
            <td>{fmt(r.actual)}</td>
            <td>{r.passed ? <span className="tick">✓ pass</span> : <span className="cross">✗ fail</span>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function StepBody({ step, expected }: { step: Step; expected: string | null }) {
  const d = step.data;
  switch (step.kind) {
    case "alerts":
      return d.alerts.length ? (
        <ul className="chips">
          {d.alerts.map((a: { name: string; summary: string }) => (
            <li key={a.name}>
              <strong>{a.name}</strong> {a.summary}
            </li>
          ))}
        </ul>
      ) : null;
    case "query":
      return <p className="query">{d.query.length > 260 ? d.query.slice(0, 260) + "…" : d.query}</p>;
    case "retrieval":
      return (
        <ol className="ranked">
          {d.candidates.map((c: { runbook: string; why: string }) => (
            <li key={c.runbook}>
              <strong>{c.runbook}</strong> <span className="muted">{c.why}</span>
            </li>
          ))}
        </ol>
      );
    case "check": {
      const lines = (d.results as CheckResult[]).flatMap((r) => r.evidence_lines ?? []);
      const pats = patternsOf(d.results);
      return (
        <>
          <CheckTable results={d.results} />
          {d.confirmed && lines.length > 0 && (
            <details>
              <summary>Evidence the checks used ({Math.min(lines.length, 6)} log lines)</summary>
              <ul className="logs">{lines.slice(0, 6).map((l, i) => <LogLine key={i} line={l} patterns={pats} />)}</ul>
            </details>
          )}
        </>
      );
    }
    case "verdict":
      return <Verdict d={d} expected={expected} />;
  }
}

function Verdict({ d, expected }: { d: Step["data"]; expected: string | null }) {
  const confirmed = d.label !== "UNKNOWN" && d.label !== "NONE";
  const pats = patternsOf((d.checks ?? []).find((c: { confirmed: boolean }) => c.confirmed)?.results);
  return (
    <div className={`verdict-card ${confirmed ? "confirmed" : "abstained"}`} role="group" aria-label="Copilot verdict">
      {confirmed ? (
        <>
          <p className="verdict-label">
            {d.label} · {d.title} <span className="sev-text">{d.severity}</span>
          </p>
          <p>
            <strong>Root cause:</strong> {d.root_cause}
          </p>
          {d.verification && (
            <p className="verify">
              Verified: {d.verification.passed}/{d.verification.total} runbook checks passed on this incident's logs. Grounding
              check: every cited log line exists.
            </p>
          )}
        </>
      ) : (
        <>
          <p className="verdict-label">{d.label === "NONE" ? "No incident" : "Abstained: escalate to a human"}</p>
          <p>{d.note || "None of the retrieved runbooks was confirmed by the logs, so the copilot does not guess."}</p>
        </>
      )}
      {d.evidence?.length > 0 && (
        <ul className="logs" aria-label="Evidence log lines">
          {(d.evidence as string[]).slice(0, 4).map((l, i) => (
            <LogLine key={i} line={l} patterns={pats} />
          ))}
        </ul>
      )}
      {d.next_steps?.length > 0 && (
        <details>
          <summary>Runbook steps ({d.next_steps.length})</summary>
          <ol className="next">{(d.next_steps as string[]).map((s, i) => <li key={i}>{s}</li>)}</ol>
        </details>
      )}
      {expected && (
        <p className={`truth ${expected === d.label ? "match" : "miss"}`}>
          Simulation ground truth: {expected} {expected === d.label ? "✓ matches" : "✗ does not match"}
        </p>
      )}
      <p className="muted small">
        {d.mode} · investigation {d.elapsed_ms < 10 ? d.elapsed_ms.toFixed(1) : Math.round(d.elapsed_ms)} ms incl. saving each step
        {d.paced_ms ? " (shown slowly on purpose)" : ""}
      </p>
    </div>
  );
}

const ICON: Record<Step["kind"], string> = { alerts: "🚨", query: "🔎", retrieval: "📚", check: "🧪", verdict: "🎯" };

export function InvestigationPanel({
  incidentId,
  investigationId,
  expected,
  hasLogs,
  onFinished,
}: {
  incidentId: number;
  investigationId: number | null;
  expected: string | null;
  hasLogs: boolean;
  onFinished?: () => void;
}) {
  const [inv, setInv] = useState<Investigation | null>(null);
  const [steps, setSteps] = useState<Step[]>([]);
  const [live, setLive] = useState(false);
  const [error, setError] = useState("");
  const [current, setCurrent] = useState<number | null>(investigationId);
  const finished = useRef(onFinished);
  finished.current = onFinished;

  useEffect(() => setCurrent(investigationId), [investigationId]);

  useEffect(() => {
    if (current === null) return;
    const ctl = new AbortController();
    let cancelled = false;
    (async () => {
      try {
        const first = await get<Investigation>(`/investigations/${current}`);
        if (cancelled) return;
        setInv(first);
        setSteps(first.steps ?? []);
        if (first.status === "done" || first.status === "failed") return;
        setLive(true);
        const seen = new Set((first.steps ?? []).map((s) => s.seq));
        await readStream(
          streamUrl(current),
          authHeaders(),
          (ev) => {
            if (ev.event !== "step") return;
            const st = JSON.parse(ev.data) as Step;
            if (seen.has(st.seq)) return;
            seen.add(st.seq);
            setSteps((prev) => [...prev, st]);
          },
          ctl.signal,
        );
        if (cancelled) return;
        setInv(await get<Investigation>(`/investigations/${current}`));
        finished.current?.();
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "could not load the investigation");
      } finally {
        if (!cancelled) setLive(false);
      }
    })();
    return () => {
      cancelled = true;
      ctl.abort();
    };
  }, [current]);

  const rerun = useCallback(async () => {
    setError("");
    try {
      const r = await post<Investigation>(`/incidents/${incidentId}/investigations`);
      setSteps([]);
      setInv(r);
      setCurrent(r.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "could not start");
    }
  }, [incidentId]);

  return (
    <section className="card investigation" aria-labelledby="inv-h">
      <div className="card-head">
        <h2 id="inv-h">Copilot investigation</h2>
        {live && (
          <span className="live" role="status">
            <span className="dot" aria-hidden="true" /> live
          </span>
        )}
        {hasLogs && !live && (
          <button type="button" className="secondary small-btn" onClick={rerun}>
            {current === null ? "Investigate" : "Re-run"}
          </button>
        )}
      </div>
      {!hasLogs && <p className="muted">This incident has no log window attached, so the copilot has nothing to verify against.</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {inv?.status === "failed" && <p className="error">The investigation failed: {inv.error}</p>}
      <ol className="steps" aria-live="polite">
        {steps.map((s) => (
          <li key={s.seq} className={`step step-${s.kind}${s.kind === "check" ? (s.data.confirmed ? " ok" : " no") : ""}`}>
            <div className="step-title">
              <span className="step-icon" aria-hidden="true">
                {ICON[s.kind]}
              </span>
              {s.title}
            </div>
            <StepBody step={s} expected={expected} />
          </li>
        ))}
        {live && (
          <li className="step pending" aria-hidden="true">
            <div className="step-title">
              <span className="spinner" /> working…
            </div>
          </li>
        )}
      </ol>
    </section>
  );
}
