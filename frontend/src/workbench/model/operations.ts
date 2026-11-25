import { useQuery } from "@tanstack/react-query";

import { api, refusal, unwrap } from "../api";
import type { JsonSchema } from "../forms/schema";

/** One declared operation, as GET /operations lists it (server/operations.py). */
export interface OperationInfo {
  name: string;
  description: string;
  effect: "read" | "change";
  stage: string;
  canvas: boolean;
  network: boolean;
  disclosure: string[];
  standards: string[];
  dry_run: boolean;
  selectable: boolean;
  reads: string[];
  writes: string[];
  parameters: JsonSchema;
}

/** The stages the Model palette offers, in pipeline order. Loading data, cleaning and
 * acquiring the reanalysis are Prepare's (decisions/0014.7), sweeps are Run's. */
export const MODEL_STAGES = [
  "homogeneity",
  "shear",
  "extrapolation",
  "air_density",
  "ltc",
  "ltc_ml",
  "ensemble",
  "clipping",
  "uncertainty",
  "statistics",
  "analysis",
  "atmosphere",
  "diagnostics",
] as const;

export const STAGE_LABELS: Record<string, string> = {
  homogeneity: "Reference homogeneity",
  shear: "Shear",
  extrapolation: "Hub height",
  air_density: "Air density",
  ltc: "Long-term correction",
  ltc_ml: "Long-term correction (learned)",
  ensemble: "Ensemble",
  clipping: "Long-term window",
  uncertainty: "Uncertainty",
  statistics: "Statistics",
  analysis: "Analysis",
  atmosphere: "Atmosphere",
  diagnostics: "Diagnostics",
};

/** An operation's name as a step's title: run_ltc_variance_ratio, "run ltc variance ratio". */
export function titleOf(name: string): string {
  return name.replace(/_/g, " ");
}

/** What a pipeline step may be: on the canvas, no credentials (the server refuses those too),
 * and in a Model stage. */
export function paletteOf(operations: OperationInfo[]): Map<string, OperationInfo[]> {
  const stages = new Map<string, OperationInfo[]>(MODEL_STAGES.map((stage) => [stage, []]));
  for (const operation of operations) {
    if (operation.canvas && !operation.network && stages.has(operation.stage)) stages.get(operation.stage)?.push(operation);
  }
  for (const [stage, listed] of stages) {
    if (listed.length === 0) stages.delete(stage);
    else listed.sort((a, b) => (a.effect === b.effect ? a.name.localeCompare(b.name) : a.effect === "change" ? -1 : 1));
  }
  return stages;
}

export function useOperations() {
  return useQuery({
    queryKey: ["operations"],
    staleTime: Infinity,
    queryFn: async () => unwrap(await api.GET("/api/operations")) as unknown as OperationInfo[],
  });
}

/** Call one operation through its generated route (decisions/0015.4): each step is a logged
 * operation of its own. The generated client is typed per route, so a name chosen at run time
 * goes through fetch with the same body. */
export async function runOperation(sessionId: string, name: string, body: Record<string, unknown>): Promise<unknown> {
  const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/operations/${encodeURIComponent(name)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-GoKaatru-Session": sessionId },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(refusal(payload));
  return payload;
}
