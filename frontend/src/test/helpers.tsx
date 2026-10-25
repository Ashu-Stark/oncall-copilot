import { render } from "@testing-library/react";
import axe from "axe-core";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";
import { AuthProvider } from "../auth";

type Handler = (url: string, init: RequestInit) => Response | Promise<Response>;

export const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

export const sse = (events: { id?: number; event: string; data: unknown }[]) =>
  new Response(events.map((e) => `${e.id ? `id: ${e.id}\n` : ""}event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`).join(""), {
    headers: { "Content-Type": "text/event-stream" },
  });

/** Routes fetch calls by "METHOD /path" prefix; records every call. Unmatched calls fail the test loudly. */
export function mockApi(routes: Record<string, Handler>) {
  const calls: { method: string; url: string; body?: unknown; headers: Record<string, string> }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input);
    const method = (init.method ?? "GET").toUpperCase();
    calls.push({ method, url, body: init.body ? JSON.parse(String(init.body)) : undefined, headers: (init.headers ?? {}) as Record<string, string> });
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    const key = Object.keys(routes)
      .filter((k) => {
        const [m, p] = k.split(" ");
        return m === method && path.startsWith(p);
      })
      .sort((a, b) => b.length - a.length)[0];
    if (!key) throw new Error(`unexpected request ${method} ${path}`);
    return routes[key](path, init);
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

export const LEAD = { id: 1, username: "lead.demo", name: "Asha Rao", role: "lead" };
export const ENGINEER = { id: 2, username: "engineer.demo", name: "Ravi Kumar", role: "engineer" };

export function renderAt(path: string, routePath: string, element: ReactElement, signedIn = true) {
  if (signedIn) localStorage.setItem("oncall.token", "test-token");
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <Routes>
          <Route path={routePath} element={element} />
          <Route path="*" element={<p>other page</p>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

export async function axeViolations(container: HTMLElement): Promise<string[]> {
  // colour contrast needs real layout, which jsdom does not do; it is checked in the browser instead
  const r = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  return r.violations.map((v) => `${v.id}: ${v.nodes.length}`);
}
