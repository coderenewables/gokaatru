import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { api, unwrap } from "../api";
import { invalidateCampaign } from "../invalidate";
import { BrightHubCredentials } from "../reanalysis/BrightHubCredentials";
import { useCampaign } from "../shell/context";

/** What BrightHub can do to the records before they are sent. Each is applied by BrightHub,
 * cannot be undone here and is recorded on the cleaning log as upstream processing. */
export const UPSTREAM = [
  { key: "apply_cleaning_log", label: "BrightHub's cleaning log", initial: true },
  { key: "apply_cleaning_rules", label: "BrightHub's cleaning rules", initial: false },
  { key: "apply_calibration", label: "Calibration", initial: false },
  { key: "apply_deadband_offset", label: "Wind vane dead-band offset", initial: false },
  { key: "apply_orientation_offset", label: "Device orientation offset", initial: false },
] as const;

type UpstreamKey = (typeof UPSTREAM)[number]["key"];

const INITIAL = Object.fromEntries(UPSTREAM.map((item) => [item.key, item.initial])) as Record<UpstreamKey, boolean>;

/** Import a BrightHub measurement location into the campaign (brighthub_import_location): its
 * records and its data model, with the site's name and coordinate when the campaign has none. */
export function BrightHubImport() {
  const { sessionId } = useCampaign();
  const client = useQueryClient();
  const id = useId();
  const path = { params: { path: { session_id: sessionId } } };
  const [uuid, setUuid] = useState("");
  const [upstream, setUpstream] = useState(INITIAL);

  const status = useQuery({
    queryKey: ["brighthub-status", sessionId],
    queryFn: async () => unwrap(await api.POST("/api/sessions/{session_id}/operations/brighthub_status", { ...path, body: {} })),
  });
  const signedIn = status.data?.authenticated === true;
  const locations = useQuery({
    queryKey: ["brighthub-locations", sessionId],
    enabled: signedIn,
    queryFn: async () => unwrap(await api.POST("/api/sessions/{session_id}/operations/brighthub_list_locations", { ...path, body: {} })),
  });
  const chosen = locations.data?.locations.find((location) => location.uuid === uuid);
  const load = useMutation({
    mutationFn: async () => {
      if (!chosen) throw new Error("Choose a location first");
      return unwrap(
        await api.POST("/api/sessions/{session_id}/operations/brighthub_import_location", {
          ...path,
          body: {
            uuid: chosen.uuid,
            name: chosen.name,
            latitude_ddeg: chosen.latitude_ddeg ?? 0,
            longitude_ddeg: chosen.longitude_ddeg ?? 0,
            ...upstream,
          },
        }),
      );
    },
    onSuccess: () => invalidateCampaign(client, sessionId),
  });

  return (
    <details className="gk-data-group gk-bh-import">
      <summary>Or import a BrightHub location</summary>
      <BrightHubCredentials sessionId={sessionId} authenticated={signedIn} disabled={load.isPending} onChanged={() => void status.refetch()} />
      {signedIn && (
        <>
          {locations.isError && <p role="alert" className="gk-refusal">{locations.error.message}</p>}
          {locations.isPending && <p className="gk-muted">Listing the locations…</p>}
          {locations.data && (
            <label className="gk-field" htmlFor={`${id}-location`}>
              Location
              <select id={`${id}-location`} value={uuid} onChange={(event) => setUuid(event.target.value)} disabled={load.isPending}>
                <option value="">Choose a location</option>
                {locations.data.locations.map((location) => (
                  <option key={location.uuid} value={location.uuid}>
                    {location.name || location.uuid}
                  </option>
                ))}
              </select>
            </label>
          )}
          <fieldset className="gk-columns" disabled={load.isPending}>
            <legend>Applied by BrightHub before the records are sent</legend>
            {UPSTREAM.map((item) => (
              <label key={item.key} className="gk-check">
                <input
                  type="checkbox"
                  checked={upstream[item.key]}
                  onChange={(event) => setUpstream((current) => ({ ...current, [item.key]: event.target.checked }))}
                />
                {item.label}
              </label>
            ))}
          </fieldset>
          <p className="gk-muted">
            What BrightHub applies cannot be undone here; the cleaning log records it as upstream processing.
          </p>
          <button type="button" className="gk-button gk-button-primary" disabled={!chosen || load.isPending} onClick={() => load.mutate()}>
            {load.isPending ? "Importing…" : "Import"}
          </button>
          {load.isError && <p role="alert" className="gk-refusal">{load.error.message}</p>}
          {load.data && (
            <p role="status">
              Imported {load.data.timeseries_rows} records from {load.data.timeseries_start ?? "?"} to {load.data.timeseries_end ?? "?"}.{" "}
              {load.data.upstream_processing_note}
            </p>
          )}
        </>
      )}
    </details>
  );
}
