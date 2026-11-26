import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { api, unwrap } from "../api";
import { useRuleDraft } from "../flags/draft";
import { invalidateCampaign } from "../invalidate";
import { PreviewSummary } from "./FlagSection";

/** A rule a view proposed (the rose's tower-shadow rule): what it does, a preview, apply. */
export function RuleDraftSection({ sessionId }: { sessionId: string }) {
  const client = useQueryClient();
  const draft = useRuleDraft((state) => state.draft);
  const clear = useRuleDraft((state) => state.clear);
  const body = draft
    ? { rule_type: draft.rule_type, sensor: draft.sensor, params: JSON.stringify(draft.params), start_date: "", end_date: "" }
    : null;

  const preview = useMutation({
    mutationKey: ["rule-draft-preview", body?.params, body?.sensor],
    mutationFn: async () => {
      if (!body) throw new Error("No rule is proposed");
      return unwrap(
        await api.POST("/api/sessions/{session_id}/operations/apply_cleaning_rule/preview", {
          params: { path: { session_id: sessionId } },
          body,
        }),
      );
    },
  });
  const apply = useMutation({
    mutationFn: async () => {
      if (!body) throw new Error("No rule is proposed");
      return unwrap(
        await api.POST("/api/sessions/{session_id}/operations/apply_cleaning_rule", {
          params: { path: { session_id: sessionId } },
          body,
        }),
      );
    },
    onSuccess: async () => {
      clear();
      preview.reset();
      await invalidateCampaign(client, sessionId);
    },
  });

  // A new proposal makes the shown preview stale.
  const { reset } = preview;
  useEffect(() => reset(), [draft, reset]);

  if (!draft) return null;
  return (
    <section aria-labelledby="gk-draft-heading" className="gk-inspector-section gk-flag">
      <h2 id="gk-draft-heading">Proposed rule</h2>
      <p>{draft.label}</p>
      <div className="gk-actions">
        <button type="button" className="gk-button" disabled={preview.isPending} onClick={() => preview.mutate()}>
          Preview
        </button>
        <button
          type="button"
          className="gk-button gk-button-primary"
          disabled={!preview.data || apply.isPending}
          title={preview.data ? undefined : "Preview first: it shows what would change"}
          onClick={() => apply.mutate()}
        >
          Apply rule
        </button>
        <button
          type="button"
          className="gk-button"
          onClick={() => {
            clear();
            preview.reset();
          }}
        >
          Discard
        </button>
      </div>
      {preview.data && <PreviewSummary preview={preview.data} />}
      {(preview.error ?? apply.error) && <p role="alert">{(preview.error ?? apply.error)?.message}</p>}
    </section>
  );
}
