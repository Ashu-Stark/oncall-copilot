import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, get, post, put, type ValidationError } from "../api";
import { useAuth } from "../auth";
import { dateTime } from "../format";

interface RunbookDetail {
  id: string;
  title: string;
  version: number;
  markdown: string;
  versions: { version: number; edited_by: string; comment: string; at: string }[];
}

interface Parsed {
  id: string;
  title: string;
  severity: string;
  root_cause: string;
  checks: { tool: string; args?: Record<string, unknown>; field?: string; op: string; value: unknown }[];
}

const TEMPLATE = `# RB17 · Short title
**Service:** hoi-platform · **Severity:** SEV2 · **Root cause:** one sentence on what actually broke.

## Symptoms
- What the alerts and logs look like.

## Checks
\`\`\`checks
[
  {"tool": "search_logs", "args": {"pattern": "text that only this failure logs"}, "field": "count", "op": ">=", "value": 3}
]
\`\`\`

## Diagnosis
1. How to confirm it by hand.

## Mitigation
- How to stop the bleeding.
`;

export function RunbookEditor() {
  const { id } = useParams();
  const isNew = !id;
  const { user } = useAuth();
  const canEdit = user?.role === "lead";
  const navigate = useNavigate();
  const [rb, setRb] = useState<RunbookDetail | null>(null);
  const [md, setMd] = useState(isNew ? TEMPLATE : "");
  const [comment, setComment] = useState("");
  const [errors, setErrors] = useState<ValidationError[]>([]);
  const [parsed, setParsed] = useState<Parsed | null>(null);
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (isNew) return;
    get<RunbookDetail>(`/runbooks/${id}`)
      .then((r) => {
        setRb(r);
        setMd(r.markdown);
      })
      .catch((e) => setStatus(e.message));
  }, [id, isNew]);

  // validate as the user types (debounced), with the same rules the server applies on save
  useEffect(() => {
    if (!md) return;
    const t = setTimeout(() => {
      post<{ valid: boolean; errors: ValidationError[]; parsed: Parsed | null }>("/runbooks/validate", { markdown: md, id: isNew ? null : id })
        .then((r) => {
          setErrors(r.errors);
          setParsed(r.parsed);
        })
        .catch(() => {});
    }, 350);
    return () => clearTimeout(t);
  }, [md, id, isNew]);

  const jumpTo = (line: number | null) => {
    const ta = area.current;
    if (!ta || !line) return;
    const offset = md.split("\n").slice(0, line - 1).join("\n").length + (line > 1 ? 1 : 0);
    ta.focus();
    ta.setSelectionRange(offset, offset + (md.split("\n")[line - 1]?.length ?? 0));
  };

  const save = async () => {
    setSaving(true);
    setStatus("");
    try {
      if (isNew) {
        const r = await post<{ id: string }>("/runbooks", { markdown: md, comment });
        navigate(`/runbooks/${r.id}`);
      } else {
        const r = await put<{ version: number }>(`/runbooks/${id}`, { markdown: md, comment, base_version: rb?.version });
        setStatus(`Saved as version ${r.version}. The next investigation uses it.`);
        setComment("");
        setRb(await get<RunbookDetail>(`/runbooks/${id}`));
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 422 && e.detail && typeof e.detail === "object" && "errors" in e.detail) {
        setErrors((e.detail as { errors: ValidationError[] }).errors);
        setStatus("Not saved: fix the errors listed.");
      } else setStatus(e instanceof Error ? e.message : "could not save");
    } finally {
      setSaving(false);
    }
  };

  const restore = async (v: number) => {
    const r = await get<{ markdown: string }>(`/runbooks/${id}/versions/${v}`);
    setMd(r.markdown);
    setStatus(`Loaded version ${v} into the editor. Save to make it current.`);
  };

  const dirty = isNew || (rb !== null && md !== rb.markdown);
  return (
    <div className="editor-page">
      <nav aria-label="Breadcrumb" className="crumbs">
        <Link to="/runbooks">Runbooks</Link> / {isNew ? "new" : id}
      </nav>
      <h1>{isNew ? "New runbook" : `${id} · ${rb?.title ?? ""}`}</h1>
      {!canEdit && <p className="note">Read-only: only an on-call lead can change runbooks. You can still try edits here; they are validated but cannot be saved.</p>}
      <div className="editor-grid">
        <section className="card">
          <label htmlFor="md" className="editor-label">
            Markdown {rb && <span className="muted">(version {rb.version})</span>}
          </label>
          <textarea
            id="md"
            ref={area}
            className="code"
            spellCheck={false}
            value={md}
            onChange={(e) => setMd(e.target.value)}
            aria-describedby="val-h"
            aria-invalid={errors.length > 0}
          />
          {canEdit && (
            <div className="save-row">
              <label htmlFor="cm" className="visually-hidden">
                Change note
              </label>
              <input id="cm" placeholder="What changed and why (shown in the history)" value={comment} onChange={(e) => setComment(e.target.value)} maxLength={200} />
              <button type="button" onClick={save} disabled={saving || errors.length > 0 || !dirty}>
                {saving ? "Saving…" : isNew ? "Create runbook" : "Save new version"}
              </button>
            </div>
          )}
          {status && <p role="status" className="save-status">{status}</p>}
        </section>
        <aside>
          <section className={`card validation ${errors.length ? "bad" : "good"}`} aria-labelledby="val-h">
            <h2 id="val-h">{errors.length ? `${errors.length} problem${errors.length > 1 ? "s" : ""}` : "Valid runbook"}</h2>
            {errors.length > 0 ? (
              <ul className="val-errors">
                {errors.map((e, i) => (
                  <li key={i}>
                    {e.line ? (
                      <button type="button" className="linkish" onClick={() => jumpTo(e.line)}>
                        line {e.line}
                      </button>
                    ) : null}{" "}
                    {e.message}
                  </li>
                ))}
              </ul>
            ) : (
              parsed && (
                <>
                  <p className="small">
                    <strong>{parsed.severity}</strong> · {parsed.root_cause}
                  </p>
                  <p className="small muted">The investigator will run these checks against an incident's logs:</p>
                  <ol className="parsed-checks">
                    {parsed.checks.map((c, i) => (
                      <li key={i}>
                        <code>
                          {c.tool}({Object.entries(c.args ?? {}).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ")}){c.field ? `.${c.field}` : ""} {c.op}{" "}
                          {JSON.stringify(c.value)}
                        </code>
                      </li>
                    ))}
                  </ol>
                </>
              )
            )}
          </section>
          {rb && rb.versions.length > 0 && (
            <section className="card" aria-labelledby="hist-h">
              <h2 id="hist-h">History</h2>
              <ol className="history">
                {rb.versions.map((v) => (
                  <li key={v.version}>
                    <p>
                      <strong>v{v.version}</strong> · {v.edited_by} · <span className="muted">{dateTime(v.at)}</span>
                    </p>
                    {v.comment && <p className="small">{v.comment}</p>}
                    {v.version !== rb.version && (
                      <button type="button" className="linkish" onClick={() => restore(v.version)}>
                        Load this version
                      </button>
                    )}
                  </li>
                ))}
              </ol>
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}
