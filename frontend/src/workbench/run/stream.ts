import { SESSION_HEADER } from "../../api/client";
import { parseFrames, type ProgressEvent } from "./progress";
import type { SweepRequest } from "./design";

async function refusal(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload?.detail === "string") return payload.detail;
    if (payload?.detail !== undefined) return JSON.stringify(payload.detail);
  } catch {
    /* the status text is the fallback */
  }
  return response.statusText || `HTTP ${response.status}`;
}

/** Run a sweep and hand each progress event over as it arrives. The generated client cannot
 * read a stream, so this is fetch and a reader. Resolves when the stream ends. */
export async function streamSweepRun(
  sessionId: string,
  body: SweepRequest,
  onEvent: (event: ProgressEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/sweep/run/stream`, {
    method: "POST",
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json", Accept: "text/event-stream", [SESSION_HEADER]: sessionId },
    signal,
  });
  if (!response.ok) throw new Error(await refusal(response));
  if (response.body === null) throw new Error("The sweep stream returned no body");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const { events, rest } = parseFrames(buffer);
    buffer = rest;
    for (const event of events) onEvent(event);
  }
}
