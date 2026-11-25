import { tableFromIPC } from "apache-arrow";

import { api, refusal, unwrap } from "../api";
import { type FlagBand, flagBand, parseWindow, type SeriesWindow } from "./helpers";

/** The query-key prefix of every flag-interval query of a campaign: invalidate it after a
 * change to the flags so each chart that shows them reads them again. */
export function flagsKey(sessionId: string): readonly ["flags", string] {
  return ["flags", sessionId];
}

/** The query-key prefix of every series window of a campaign. */
export function seriesKey(sessionId: string): readonly ["series", string] {
  return ["series", sessionId];
}

/** One window of the series as Arrow (decisions/0005). The generated client is JSON-only, so
 * this is a plain fetch; ``start`` and ``end`` empty ask for the whole record. */
export async function fetchSeries(
  sessionId: string,
  channels: string[],
  start: string,
  end: string,
  buckets: number,
  signal?: AbortSignal,
): Promise<SeriesWindow> {
  const response = await fetch(`/api/sessions/${sessionId}/series`, {
    method: "POST",
    signal,
    headers: { "Content-Type": "application/json", "X-GoKaatru-Session": sessionId },
    body: JSON.stringify({ channels: channels.join(","), start, end, buckets, selection: "" }),
  });
  if (!response.ok) {
    const text = await response.text();
    let detail: unknown = text;
    try {
      detail = (JSON.parse(text) as { detail?: unknown }).detail ?? text;
    } catch {
      // A body that is not JSON is the message itself.
    }
    throw new Error(typeof detail === "string" ? detail : refusal({ detail }));
  }
  return parseWindow(tableFromIPC(new Uint8Array(await response.arrayBuffer())));
}

export async function fetchFlagBands(
  sessionId: string,
  channels: string[],
  start: string,
  end: string,
  stepMs: number,
): Promise<FlagBand[]> {
  const result = unwrap(
    await api.POST("/api/sessions/{session_id}/operations/get_flag_intervals", {
      params: { path: { session_id: sessionId } },
      body: { channels: channels.join(","), start, end },
    }),
  );
  return channels.flatMap((channel) =>
    (result.channels[channel]?.intervals ?? []).map((interval) => flagBand(channel, interval, stepMs)),
  );
}
