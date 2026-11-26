import type { Step } from "./store";

export interface Edge {
  source: string;
  target: string;
  artifact: string;
}

export const COLUMN_WIDTH = 300;
export const ROW_HEIGHT = 150;

/** Where each step is drawn: where it was moved to, else a column for how many steps it waits
 * on (its depth along the edges) and a row within that column, in the server's order. */
export function layoutSteps(steps: Step[], order: string[], edges: Edge[]): Record<string, { x: number; y: number }> {
  const known = new Set(steps.map((step) => step.id));
  const sequence = [...order.filter((id) => known.has(id)), ...steps.map((step) => step.id).filter((id) => !order.includes(id))];
  const depth: Record<string, number> = {};
  for (const id of sequence) {
    const incoming = edges.filter((edge) => edge.target === id && edge.source in depth);
    depth[id] = incoming.length ? Math.max(...incoming.map((edge) => depth[edge.source] + 1)) : 0;
  }
  const rows: Record<number, number> = {};
  const placed: Record<string, { x: number; y: number }> = {};
  for (const id of sequence) {
    const column = depth[id];
    const row = rows[column] ?? 0;
    rows[column] = row + 1;
    placed[id] = { x: 20 + column * COLUMN_WIDTH, y: 20 + row * ROW_HEIGHT };
  }
  for (const step of steps) if (step.position) placed[step.id] = step.position;
  return placed;
}

/** The artifacts a step reads from another step of the pipeline, its ports; what it reads from
 * the session as it stands is listed apart rather than drawn as a port each. */
export function portsOf(stepId: string, inputs: Record<string, string[]> | undefined): { fromSteps: string[]; fromSession: string[] } {
  const fromSteps: string[] = [];
  const fromSession: string[] = [];
  for (const [artifact, sources] of Object.entries(inputs ?? {})) {
    (sources.some((source) => source !== stepId) ? fromSteps : fromSession).push(artifact);
  }
  return { fromSteps: fromSteps.sort(), fromSession: fromSession.sort() };
}

/** Why a status reads as it does, in a few words for the node's badge. */
export const STATUS_LABELS: Record<string, string> = {
  current: "current",
  changed: "changed",
  stale: "stale",
  not_run: "not run",
  upstream: "waits",
  invalid: "invalid",
  ready: "ready",
};
