import { create } from "zustand";

import { readStored, writeStored } from "../storage";

/** One step of the campaign's pipeline: an operation and its parameters (decisions/0015.1).
 * ``position`` is where the canvas drew it once moved; unmoved steps are laid out by order. */
export interface Step {
  id: string;
  operation: string;
  parameters: Record<string, unknown>;
  position?: { x: number; y: number };
}

/** Where the pipeline came from when a sweep scenario was loaded into it (decisions/0015.1),
 * and whether the campaign is still as that sweep found it. */
export interface Origin {
  sweepId: string;
  configHash: string;
  prefixMatches: boolean;
  prefixNote?: string | null;
}

/** What running a step gave, kept for the Step panel until the step is run again. */
export interface StepRun {
  result?: unknown;
  error?: string;
  at: string;
}

interface PipelineState {
  sessionId: string | null;
  steps: Step[];
  selected: string | null;
  runs: Record<string, StepRun>;
  origin: Origin | null;
  open: (sessionId: string) => void;
  add: (operation: string, parameters?: Record<string, unknown>) => string;
  remove: (id: string) => void;
  setParameters: (id: string, parameters: Record<string, unknown>) => void;
  move: (id: string, position: { x: number; y: number }) => void;
  select: (id: string | null) => void;
  replace: (steps: Step[], origin?: Origin) => void;
  recordRun: (id: string, run: StepRun) => void;
}

/** The pipeline being edited is view state (decisions/0015.5): kept in this browser for the
 * campaign, saved on the server only when named. */
export function pipelineKey(sessionId: string): string {
  return `gk-pipeline-v1-${sessionId}`;
}

function stored(sessionId: string): Step[] {
  const raw = readStored(pipelineKey(sessionId));
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? (parsed as Step[]) : [];
  } catch {
    return [];
  }
}

function keep(sessionId: string | null, steps: Step[]): void {
  if (sessionId) writeStored(pipelineKey(sessionId), JSON.stringify(steps));
}

/** A step id from its operation, unique in the pipeline: run_ltc_variance_ratio, variance_ratio-2. */
export function newStepId(operation: string, steps: Step[]): string {
  const base = operation.replace(/^(run_ltc_|calculate_|build_|compute_|run_)/, "");
  const taken = new Set(steps.map((step) => step.id));
  if (!taken.has(base)) return base;
  let index = 2;
  while (taken.has(`${base}-${index}`)) index += 1;
  return `${base}-${index}`;
}

export const usePipeline = create<PipelineState>((set, get) => ({
  sessionId: null,
  steps: [],
  selected: null,
  runs: {},
  origin: null,
  open: (sessionId) => {
    if (get().sessionId === sessionId) return;
    set({ sessionId, steps: stored(sessionId), selected: null, runs: {}, origin: null });
  },
  add: (operation, parameters = {}) => {
    const steps = get().steps;
    const id = newStepId(operation, steps);
    const next = [...steps, { id, operation, parameters }];
    keep(get().sessionId, next);
    set({ steps: next, selected: id });
    return id;
  },
  remove: (id) => {
    const next = get().steps.filter((step) => step.id !== id);
    keep(get().sessionId, next);
    const { [id]: _dropped, ...runs } = get().runs;
    set({ steps: next, selected: get().selected === id ? null : get().selected, runs });
  },
  setParameters: (id, parameters) => {
    const next = get().steps.map((step) => (step.id === id ? { ...step, parameters } : step));
    keep(get().sessionId, next);
    set({ steps: next });
  },
  move: (id, position) => {
    const next = get().steps.map((step) => (step.id === id ? { ...step, position } : step));
    keep(get().sessionId, next);
    set({ steps: next });
  },
  select: (id) => set({ selected: id }),
  replace: (steps, origin) => {
    keep(get().sessionId, steps);
    set({ steps, selected: steps[0]?.id ?? null, runs: {}, origin: origin ?? null });
  },
  recordRun: (id, run) => set({ runs: { ...get().runs, [id]: run } }),
}));

/** The steps as the server orders them: id, operation and parameters, without the drawing. */
export function forServer(steps: Step[]): { id: string; operation: string; parameters: Record<string, unknown> }[] {
  return steps.map(({ id, operation, parameters }) => ({ id, operation, parameters }));
}
