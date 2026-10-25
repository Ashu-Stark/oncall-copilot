// Minimal markdown for postmortem drafts: headings, lists, checkboxes, tables, quotes, `code`, **bold**, _italic_.
// Renders React elements (never innerHTML), so text from incidents cannot inject markup.
import type { ReactNode } from "react";

function inline(text: string, key: string): ReactNode[] {
  const out: ReactNode[] = [];
  const rx = /(`[^`]+`|\*\*[^*]+\*\*|(?<![A-Za-z0-9])_[^_`]+_(?![A-Za-z0-9]))/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = rx.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const t = m[0];
    const k = `${key}-${i++}`;
    if (t.startsWith("`")) out.push(<code key={k}>{t.slice(1, -1)}</code>);
    else if (t.startsWith("**")) out.push(<strong key={k}>{t.slice(2, -2)}</strong>);
    else out.push(<em key={k}>{t.slice(1, -1)}</em>);
    last = m.index + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Markdown({ source }: { source: string }) {
  const lines = source.split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  while (i < lines.length) {
    const l = lines[i];
    const k = `b${i}`;
    if (l.startsWith("# ")) blocks.push(<h2 key={k}>{inline(l.slice(2), k)}</h2>);
    else if (l.startsWith("## ")) blocks.push(<h3 key={k}>{inline(l.slice(3), k)}</h3>);
    else if (l.startsWith("> ")) blocks.push(<blockquote key={k}>{inline(l.slice(2), k)}</blockquote>);
    else if (l.startsWith("|")) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].startsWith("|")) {
        if (!/^\|[-| ]+\|$/.test(lines[i])) rows.push(lines[i].slice(1, -1).split("|").map((c) => c.trim()));
        i++;
      }
      const [head, ...body] = rows;
      blocks.push(
        <table key={k} className="md-table">
          <thead>
            <tr>{head.map((c, j) => <th key={j}>{inline(c, `${k}h${j}`)}</th>)}</tr>
          </thead>
          <tbody>
            {body.map((r, ri) => (
              <tr key={ri}>{r.map((c, j) => <td key={j}>{inline(c, `${k}r${ri}c${j}`)}</td>)}</tr>
            ))}
          </tbody>
        </table>,
      );
      continue;
    } else if (l.startsWith("- ")) {
      const items: string[] = [];
      while (i < lines.length && lines[i].startsWith("- ")) items.push(lines[i++].slice(2));
      blocks.push(
        <ul key={k} className="md-list">
          {items.map((it, j) =>
            it.startsWith("[ ] ") ? (
              <li key={j} className="todo">
                <span aria-hidden="true">☐</span> {inline(it.slice(4), `${k}${j}`)}
              </li>
            ) : (
              <li key={j}>{inline(it, `${k}${j}`)}</li>
            ),
          )}
        </ul>,
      );
      continue;
    } else if (l.trim()) blocks.push(<p key={k}>{inline(l, k)}</p>);
    i++;
  }
  return <div className="markdown">{blocks}</div>;
}
