import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import type { Schemas } from "../../api/client";
import { api, unwrap } from "../api";
import { instrumentsKey } from "../datatree/DataPanel";
import { invalidateCampaign } from "../invalidate";
import { crossfilter, useSelection } from "../selection/store";
import {
  defaultInstrument,
  flagProblem,
  instrumentColumns,
  reasonLabel,
  selectionFlagBody,
} from "./flagForm";

type Preview = Schemas["ApplyCleaningRulePreview"];

export function PreviewSummary({ preview }: { preview: Preview }) {
  const columns = Object.entries(preview.changes.columns);
  return (
    <div className="gk-preview" aria-live="polite">
      {preview.description && <p className="gk-muted">{preview.description}</p>}
      <p>
        <strong>{preview.records_affected}</strong> values would be set missing
        {preview.selected_records !== null && preview.selected_records !== undefined
          ? `, on ${preview.selected_records} selected records`
          : ""}
        .
      </p>
      <ul className="gk-preview-columns" aria-label="Values set missing by column">
        {columns.map(([column, change]) => (
          <li key={column}>
            {column}: {change.set_missing}
          </li>
        ))}
      </ul>
      {preview.order_dependence.warning && <p className="gk-warning">{preview.order_dependence.warning}</p>}
    </div>
  );
}

/** Flag the selection (plan §3.3 "Timeline", "Scatter"): the columns of an instrument, a
 * reason and a note, a preview of what would change, then apply. One application is one
 * exclude_selection rule, one log entry and one undo step. */
export function FlagSection({ sessionId }: { sessionId: string }) {
  const client = useQueryClient();
  const terms = useSelection((state) => state.terms);
  const clearAll = useSelection((state) => state.clearAll);
  const definition = useMemo(() => crossfilter(terms), [terms]);

  const instruments = useQuery({
    queryKey: instrumentsKey(sessionId),
    queryFn: async () =>
      unwrap(
        await api.POST("/api/sessions/{session_id}/operations/list_instruments", {
          params: { path: { session_id: sessionId } },
          body: {},
        }),
      ),
  });
  const rules = useQuery({
    queryKey: ["cleaning-rules", sessionId],
    queryFn: async () =>
      unwrap(
        await api.POST("/api/sessions/{session_id}/operations/list_cleaning_rules", {
          params: { path: { session_id: sessionId } },
          body: {},
        }),
      ),
  });
  const listed = (instruments.data?.instruments ?? []).filter((instrument) => instrument.in_data);

  const [instrumentName, setInstrumentName] = useState("");
  const instrument = listed.find((item) => item.name === instrumentName) ?? defaultInstrument(listed);
  const columns = instrumentColumns(instrument);
  const [unticked, setUnticked] = useState<Set<string>>(new Set());
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [done, setDone] = useState("");
  const ticked = columns.filter((column) => !unticked.has(column));
  const problem = flagProblem(ticked, reason, note);
  const body = definition && !problem ? selectionFlagBody(definition, ticked, reason, note) : null;

  const preview = useMutation({
    mutationFn: async () => {
      if (!body) throw new Error(problem ?? "Nothing is selected");
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
      if (!body) throw new Error(problem ?? "Nothing is selected");
      return unwrap(
        await api.POST("/api/sessions/{session_id}/operations/apply_cleaning_rule", {
          params: { path: { session_id: sessionId } },
          body,
        }),
      );
    },
    onSuccess: async (result) => {
      setDone(
        `Flagged ${result.records_affected} values of ${ticked.join(", ")} as ${reasonLabel(reason).toLowerCase()} (rule ${result.order_dependence.sequence}). Ctrl+Z undoes it.`,
      );
      clearAll();
      preview.reset();
      await invalidateCampaign(client, sessionId);
    },
  });

  // A changed selection or form makes the shown preview stale.
  const { reset } = preview;
  useEffect(() => reset(), [definition, instrumentName, unticked, reason, note, reset]);

  if (!definition) {
    return done ? (
      <section aria-labelledby="gk-flag-heading" className="gk-inspector-section">
        <h2 id="gk-flag-heading">Flag</h2>
        <p role="status">{done}</p>
      </section>
    ) : null;
  }

  return (
    <section aria-labelledby="gk-flag-heading" className="gk-inspector-section gk-flag">
      <h2 id="gk-flag-heading">Flag the selection</h2>
      <label className="gk-field">
        <span>Instrument</span>
        <select
          value={instrument?.name ?? ""}
          onChange={(event) => {
            setInstrumentName(event.target.value);
            setUnticked(new Set());
          }}
        >
          {listed.map((item) => (
            <option key={item.name} value={item.name}>
              {item.name} ({item.height_m} m)
            </option>
          ))}
        </select>
      </label>
      <fieldset className="gk-columns">
        <legend>Columns set missing</legend>
        {columns.map((column) => (
          <label key={column} className="gk-check">
            <input
              type="checkbox"
              checked={!unticked.has(column)}
              onChange={(event) => {
                const next = new Set(unticked);
                if (event.target.checked) next.delete(column);
                else next.add(column);
                setUnticked(next);
              }}
            />
            {column}
          </label>
        ))}
      </fieldset>
      <label className="gk-field">
        <span>Reason</span>
        <select value={reason} onChange={(event) => setReason(event.target.value)}>
          <option value="">Choose a reason</option>
          {(rules.data?.manual_flag_reasons ?? []).map((code) => (
            <option key={code} value={code}>
              {reasonLabel(code)}
            </option>
          ))}
        </select>
      </label>
      <label className="gk-field">
        <span>Note{reason === "other" ? " (required)" : ""}</span>
        <textarea value={note} rows={2} onChange={(event) => setNote(event.target.value)} />
      </label>
      {problem && <p className="gk-muted">{problem}</p>}
      <div className="gk-actions">
        <button type="button" className="gk-button" disabled={!body || preview.isPending} onClick={() => preview.mutate()}>
          Preview
        </button>
        <button
          type="button"
          className="gk-button gk-button-primary"
          disabled={!body || !preview.data || apply.isPending}
          title={preview.data ? undefined : "Preview first: it shows what would change"}
          onClick={() => apply.mutate()}
        >
          Apply flag
        </button>
      </div>
      {preview.data && <PreviewSummary preview={preview.data} />}
      {(preview.error ?? apply.error) && <p role="alert">{(preview.error ?? apply.error)?.message}</p>}
    </section>
  );
}
