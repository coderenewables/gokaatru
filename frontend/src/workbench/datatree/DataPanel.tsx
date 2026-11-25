import { useDraggable } from "@dnd-kit/core";
import { useQuery } from "@tanstack/react-query";

import type { Schemas } from "../../api/client";
import { api, unwrap } from "../api";
import type { ChannelDrag } from "../dnd";
import { useCampaign } from "../shell/context";
import "./data.css";

type Instrument = Schemas["Instrument"];

const TYPE_LABELS: Record<string, string> = {
  wind_speed: "speed",
  wind_direction: "direction",
  temperature: "temperature",
  pressure: "pressure",
  humidity: "humidity",
};

export const instrumentsKey = (sessionId: string) => ["instruments", sessionId] as const;

const inSession = (sessionId: string) => ({ params: { path: { session_id: sessionId } }, body: {} });

/** A channel that can be dragged onto a chart (plan §3.3 "Any chart"). The charts' own
 * pickers are the keyboard route to the same thing. */
function Channel({ name, detail }: { name: string; detail?: string }) {
  const data: ChannelDrag = { kind: "channel", channel: name };
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({ id: `channel:${name}`, data });
  const style = transform ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)` } : undefined;
  return (
    <span
      ref={setNodeRef}
      className={isDragging ? "gk-channel gk-channel-dragging" : "gk-channel"}
      style={style}
      {...listeners}
      {...attributes}
      aria-roledescription="channel; drag onto a chart"
    >
      <span className="gk-channel-name">{name}</span>
      {detail && <span className="gk-muted"> {detail}</span>}
    </span>
  );
}

function InstrumentRow({ instrument }: { instrument: Instrument }) {
  const notes = [
    TYPE_LABELS[instrument.sensor_type ?? ""] ?? instrument.sensor_type ?? "unknown",
    instrument.boom_orientation_deg !== null && instrument.boom_orientation_deg !== undefined
      ? `boom ${instrument.boom_orientation_deg}°`
      : null,
    instrument.mapped_as === null ? "not mapped" : null,
  ].filter(Boolean);
  return (
    <li className="gk-instrument">
      {instrument.in_data ? (
        <Channel name={instrument.name} detail={notes.join(", ")} />
      ) : (
        <span className="gk-channel gk-channel-absent">
          <span className="gk-channel-name">{instrument.name}</span>
          <span className="gk-muted"> {[...notes, "not in the data"].join(", ")}</span>
        </span>
      )}
      {instrument.statistics.length > 0 && (
        <ul className="gk-statistics" aria-label={`Statistics of ${instrument.name}`}>
          {instrument.statistics.map((column) => (
            <li key={column}>
              <Channel name={column} />
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

/** The data tree: the campaign's instruments by height with their statistic channels, the
 * other channels, the reanalysis held, the saved selections and the flags. */
export function DataPanel() {
  const { sessionId } = useCampaign();
  const instruments = useQuery({
    queryKey: instrumentsKey(sessionId),
    queryFn: async () =>
      unwrap(await api.POST("/api/sessions/{session_id}/operations/list_instruments", inSession(sessionId))),
  });
  const summary = useQuery({
    queryKey: ["session", sessionId],
    queryFn: async () =>
      unwrap(await api.GET("/api/sessions/{session_id}", { params: { path: { session_id: sessionId } } })),
  });
  const selections = useQuery({
    queryKey: ["selections", sessionId],
    queryFn: async () =>
      unwrap(await api.POST("/api/sessions/{session_id}/operations/list_selections", inSession(sessionId))),
  });
  const cleaning = useQuery({
    queryKey: ["cleaning-log", sessionId],
    queryFn: async () =>
      unwrap(await api.POST("/api/sessions/{session_id}/operations/get_cleaning_log", inSession(sessionId))),
  });

  if (instruments.isError) {
    return (
      <div className="gk-panel" role="alert">
        The campaign's instruments could not be read: {instruments.error.message}
      </div>
    );
  }
  const listed = instruments.data?.instruments ?? [];
  const heights = instruments.data?.heights ?? [];
  const other = instruments.data?.other_channels ?? [];

  return (
    <div className="gk-panel gk-data">
      {instruments.isPending && <p className="gk-muted">Reading the instruments…</p>}
      {instruments.data && listed.length === 0 && other.length === 0 && (
        <p className="gk-muted">No data yet. Load the campaign's files to see its channels here.</p>
      )}
      {heights.map((height) => (
        <section key={height} aria-labelledby={`gk-height-${height}`} className="gk-data-group">
          <h2 id={`gk-height-${height}`}>{height} m</h2>
          <ul className="gk-instruments">
            {listed
              .filter((instrument) => instrument.height_m === height)
              .map((instrument) => (
                <InstrumentRow key={instrument.name} instrument={instrument} />
              ))}
          </ul>
        </section>
      ))}
      {other.length > 0 && (
        <section aria-labelledby="gk-other-channels" className="gk-data-group">
          <h2 id="gk-other-channels">Other channels</h2>
          <ul className="gk-instruments">
            {other.map((channel) => (
              <li key={channel.name} className="gk-instrument">
                <Channel name={channel.name} detail={channel.role === "ignored" ? "not a sensor" : channel.role} />
              </li>
            ))}
          </ul>
        </section>
      )}
      <section aria-labelledby="gk-reanalysis" className="gk-data-group">
        <h2 id="gk-reanalysis">Reanalysis</h2>
        <p className="gk-muted">
          {summary.data?.era5_interpolated_loaded
            ? "Interpolated to the site."
            : summary.data?.era5_nodes_loaded
              ? "Nodes downloaded, not yet interpolated."
              : "None loaded."}
        </p>
      </section>
      <section aria-labelledby="gk-saved-selections" className="gk-data-group">
        <h2 id="gk-saved-selections">Saved selections</h2>
        {selections.data?.selections.length ? (
          <ul className="gk-instruments">
            {selections.data.selections.map((selection) => (
              <li key={selection.name}>
                {selection.name}
                <span className="gk-muted">
                  {selection.records !== null && selection.records !== undefined ? ` ${selection.records} records` : ""}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="gk-muted">None saved.</p>
        )}
      </section>
      <section aria-labelledby="gk-flags" className="gk-data-group">
        <h2 id="gk-flags">Flags</h2>
        {cleaning.data?.flags.by_rule.length ? (
          <ul className="gk-instruments">
            {cleaning.data.flags.by_rule.map((row) => (
              <li key={`${row.rule_sequence}-${row.sensor}`}>
                {row.sensor}
                <span className="gk-muted">
                  {" "}
                  {row.records} records, {row.reason.replace(/_/g, " ")} (rule {row.rule_sequence})
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="gk-muted">No records flagged.</p>
        )}
      </section>
    </div>
  );
}
