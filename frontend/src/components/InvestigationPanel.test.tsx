import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { axeViolations, json, mockApi, sse } from "../test/helpers";
import { InvestigationPanel } from "./InvestigationPanel";

const STEPS = [
  { seq: 1, kind: "alerts", title: "Alert rules on the log window: HighErrorRate", data: { alerts: [{ name: "HighErrorRate", summary: "67% of 60 requests returned 5xx" }] }, at: "" },
  { seq: 2, kind: "retrieval", title: "Retrieved 2 candidate runbooks (hybrid search)", data: { ranker: "hybrid", candidates: [{ runbook: "RB13", why: "rrf" }, { runbook: "RB01", why: "rrf" }] }, at: "" },
  {
    seq: 3,
    kind: "check",
    title: "RB13: 0/1 checks passed, rejected",
    data: { runbook: "RB13", confirmed: false, results: [{ tool: "search_logs", args: { pattern: "compensation" }, field: "count", op: ">=", expected: 1, actual: 0, passed: false, evidence: [] }] },
    at: "",
  },
  {
    seq: 4,
    kind: "check",
    title: "RB01: 1/1 checks passed, confirmed",
    data: {
      runbook: "RB01",
      confirmed: true,
      results: [{ tool: "search_logs", args: { pattern: "ServerSelectionTimeoutError" }, field: "count", op: ">=", expected: 1, actual: 36, passed: true, evidence: [26], evidence_lines: ["#26 ERROR hoi.platform: unhandled error | ServerSelectionTimeoutError"] }],
    },
    at: "",
  },
  {
    seq: 5,
    kind: "verdict",
    title: "Root cause: RB01 · Database unreachable (MongoDB)",
    data: {
      label: "RB01",
      title: "Database unreachable (MongoDB)",
      severity: "SEV1",
      root_cause: "the API cannot reach the MongoDB cluster",
      verification: { runbook: "RB01", passed: 1, total: 1 },
      evidence: ["#26 ERROR hoi.platform: unhandled error | ServerSelectionTimeoutError"],
      next_steps: ["[Diagnosis] Check Atlas status"],
      mode: "hybrid+checks",
      elapsed_ms: 3.2,
      paced_ms: 1400,
    },
    at: "",
  },
];

describe("InvestigationPanel", () => {
  it("streams steps as they arrive and ends with a verified verdict", async () => {
    let finished = false;
    const calls = mockApi({
      "GET /api/investigations/9/stream": () => sse(STEPS.map((s) => ({ id: s.seq, event: "step", data: s })).concat([{ event: "done", data: { status: "done" } } as never])),
      "GET /api/investigations/9": () =>
        finished ? json({ id: 9, status: "done", label: "RB01", steps: STEPS }) : ((finished = true), json({ id: 9, status: "running", label: null, steps: [] })),
    });
    localStorage.setItem("oncall.token", "tok");
    const { container } = render(
      <MemoryRouter>
        <InvestigationPanel incidentId={4} investigationId={9} expected="RB01" hasLogs />
      </MemoryRouter>,
    );
    const verdict = await screen.findByRole("group", { name: "Copilot verdict" });
    expect(within(verdict).getByText(/RB01 · Database unreachable/)).toBeInTheDocument();
    expect(within(verdict).getByText(/Verified: 1\/1 runbook checks passed/)).toBeInTheDocument();
    expect(within(verdict).getByText(/ground truth: RB01 ✓ matches/)).toBeInTheDocument();
    expect(within(verdict).getByText(/investigation 3.2 ms/)).toBeInTheDocument();
    // the steps are in order, rejected runbook before the confirmed one
    const titles = screen.getAllByRole("listitem").map((li) => li.querySelector(".step-title")?.textContent).filter(Boolean);
    expect(titles.findIndex((t) => t!.includes("RB13"))).toBeLessThan(titles.findIndex((t) => t!.includes("RB01: 1/1")));
    // the text the check searched for is highlighted in the evidence
    expect([...container.querySelectorAll("mark")].map((m) => m.textContent)).toContain("ServerSelectionTimeoutError");
    const stream = calls.find((c) => c.url.endsWith("/stream"))!;
    expect(stream.headers.Authorization).toBe("Bearer tok");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("shows an abstention as 'escalate to a human', not as a diagnosis", async () => {
    const verdict = { seq: 1, kind: "verdict", title: "Abstained", data: { label: "UNKNOWN", note: "none of the top 5 runbooks was confirmed by the logs; escalate to a human", evidence: [], next_steps: [], mode: "hybrid+checks", elapsed_ms: 2 }, at: "" };
    mockApi({ "GET /api/investigations/3": () => json({ id: 3, status: "done", label: "UNKNOWN", steps: [verdict] }) });
    render(
      <MemoryRouter>
        <InvestigationPanel incidentId={1} investigationId={3} expected={null} hasLogs />
      </MemoryRouter>,
    );
    expect(await screen.findByText("Abstained: escalate to a human")).toBeInTheDocument();
    expect(screen.queryByText(/Root cause:/)).not.toBeInTheDocument();
  });

  it("explains why there is nothing to investigate without logs", async () => {
    mockApi({});
    render(
      <MemoryRouter>
        <InvestigationPanel incidentId={1} investigationId={null} expected={null} hasLogs={false} />
      </MemoryRouter>,
    );
    expect(screen.getByText(/no log window attached/)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("button", { name: /investigate/i })).not.toBeInTheDocument());
  });
});
