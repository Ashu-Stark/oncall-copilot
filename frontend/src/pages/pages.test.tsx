import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { axeViolations, ENGINEER, json, LEAD, mockApi, renderAt } from "../test/helpers";
import { Inbox } from "./Inbox";
import { Login } from "./Login";
import { RunbookEditor } from "./RunbookEditor";

const INCIDENT = {
  id: 7,
  title: "HighErrorRate + ReadinessFailing: 67% of 60 requests returned 5xx",
  service: "hoi-platform",
  severity: "SEV1",
  status: "triggered",
  assignee: null,
  created_at: new Date().toISOString(),
  acknowledged_at: null,
  resolved_at: null,
  is_demo: false,
  simulated_fault: "db_down",
  expected_label: "RB01",
  resolution: "",
  alert_count: 1,
  alerts: [],
  verdict: { investigation_id: 3, status: "done", label: "RB01" },
};

describe("Login", () => {
  it("shows the server's message on a wrong password and has no accessibility violations", async () => {
    mockApi({
      "GET /api/auth/demo": () => json({ enabled: false }),
      "POST /api/auth/login": () => json({ detail: "wrong username or password" }, 401),
    });
    const { container } = renderAt("/login", "/login", <Login />, false);
    await userEvent.type(screen.getByLabelText("Username"), "lead.demo");
    await userEvent.type(screen.getByLabelText("Password"), "nope");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("wrong username or password");
    expect(await axeViolations(container)).toEqual([]);
  });
});

describe("Inbox", () => {
  it("lists incidents with severity, status and verdict, and filters through the URL", async () => {
    const calls = mockApi({
      "GET /api/auth/me": () => json(ENGINEER),
      "GET /api/incidents": () => json({ items: [INCIDENT], total: 1 }),
      "GET /api/simulator": () => json({ available: true, faults: [{ name: "db_down", description: "MongoDB becomes unreachable", expected: "RB01" }] }),
    });
    const { container } = renderAt("/", "/", <Inbox />);
    const card = (await screen.findByText(/#7 HighErrorRate/)).closest("li")!;
    expect(within(card).getByText("SEV1")).toBeInTheDocument();
    expect(within(card).getByText("triggered")).toBeInTheDocument();
    expect(within(card).getByText("RB01")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Severity"), "SEV1");
    await waitFor(() => expect(calls.some((c) => c.url.includes("/incidents?status=open&severity=SEV1"))).toBe(true));
    await userEvent.click(screen.getByRole("radio", { name: "resolved" }));
    await waitFor(() => expect(calls.some((c) => c.url.includes("status=resolved"))).toBe(true));
    expect(await axeViolations(container)).toEqual([]);
  });

  it("injects a fault and opens the new incident", async () => {
    const calls = mockApi({
      "GET /api/auth/me": () => json(ENGINEER),
      "GET /api/incidents": () => json({ items: [], total: 0 }),
      "GET /api/simulator": () => json({ available: true, faults: [{ name: "db_down", description: "MongoDB becomes unreachable", expected: "RB01" }] }),
      "POST /api/simulator/run": () => json({ incident_id: 12, investigation_id: 4, alerts: [{ name: "HighErrorRate", summary: "" }], log_lines: 100, message: "ok" }),
    });
    renderAt("/", "/", <Inbox />);
    await screen.findByText(/ground truth: RB01/);
    await userEvent.click(screen.getByRole("button", { name: "Inject fault" }));
    expect(await screen.findByText("other page")).toBeInTheDocument(); // navigated to /incidents/12
    expect(calls.find((c) => c.method === "POST")!.body).toMatchObject({ fault: "db_down" });
  });

  it("says plainly when a fault pages nobody", async () => {
    mockApi({
      "GET /api/auth/me": () => json(ENGINEER),
      "GET /api/incidents": () => json({ items: [], total: 0 }),
      "GET /api/simulator": () => json({ available: true, faults: [{ name: "portal_down", description: "Tourism portal down", expected: "NONE" }] }),
      "POST /api/simulator/run": () => json({ incident_id: null, alerts: [], log_lines: 64, message: "No alert rule fired, so nobody is paged (correct: this fault has no user impact)" }),
    });
    renderAt("/", "/", <Inbox />);
    await screen.findByText(/ground truth: NONE/);
    await userEvent.click(screen.getByRole("button", { name: "Inject fault" }));
    expect(await screen.findByText(/nobody is paged/)).toBeInTheDocument();
  });
});

describe("RunbookEditor", () => {
  const RB = { id: "RB01", title: "Database unreachable", version: 2, markdown: "# RB01 · Database unreachable\n...", versions: [{ version: 2, edited_by: "lead.demo", comment: "", at: new Date().toISOString() }] };

  it("shows validation errors with line links and blocks saving", async () => {
    mockApi({
      "GET /api/auth/me": () => json(LEAD),
      "GET /api/runbooks/RB01": () => json(RB),
      "POST /api/runbooks/validate": () =>
        json({ valid: false, errors: [{ line: 12, message: "check 3: unknown tool 'restart_service'" }], parsed: null }),
    });
    const { container } = renderAt("/runbooks/RB01", "/runbooks/:id", <RunbookEditor />);
    await userEvent.type(await screen.findByLabelText(/Markdown/), "x");
    expect(await screen.findByText(/unknown tool 'restart_service'/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "line 12" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save new version" })).toBeDisabled();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("sends the base version so a concurrent edit is not overwritten", async () => {
    const calls = mockApi({
      "GET /api/auth/me": () => json(LEAD),
      "GET /api/runbooks/RB01": () => json(RB),
      "POST /api/runbooks/validate": () => json({ valid: true, errors: [], parsed: { id: "RB01", title: "t", severity: "SEV1", root_cause: "r", checks: [] } }),
      "PUT /api/runbooks/RB01": () => json({ detail: "RB01 was changed by someone (now version 3); reload and reapply your edit" }, 409),
    });
    renderAt("/runbooks/RB01", "/runbooks/:id", <RunbookEditor />);
    await userEvent.type(await screen.findByLabelText(/Markdown/), "!");
    await screen.findByText("Valid runbook");
    await userEvent.click(screen.getByRole("button", { name: "Save new version" }));
    expect(await screen.findByRole("status")).toHaveTextContent("reload and reapply");
    expect(calls.find((c) => c.method === "PUT")!.body).toMatchObject({ base_version: 2 });
  });

  it("is read-only for engineers", async () => {
    mockApi({
      "GET /api/auth/me": () => json(ENGINEER),
      "GET /api/runbooks/RB01": () => json(RB),
      "POST /api/runbooks/validate": () => json({ valid: true, errors: [], parsed: null }),
    });
    renderAt("/runbooks/RB01", "/runbooks/:id", <RunbookEditor />);
    expect(await screen.findByText(/only an on-call lead can change runbooks/)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("button", { name: /Save/ })).not.toBeInTheDocument());
  });
});
