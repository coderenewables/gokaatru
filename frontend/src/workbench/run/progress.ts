// The run's progress events (server/core/sweep.py `SweepProgress.as_record`) folded into what
// the monitor shows. Pure, so the reducer is tested without a stream.

export interface SweepManifestView {
  sweep_id: string;
  stopped_early?: boolean;
  fixed_prefix_hash?: string;
  not_swept_statement?: string;
  diagnosis?: string | null;
  gate_failures?: Record<string, number>;
  counts?: {
    planned: number;
    run: number;
    completed: number;
    failed: number;
    admissible: number;
    inadmissible: number;
    duplicates_skipped?: number;
  };
  duplicates_skipped?: Array<{ shear_fit_policy: string; reference_policy: string; same_as: string }>;
}

export interface ProgressEvent {
  event: string;
  completed?: number;
  total?: number;
  config_hash?: string | null;
  detail?: Record<string, unknown>;
  manifest?: SweepManifestView;
  error?: string;
}

export interface LogLine {
  id: number;
  kind: "scenario_completed" | "scenario_failed" | "scenario_skipped_duplicate" | "prefix_started" | "prefix_completed";
  text: string;
}

export interface RunState {
  phase: "idle" | "running" | "finished" | "error";
  completed: number;
  total: number;
  scenarios: { ok: number; inadmissible: number; failed: number; duplicates: number };
  prefixes: { started: number; completed: number };
  log: LogLine[];
  manifest: SweepManifestView | null;
  error: string | null;
}

/** The newest events kept for display; a 9,000-leaf sweep would otherwise hold them all. */
export const LOG_LIMIT = 200;

export const IDLE_RUN: RunState = {
  phase: "idle",
  completed: 0,
  total: 0,
  scenarios: { ok: 0, inadmissible: 0, failed: 0, duplicates: 0 },
  prefixes: { started: 0, completed: 0 },
  log: [],
  manifest: null,
  error: null,
};

export const STARTED_RUN: RunState = { ...IDLE_RUN, phase: "running" };

const short = (hash: string | null | undefined) => (hash ? hash.slice(0, 8) : "unknown");

function describe(event: ProgressEvent): Omit<LogLine, "id"> | null {
  const detail = event.detail ?? {};
  const prefix = Array.isArray(detail.shear_prefix) ? (detail.shear_prefix as unknown[]).filter((v) => v !== null).join(" / ") : "";
  switch (event.event) {
    case "scenario_completed":
      return {
        kind: "scenario_completed",
        text: `Scenario ${short(event.config_hash)} completed${detail.admissible === false ? ", inadmissible" : ""}`,
      };
    case "scenario_failed":
      return {
        kind: "scenario_failed",
        text: `Scenario ${short(event.config_hash)} failed: ${event.error ?? String(detail.error ?? "no reason given")}`,
      };
    case "scenario_skipped_duplicate":
      return {
        kind: "scenario_skipped_duplicate",
        text: `Skipped ${String(detail.shear_fit_policy)} / ${String(detail.reference_policy)}: it repeats ${short(String(detail.same_as))}`,
      };
    case "prefix_started":
      return { kind: "prefix_started", text: `Shear table started: ${prefix}` };
    case "prefix_completed":
      return { kind: "prefix_completed", text: `Shear table done: ${prefix}` };
    default:
      return null;
  }
}

/** One event applied to the state. `sweep_stopped` is not terminal: the server follows it with
 * `sweep_finished`, whose manifest says `stopped_early`. */
export function reduceRun(state: RunState, event: ProgressEvent): RunState {
  const counted = {
    ...state,
    completed: event.completed ?? state.completed,
    total: event.total ?? state.total,
  };
  if (event.event === "sweep_error") {
    return { ...counted, phase: "error", error: event.error ?? "The sweep failed with no reason given" };
  }
  if (event.event === "sweep_finished") return { ...counted, phase: "finished", manifest: event.manifest ?? null };
  const scenarios = { ...state.scenarios };
  const prefixes = { ...state.prefixes };
  if (event.event === "scenario_completed") {
    if (event.detail?.admissible === false) scenarios.inadmissible += 1;
    else scenarios.ok += 1;
  }
  if (event.event === "scenario_failed") scenarios.failed += 1;
  if (event.event === "scenario_skipped_duplicate") scenarios.duplicates += 1;
  if (event.event === "prefix_started") prefixes.started += 1;
  if (event.event === "prefix_completed") prefixes.completed += 1;
  const line = describe(event);
  const log = line ? [...state.log, { ...line, id: (state.log.at(-1)?.id ?? 0) + 1 }].slice(-LOG_LIMIT) : state.log;
  return { ...counted, scenarios, prefixes, log };
}

/** The data frames of an event stream's text: frames end at a blank line, and a partial frame
 * stays in the remainder for the next chunk. A malformed frame is skipped, not fatal. */
export function parseFrames(buffer: string): { events: ProgressEvent[]; rest: string } {
  const frames = buffer.split("\n\n");
  const rest = frames.pop() ?? "";
  const events: ProgressEvent[] = [];
  for (const frame of frames) {
    const line = frame.split("\n").find((entry) => entry.startsWith("data: "));
    if (!line) continue;
    try {
      events.push(JSON.parse(line.slice("data: ".length)) as ProgressEvent);
    } catch {
      continue;
    }
  }
  return { events, rest };
}
