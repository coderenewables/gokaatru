import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, unwrap } from "../api";
import { invalidateCampaign } from "../invalidate";

/** What an undo or redo reports, in a line for the status bar. */
export function historyLine(verb: "Undid" | "Redid", entry: { operation: string; parameters: Record<string, unknown> }): string {
  const rule = typeof entry.parameters.rule_type === "string" ? ` (${entry.parameters.rule_type})` : "";
  return `${verb} ${entry.operation.replace(/_/g, " ")}${rule}.`;
}

/** The campaign's history (decisions/0014.6: data changes only), and undo and redo through the
 * server's operation log, so the workbench, the assistant and MCP share one history. */
export function useHistory(sessionId: string) {
  const client = useQueryClient();
  const [said, setSaid] = useState("");
  const log = useQuery({
    queryKey: ["history", sessionId],
    queryFn: async () =>
      unwrap(
        await api.POST("/api/sessions/{session_id}/operations/get_operation_log", {
          params: { path: { session_id: sessionId } },
          body: { limit: 1 },
        }),
      ),
  });
  const prefix = useQuery({
    queryKey: ["prefix", sessionId],
    queryFn: async () =>
      unwrap(
        await api.POST("/api/sessions/{session_id}/operations/get_fixed_prefix_hash", {
          params: { path: { session_id: sessionId } },
          body: {},
        }),
      ),
  });
  const undo = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/sessions/{session_id}/operations/undo_last_change", {
          params: { path: { session_id: sessionId } },
          body: {},
        }),
      ),
    onSuccess: async (result) => {
      setSaid(historyLine("Undid", result.undone));
      await invalidateCampaign(client, sessionId);
    },
    onError: (error) => setSaid(error.message),
  });
  const redo = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/sessions/{session_id}/operations/redo_last_change", {
          params: { path: { session_id: sessionId } },
          body: {},
        }),
      ),
    onSuccess: async (result) => {
      setSaid(historyLine("Redid", result.redone));
      await invalidateCampaign(client, sessionId);
    },
    onError: (error) => setSaid(error.message),
  });
  const busy = undo.isPending || redo.isPending;
  return {
    log: log.data,
    prefix: prefix.data,
    said,
    canUndo: Boolean(log.data?.can_undo) && !busy,
    canRedo: Boolean(log.data?.can_redo) && !busy,
    undo: () => {
      if (log.data?.can_undo && !busy) undo.mutate();
    },
    redo: () => {
      if (log.data?.can_redo && !busy) redo.mutate();
    },
  };
}
