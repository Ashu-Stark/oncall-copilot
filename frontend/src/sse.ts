// Server-Sent Events over fetch (EventSource cannot send an Authorization header, and tokens do not belong in URLs).

export interface SseEvent {
  id?: string;
  event: string;
  data: string;
}

/** Splits a text stream into SSE events. Feed it chunks as they arrive; it keeps partial events between calls. */
export class SseParser {
  private buf = "";

  push(chunk: string): SseEvent[] {
    this.buf += chunk.replace(/\r\n/g, "\n");
    const out: SseEvent[] = [];
    let i: number;
    while ((i = this.buf.indexOf("\n\n")) >= 0) {
      const block = this.buf.slice(0, i);
      this.buf = this.buf.slice(i + 2);
      const ev: SseEvent = { event: "message", data: "" };
      const data: string[] = [];
      for (const line of block.split("\n")) {
        if (!line || line.startsWith(":")) continue; // comment = keep-alive
        const c = line.indexOf(":");
        const field = c < 0 ? line : line.slice(0, c);
        const value = c < 0 ? "" : line.slice(c + 1).replace(/^ /, "");
        if (field === "event") ev.event = value;
        else if (field === "data") data.push(value);
        else if (field === "id") ev.id = value;
      }
      if (data.length || ev.event !== "message") {
        ev.data = data.join("\n");
        out.push(ev);
      }
    }
    return out;
  }
}

/** Reads an SSE endpoint until it ends or `signal` aborts. Reconnects (with Last-Event-ID) if the connection drops. */
export async function readStream(
  url: string,
  headers: Record<string, string>,
  onEvent: (e: SseEvent) => void,
  signal: AbortSignal,
  retries = 3,
): Promise<void> {
  let lastId: string | undefined;
  for (let attempt = 0; attempt <= retries && !signal.aborted; attempt++) {
    try {
      const res = await fetch(url, { headers: { ...headers, Accept: "text/event-stream", ...(lastId ? { "Last-Event-ID": lastId } : {}) }, signal });
      if (!res.ok || !res.body) throw new Error(`stream failed (${res.status})`);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      const parser = new SseParser();
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        for (const ev of parser.push(decoder.decode(value, { stream: true }))) {
          if (ev.id) lastId = ev.id;
          onEvent(ev);
          if (ev.event === "done") return;
        }
      }
    } catch (e) {
      if (signal.aborted) return;
      if (attempt === retries) throw e;
      await new Promise((r) => setTimeout(r, 500 * (attempt + 1)));
    }
  }
}
