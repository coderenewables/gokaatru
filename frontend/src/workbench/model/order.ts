import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import type { Schemas } from "../../api/client";
import { api, unwrap } from "../api";
import { invalidateCampaign } from "../invalidate";
import { runOperation } from "./operations";
import { type Step, forServer, usePipeline } from "./store";

export type Ordered = Schemas["OrderPipelineResult"];
export type StepReport = Schemas["StepReport"];

/** The pipeline in the server's order, with each step's status (P3-6): read again whenever a
 * step changes, and after anything changes the campaign (the key holds its session id). */
export function useOrder(sessionId: string, steps: Step[]) {
  const body = forServer(steps);
  return useQuery({
    queryKey: ["pipeline-order", sessionId, JSON.stringify(body)],
    enabled: steps.length > 0,
    retry: false,
    queryFn: async () =>
      unwrap(
        await api.POST("/api/sessions/{session_id}/operations/order_pipeline", {
          params: { path: { session_id: sessionId } },
          body: { steps: body },
        }),
      ),
  });
}

/** Run steps one at a time in the order given, each through its own route (decisions/0015.4),
 * stopping at the first that is refused, so nothing runs on an input that failed. */
export function useRunSteps(sessionId: string) {
  const client = useQueryClient();
  const [running, setRunning] = useState<string | null>(null);
  const run = async (ids: string[]): Promise<void> => {
    const { steps, recordRun } = usePipeline.getState();
    try {
      for (const id of ids) {
        const step = steps.find((candidate) => candidate.id === id);
        if (!step) continue;
        setRunning(id);
        const at = new Date().toISOString();
        try {
          recordRun(id, { result: await runOperation(sessionId, step.operation, step.parameters), at });
        } catch (error) {
          recordRun(id, { error: error instanceof Error ? error.message : String(error), at });
          break;
        } finally {
          await invalidateCampaign(client, sessionId);
        }
      }
    } finally {
      setRunning(null);
    }
  };
  return { run, running };
}
