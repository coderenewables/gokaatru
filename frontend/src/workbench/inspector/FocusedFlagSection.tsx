import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "../api";
import { useFlagFocus } from "../flags/store";
import { invalidateCampaign } from "../invalidate";
import { reasonLabel } from "./flagForm";

const instant = (value: string) => new Date(value).toISOString().slice(0, 16).replace("T", " ") + " UTC";

/** The flag band the analyst clicked (plan §3.3 "Any flag band"): who or what created it,
 * when and why, and its removal in one click. Removing takes out the whole rule that set it,
 * replaying the rules after it, because rules depend on their order. */
export function FocusedFlagSection({ sessionId }: { sessionId: string }) {
  const client = useQueryClient();
  const focused = useFlagFocus((state) => state.focused);
  const clear = useFlagFocus((state) => state.clear);
  const log = useQuery({
    queryKey: ["cleaning-log", sessionId],
    enabled: focused !== null,
    queryFn: async () =>
      unwrap(
        await api.POST("/api/sessions/{session_id}/operations/get_cleaning_log", {
          params: { path: { session_id: sessionId } },
          body: {},
        }),
      ),
  });
  const entries = log.data?.entries ?? [];
  const index = focused ? entries.findIndex((entry) => entry.sequence === focused.interval.rule_sequence) : -1;
  const entry = index >= 0 ? entries[index] : undefined;
  const note = entry && typeof entry.params.note === "string" ? entry.params.note : "";

  const remove = useMutation({
    mutationFn: async () => {
      if (index < 0) throw new Error("The rule that set this flag is no longer in the cleaning log");
      return unwrap(
        await api.POST("/api/sessions/{session_id}/operations/undo_cleaning_rule", {
          params: { path: { session_id: sessionId } },
          body: { entry_index: index },
        }),
      );
    },
    onSuccess: async () => {
      clear();
      await invalidateCampaign(client, sessionId);
    },
  });

  if (!focused) return null;
  const { sensor, interval } = focused;
  return (
    <section aria-labelledby="gk-focused-heading" className="gk-inspector-section gk-focused">
      <h2 id="gk-focused-heading">Flag on {sensor}</h2>
      <dl className="gk-facts">
        <dt>Records</dt>
        <dd>
          {interval.records}, {instant(interval.first)} to {instant(interval.last)}
        </dd>
        <dt>Reason</dt>
        <dd>{reasonLabel(interval.reason)}</dd>
        <dt>Rule</dt>
        <dd>
          {interval.rule_sequence}. {interval.rule_type}
          {entry?.description ? `: ${entry.description}` : ""}
        </dd>
        <dt>By</dt>
        <dd>{interval.actor}</dd>
        <dt>When</dt>
        <dd>{instant(interval.flagged_at)}</dd>
        {note && (
          <>
            <dt>Note</dt>
            <dd>{note}</dd>
          </>
        )}
      </dl>
      <div className="gk-actions">
        <button type="button" className="gk-button" disabled={remove.isPending || index < 0} onClick={() => remove.mutate()}>
          Remove rule {interval.rule_sequence}
        </button>
        <button type="button" className="gk-button" onClick={clear}>
          Close
        </button>
      </div>
      {remove.error && <p role="alert">{remove.error.message}</p>}
    </section>
  );
}
