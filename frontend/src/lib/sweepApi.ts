// HTTP client for the scenario-sweep engine (design doc §7.6).
//
// Kept apart from `api.ts` so the sweep surface can grow without adding to a file that
// is already the largest in the frontend. Same conventions: the session header is derived
// from the path, and a non-2xx response becomes an Error carrying the backend's `detail`.
import type {
  SweepAxes,
  SweepEstimate,
  SweepManifest,
  SweepOutcome,
  SweepProgressEvent,
  SweepRequestBody,
  SweepSummary,
} from "../types/sweep";

const SESSION_HEADER_NAME = "X-GoKaatru-Session";

function joinUrl(baseUrl: string, path: string): string {
  const trimmed = baseUrl.endsWith("/") ? baseUrl.slice(0, -1) : baseUrl;
  return `${trimmed}${path}`;
}

function sessionHeaders(sessionId: string, extra: Record<string, string> = {}): Headers {
  const headers = new Headers(extra);
  headers.set("Accept", "application/json");
  headers.set(SESSION_HEADER_NAME, sessionId);
  return headers;
}

async function readError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload?.detail === "string") return payload.detail;
  } catch {
    /* fall through to the status text */
  }
  return response.statusText || `HTTP ${response.status}`;
}

async function requestJson<T>(
  baseUrl: string,
  sessionId: string,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = sessionHeaders(sessionId);
  if (init.body !== undefined) headers.set("Content-Type", "application/json");
  const response = await fetch(joinUrl(baseUrl, path), { ...init, headers });
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as T;
}

/** Which axis levels this session can actually run, and why not where it cannot. */
export async function getSweepAxes(baseUrl: string, sessionId: string): Promise<SweepAxes> {
  return requestJson<SweepAxes>(baseUrl, sessionId, `/api/sessions/${sessionId}/sweep/axes`);
}

/** Price a specification without running it — the designer's cost counter (§9.1). */
export async function estimateSweep(
  baseUrl: string,
  sessionId: string,
  body: SweepRequestBody,
): Promise<SweepEstimate> {
  return requestJson<SweepEstimate>(baseUrl, sessionId, `/api/sessions/${sessionId}/sweep/estimate`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** Run a sweep to completion. Prefer `streamSweep` for anything a user is watching. */
export async function runSweep(
  baseUrl: string,
  sessionId: string,
  body: SweepRequestBody,
): Promise<SweepOutcome> {
  return requestJson<SweepOutcome>(baseUrl, sessionId, `/api/sessions/${sessionId}/sweep/run`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function listSweeps(baseUrl: string, sessionId: string): Promise<SweepSummary[]> {
  const payload = await requestJson<{ sweeps: SweepSummary[] }>(
    baseUrl,
    sessionId,
    `/api/sessions/${sessionId}/sweep`,
  );
  return payload.sweeps;
}

export async function getSweep(
  baseUrl: string,
  sessionId: string,
  sweepId: string,
): Promise<SweepOutcome> {
  return requestJson<SweepOutcome>(baseUrl, sessionId, `/api/sessions/${sessionId}/sweep/${sweepId}`);
}

/** One scenario's materialised runconfig — the file an analyst takes away (§7.13). */
export async function getScenarioRunconfig(
  baseUrl: string,
  sessionId: string,
  sweepId: string,
  configHash: string,
): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>(
    baseUrl,
    sessionId,
    `/api/sessions/${sessionId}/sweep/${sweepId}/scenarios/${configHash}/runconfig`,
  );
}

/**
 * Run a sweep, invoking `onEvent` as each scenario completes.
 *
 * Read as a stream rather than awaited whole: the Run Monitor exists to show the spread
 * forming, and buffering the response until the run finished would deliver every event
 * at once, after the only moment they were useful.
 *
 * Returns the final manifest when the stream carried one.
 */
export async function streamSweep(
  baseUrl: string,
  sessionId: string,
  body: SweepRequestBody,
  onEvent: (event: SweepProgressEvent) => void,
  signal?: AbortSignal,
): Promise<SweepManifest | null> {
  const headers = sessionHeaders(sessionId, { "Content-Type": "application/json" });
  headers.set("Accept", "text/event-stream");
  const response = await fetch(joinUrl(baseUrl, `/api/sessions/${sessionId}/sweep/run/stream`), {
    method: "POST",
    body: JSON.stringify(body),
    headers,
    signal,
  });
  if (!response.ok) throw new Error(await readError(response));
  if (response.body == null) throw new Error("The sweep stream returned no body");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let manifest: SweepManifest | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // SSE frames are separated by a blank line; a partial frame stays in the buffer.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const line = frame.split("\n").find((entry) => entry.startsWith("data: "));
      if (!line) continue;
      let event: SweepProgressEvent;
      try {
        event = JSON.parse(line.slice("data: ".length)) as SweepProgressEvent;
      } catch {
        continue; // a malformed frame must not end the run
      }
      if (event.manifest) manifest = event.manifest;
      onEvent(event);
    }
  }
  return manifest;
}
