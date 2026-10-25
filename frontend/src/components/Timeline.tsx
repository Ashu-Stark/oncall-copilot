import { useState, type FormEvent } from "react";
import { post, type TimelineEvent } from "../api";
import { clock } from "../format";

const ICON: Record<string, string> = {
  alert: "🚨",
  alert_repeated: "🔁",
  status: "↪",
  assigned: "👤",
  note: "📝",
  investigation: "🧭",
  verdict: "🎯",
  severity: "⚠",
};

export function Timeline({ incidentId, events, onAdded }: { incidentId: number; events: TimelineEvent[]; onAdded: () => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    setBusy(true);
    setError("");
    try {
      await post(`/incidents/${incidentId}/notes`, { text });
      setText("");
      onAdded();
    } catch (err) {
      setError(err instanceof Error ? err.message : "could not save the note");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card" aria-labelledby="tl-h">
      <h2 id="tl-h">Timeline</h2>
      <ol className="timeline">
        {events.map((e) => (
          <li key={e.id} className={`tl tl-${e.kind}`}>
            <span className="tl-icon" aria-hidden="true">
              {ICON[e.kind] ?? "•"}
            </span>
            <div>
              <p className="tl-text">{e.text}</p>
              <p className="tl-meta">
                <time dateTime={e.at}>{clock(e.at)}</time> · {e.actor}
              </p>
            </div>
          </li>
        ))}
      </ol>
      <form onSubmit={submit} className="note-form">
        <label htmlFor="note">Add a note</label>
        <textarea id="note" rows={2} value={text} onChange={(e) => setText(e.target.value)} maxLength={4000} placeholder="What did you check? What did you change?" />
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={busy || !text.trim()}>
          Add note
        </button>
      </form>
    </section>
  );
}
