import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useId, useMemo, useState } from "react";

import type { Schemas } from "../../api/client";
import { api, unwrap } from "../api";
import { invalidateCampaign } from "../invalidate";
import { useCampaign } from "../shell/context";
import { MastEditor } from "./MastEditor";
import { loadFiles, useLoadStatus } from "./loading";
import {
  type Chip,
  type DraftChips,
  EMPTY_LOCATION,
  type Location,
  MEASUREMENT_TYPES,
  blockers,
  buildSpec,
  chipsFromDraft,
  chipsFromSpec,
  levelLabel,
  locationFromSpec,
} from "./spec";
import "./datamodel.css";

type Instruments = Schemas["ListInstrumentsResult"];
type Draft = Schemas["DraftDataModelResult"];

const inSession = (sessionId: string) => ({ params: { path: { session_id: sessionId } }, body: {} });

export const draftKey = (sessionId: string) => ["datamodel-draft", sessionId] as const;

/** The empty campaign's start: the keyboard route to loading, beside the window's drop. */
export function DropArea() {
  const { sessionId } = useCampaign();
  const client = useQueryClient();
  const busy = useLoadStatus((state) => state.busy);
  const inputId = useId();
  return (
    <section aria-labelledby={`${inputId}-title`} className="gk-data-group gk-drop-area">
      <h2 id={`${inputId}-title`}>Load the campaign</h2>
      <p>Drop the campaign's files here</p>
      <p className="gk-muted">A table (.csv, .txt, .xlsx) is the records, a .json file is a data model. Anywhere on the window works.</p>
      <label htmlFor={inputId}>Choose files</label>{" "}
      <input
        id={inputId}
        type="file"
        multiple
        accept=".csv,.txt,.xlsx,.json"
        disabled={busy}
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          event.target.value = "";
          if (files.length > 0) void loadFiles(client, sessionId, files);
        }}
      />
    </section>
  );
}

function LocationForm({ location, onChange }: { location: Location; onChange: (next: Location) => void }) {
  const field = (key: keyof Location, label: string, hint?: string) => (
    <label className="gk-mast-field gk-mast-location-field">
      <span>{label}</span>
      <input
        type="text"
        value={location[key]}
        placeholder={hint}
        onChange={(event) => onChange({ ...location, [key]: event.target.value })}
      />
    </label>
  );
  return (
    <fieldset className="gk-mast-location">
      <legend>Site</legend>
      {field("name", "Name")}
      {field("latitude", "Latitude (°)")}
      {field("longitude", "Longitude (°)")}
      {field("elevation", "Elevation (m)")}
      {field("offset", "UTC offset (hours)", "0")}
      {field("timezone", "or IANA time zone", "Europe/Copenhagen")}
      <p className="gk-muted">The timezone is required: a UTC offset or a zone name. Nothing is assumed.</p>
    </fieldset>
  );
}

function NotBuilt({ items }: { items: DraftChips["notBuilt"] }) {
  if (items.length === 0) return null;
  return (
    <details className="gk-mast-notbuilt">
      <summary>Not built ({items.length})</summary>
      <ul>
        {items.map((item) => (
          <li key={item.name}>
            <span className="gk-channel-name">{item.name}</span> <span className="gk-muted">{item.reason}</span>
          </li>
        ))}
      </ul>
    </details>
  );
}

async function build(sessionId: string, spec: Record<string, unknown>) {
  unwrap(
    await api.POST("/api/sessions/{session_id}/operations/build_data_model", {
      params: { path: { session_id: sessionId } },
      body: { spec },
    }),
  );
}

/** The drafted data model, before any build: the location and the mast, and the button. */
function DraftBuilder({ draft }: { draft: Draft }) {
  const { sessionId } = useCampaign();
  const client = useQueryClient();
  const drafted = useMemo(() => chipsFromDraft(draft.columns), [draft]);
  const [chips, setChips] = useState<Chip[]>(drafted.chips);
  const [location, setLocation] = useState<Location>(EMPTY_LOCATION);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reasons = blockers(chips, location);
  const reasonsId = useId();

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      await build(sessionId, buildSpec(chips, location));
      await invalidateCampaign(client, sessionId);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-labelledby="gk-builder-title" className="gk-data-group gk-builder">
      <h2 id="gk-builder-title">Build the data model</h2>
      <p className="gk-muted">{draft.note}</p>
      <LocationForm location={location} onChange={setLocation} />
      <MastEditor chips={chips} onChange={setChips} />
      <NotBuilt items={drafted.notBuilt} />
      <button type="button" className="gk-mast-build" disabled={reasons.length > 0 || busy} aria-describedby={reasonsId} onClick={() => void run()}>
        Build data model
      </button>
      <div id={reasonsId}>
        {reasons.length > 0 && (
          <ul className="gk-mast-reasons">
            {reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        )}
        <p className="gk-muted">The first build puts the records into UTC and cannot be undone; later edits can.</p>
      </div>
      {error && <p role="alert">{error}</p>}
    </section>
  );
}

