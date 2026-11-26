import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import type { Schemas } from "../../api/client";
import { api, unwrap } from "../api";
import { invalidateCampaign } from "../invalidate";
import { useCampaign } from "../shell/context";

type Instrument = Schemas["Instrument"];
type Removal = Schemas["RemoveSensorsResult"];

const inSession = (sessionId: string) => ({ params: { path: { session_id: sessionId } } });

/** Columns a removal takes out of the working and raw data, each named once. */
export function droppedColumns(result: Pick<Removal, "columns_dropped">): string[] {
  return [...new Set(Object.values(result.columns_dropped).flat())].sort();
}

/** Take sensors out of the analysis (remove_sensors): their columns leave the working data and
 * the mapping, kept by the server so the change is undone like any other. Previewed first. */
export function RemovalSection({ instruments }: { instruments: Instrument[] }) {
  const { sessionId } = useCampaign();
  const client = useQueryClient();
  const [chosen, setChosen] = useState<string[]>([]);
  const preview = useMutation({
    mutationFn: async (sensor_names: string[]) =>
      unwrap(await api.POST("/api/sessions/{session_id}/operations/remove_sensors/preview", { ...inSession(sessionId), body: { sensor_names } })),
  });
  const apply = useMutation({
    mutationFn: async (sensor_names: string[]) =>
      unwrap(await api.POST("/api/sessions/{session_id}/operations/remove_sensors", { ...inSession(sessionId), body: { sensor_names } })),
    onSuccess: async () => {
      setChosen([]);
      preview.reset();
      await invalidateCampaign(client, sessionId);
    },
  });
  const present = instruments.filter((instrument) => instrument.in_data);
  if (present.length === 0) return null;

  const toggle = (name: string) => {
    preview.reset();
    apply.reset();
    setChosen((current) => (current.includes(name) ? current.filter((item) => item !== name) : [...current, name]));
  };
  const refused = preview.error ?? apply.error;
  const shown = preview.data;
  return (
    <details className="gk-data-group gk-removal">
      <summary>Remove sensors from the analysis</summary>
      <p className="gk-muted">A removed sensor&apos;s columns leave the working data. Undo puts them back.</p>
      <fieldset className="gk-columns">
        <legend>Sensors to remove</legend>
        {present.map((instrument) => (
          <label key={instrument.name} className="gk-check">
            <input type="checkbox" checked={chosen.includes(instrument.name)} onChange={() => toggle(instrument.name)} />
            {instrument.name}
          </label>
        ))}
      </fieldset>
      <div className="gk-actions">
        <button type="button" className="gk-button" disabled={chosen.length === 0 || preview.isPending} onClick={() => preview.mutate(chosen)}>
          Preview
        </button>
        {shown && (
          <button type="button" className="gk-button gk-button-primary" disabled={apply.isPending} onClick={() => apply.mutate(chosen)}>
            Remove {shown.removed.length} {shown.removed.length === 1 ? "sensor" : "sensors"}
          </button>
        )}
      </div>
      {shown && (
        <p role="status">
          Would remove {shown.removed.join(", ") || "nothing"}, taking out the columns {droppedColumns(shown).join(", ") || "none"};{" "}
          {shown.remaining_count} {shown.remaining_count === 1 ? "sensor remains" : "sensors remain"}.
          {shown.not_found.length > 0 ? ` Not in the inventory: ${shown.not_found.join(", ")}.` : ""}
        </p>
      )}
      {refused && (
        <p role="alert" className="gk-refusal">
          {refused.message}
        </p>
      )}
    </details>
  );
}
