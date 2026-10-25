import { describe, expect, it, vi } from "vitest";
import { readStream, SseParser } from "./sse";

describe("SseParser", () => {
  it("joins events split across chunks and skips keep-alive comments", () => {
    const p = new SseParser();
    expect(p.push("id: 1\nevent: step\nda")).toEqual([]);
    expect(p.push('ta: {"seq":1}\n\n: keep-alive\n\nevent: done\ndata: {}\n\n')).toEqual([
      { id: "1", event: "step", data: '{"seq":1}' },
      { event: "done", data: "{}" },
    ]);
  });

  it("handles CRLF line endings", () => {
    expect(new SseParser().push("event: step\r\ndata: x\r\n\r\n")).toEqual([{ event: "step", data: "x" }]);
  });
});

describe("readStream", () => {
  it("reconnects after a dropped connection and resumes with Last-Event-ID", async () => {
    let n = 0;
    const seen: Record<string, string>[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init: RequestInit) => {
        seen.push(init.headers as Record<string, string>);
        n++;
        if (n === 1) {
          // first connection delivers one step, then the network drops
          let pulls = 0;
          const body = new ReadableStream({
            pull(c) {
              if (pulls++ === 0) c.enqueue(new TextEncoder().encode("id: 1\nevent: step\ndata: a\n\n"));
              else c.error(new Error("connection reset"));
            },
          });
          return new Response(body);
        }
        return new Response("id: 2\nevent: step\ndata: b\n\nevent: done\ndata: {}\n\n");
      }),
    );
    const events: string[] = [];
    await readStream("/s", { Authorization: "Bearer t" }, (e) => events.push(`${e.event}:${e.data}`), new AbortController().signal);
    expect(events).toEqual(["step:a", "step:b", "done:{}"]);
    expect(seen[1]["Last-Event-ID"]).toBe("1");
    expect(seen[0].Authorization).toBe("Bearer t"); // the token goes in a header, never in the URL
  });
});
