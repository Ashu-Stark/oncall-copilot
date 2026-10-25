import type { Severity, Status } from "../api";

const SEV_TEXT: Record<Severity, string> = { SEV1: "SEV1 · critical", SEV2: "SEV2 · major", SEV3: "SEV3 · minor", SEV4: "SEV4 · info" };

export function SeverityBadge({ sev, short = false }: { sev: Severity; short?: boolean }) {
  return <span className={`badge sev-${sev.toLowerCase()}`}>{short ? sev : SEV_TEXT[sev]}</span>;
}

export function StatusBadge({ status }: { status: Status }) {
  return <span className={`badge status status-${status}`}>{status}</span>;
}

export function VerdictBadge({ label, status }: { label: string | null; status?: string }) {
  if (status && status !== "done") return <span className="badge verdict pending">{status === "failed" ? "investigation failed" : "investigating…"}</span>;
  if (!label) return <span className="badge verdict none">no verdict</span>;
  if (label === "UNKNOWN") return <span className="badge verdict unknown">abstained</span>;
  if (label === "NONE") return <span className="badge verdict none">no incident</span>;
  return <span className="badge verdict ok">{label}</span>;
}