function Collapsible({ title, children }: { title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <section aria-labelledby={`${id}-title`} className="gk-data-group">
      <h2 id={`${id}-title`}>
        <button type="button" className="gk-mast-toggle" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
          {title}
        </button>
      </h2>
      {open && <div id={id}>{children}</div>}
    </section>
  );
}

/** After a build the diagram stays editable: an edit rebuilds from the spec in force. */
function BuiltDiagram({ draft, spec }: { draft: Draft; spec: Record<string, unknown> }) {
  const { sessionId } = useCampaign();
  const client = useQueryClient();
  const drafted = useMemo(() => chipsFromDraft(draft.columns), [draft]);
  const chips = useMemo(() => chipsFromSpec(spec, drafted), [spec, drafted]);
  const location = useMemo(() => locationFromSpec(spec), [spec]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [held, setHeld] = useState<Chip[] | null>(null);
  // A column still without a height keeps the edit local: the rebuild waits for it.
  const shown = held ?? chips;
  const reasons = blockers(shown, location);

  const rebuild = async (next: Chip[]) => {
    setError(null);
    const waiting = blockers(next, location);
    if (waiting.length > 0) {
      setHeld(next);
      return;
    }
    setBusy(true);
    try {
      await build(sessionId, buildSpec(next, location));
      setHeld(null);
      await invalidateCampaign(client, sessionId);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Collapsible title="Mast diagram (editable)">
      <p className="gk-muted">
        Built from the file headers{location.name ? ` for ${location.name}` : ""}. A change rebuilds the data model at once; Ctrl+Z undoes it.
      </p>
      <fieldset disabled={busy} className="gk-mast-lock">
        <MastEditor chips={shown} onChange={(next) => void rebuild(next)} />
      </fieldset>
      <NotBuilt items={drafted.notBuilt} />
      {held && reasons.length > 0 && (
        <ul className="gk-mast-reasons">
          {reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
      {error && <p role="alert">{error}</p>}
    </Collapsible>
  );
}

/** The campaign's own data model: drawn from the instruments, never changed. */
function ReadOnlyDiagram({ file, instruments }: { file: string; instruments: Instruments | undefined }) {
  const listed = instruments?.instruments ?? [];
  const heights = (instruments?.heights ?? []).filter((height): height is number => height !== null);
  const noHeight = listed.filter((instrument) => instrument.height_m === null);
  return (
    <Collapsible title="Mast diagram (read only)">
      <p>
        The campaign's own data model, {file}. Shown, never changed.
      </p>
      <div className="gk-mast gk-mast-readonly">
        <div className="gk-mast-pole">
          {heights.map((height) => (
            <div key={height} role="group" aria-label={`Mast level ${levelLabel(height)}`} className="gk-mast-level">
              <span className="gk-mast-height">{levelLabel(height)}</span>
              <ul className="gk-mast-chips">
                {listed
                  .filter((instrument) => instrument.height_m === height)
                  .map((instrument) => (
                    <li key={instrument.name} className="gk-mast-chip">
                      <span className="gk-channel-name">{instrument.name}</span>{" "}
                      <span className="gk-muted">
                        {MEASUREMENT_TYPES[instrument.sensor_type ?? ""] ?? instrument.sensor_type ?? "unknown type"}
                        {instrument.boom_orientation_deg !== null && instrument.boom_orientation_deg !== undefined
                          ? `, boom ${instrument.boom_orientation_deg}°`
                          : ""}
                        {instrument.statistics.length > 0 ? `, with ${instrument.statistics.join(", ")}` : ""}
                      </span>
                    </li>
                  ))}
              </ul>
            </div>
          ))}
        </div>
        {noHeight.length > 0 && (
          <div role="group" aria-label="No height in the data model" className="gk-mast-unplaced">
            <h3>No height in the data model</h3>
            <ul className="gk-mast-chips">
              {noHeight.map((instrument) => (
                <li key={instrument.name} className="gk-mast-chip">
                  <span className="gk-channel-name">{instrument.name}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Collapsible>
  );
}

/** Whichever of the three the campaign is in: the builder, the editable diagram of a built
 * model, or the read-only diagram of its own. */
export function DataModelSection({ instruments }: { instruments: Instruments | undefined }) {
  const { sessionId } = useCampaign();
  const draft = useQuery({
    queryKey: draftKey(sessionId),
    queryFn: async () =>
      unwrap(await api.POST("/api/sessions/{session_id}/operations/draft_data_model", inSession(sessionId))),
  });
  if (draft.isError) {
    return (
      <p role="alert" className="gk-data-group">
        The columns could not be drafted: {draft.error.message}
      </p>
    );
  }
  if (!draft.data) return null;
  const inUse = draft.data.in_use;
  if (!inUse) return <DraftBuilder draft={draft.data} />;
  if (!inUse.built || inUse.spec === null) return <ReadOnlyDiagram file={inUse.file} instruments={instruments} />;
  return <BuiltDiagram draft={draft.data} spec={inUse.spec} />;
}
