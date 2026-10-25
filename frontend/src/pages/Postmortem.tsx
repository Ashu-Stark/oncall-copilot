import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { get } from "../api";
import { Markdown } from "../components/Markdown";

export function Postmortem() {
  const { id } = useParams();
  const [md, setMd] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    get<{ markdown: string }>(`/incidents/${id}/postmortem`)
      .then((r) => setMd(r.markdown))
      .catch((e) => setError(e.message));
  }, [id]);

  const download = () => {
    if (!md) return;
    const url = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `postmortem-incident-${id}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const copy = async () => {
    if (!md) return;
    try {
      await navigator.clipboard.writeText(md);
      setCopied(true);
    } catch {
      setError("copy is blocked in this browser; use Download");
    }
  };

  return (
    <div className="postmortem">
      <nav aria-label="Breadcrumb" className="crumbs">
        <Link to="/">Incidents</Link> / <Link to={`/incidents/${id}`}>#{id}</Link> / postmortem
      </nav>
      <div className="pm-actions">
        <button type="button" onClick={download} disabled={!md}>
          Download .md
        </button>
        <button type="button" className="secondary" onClick={copy} disabled={!md}>
          {copied ? "Copied" : "Copy markdown"}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      <article className="card">{md ? <Markdown source={md} /> : <p className="muted">Building the draft…</p>}</article>
    </div>
  );
}
