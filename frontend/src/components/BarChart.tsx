// Horizontal bars as a table: readable at any width, and screen readers get the numbers as a real table.

export function BarChart({ data, label, unit = "", byValue = true }: { data: Record<string, number>; label: string; unit?: string; byValue?: boolean }) {
  const rows = byValue ? Object.entries(data).sort((a, b) => b[1] - a[1]) : Object.entries(data);
  const max = Math.max(1, ...rows.map(([, v]) => v));
  if (!rows.length) return <p className="muted">No data yet.</p>;
  return (
    <table className="bars" aria-label={label}>
      <tbody>
        {rows.map(([k, v]) => (
          <tr key={k}>
            <th scope="row">{k}</th>
            <td>
              <span className="bar" style={{ width: `${(v / max) * 100}%` }} aria-hidden="true" />
              <span className="bar-v">
                {v}
                {unit}
              </span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
