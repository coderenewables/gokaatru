import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "../api";
import { describeTerm } from "../selection/describe";
import { VIEWS, VIEW_LABELS, useSelection, useSharedSelection } from "../selection/store";

export interface SelectionSectionProps {
  sessionId: string;
  /** The channels compared between the selection and every record, usually the speeds. */
  channels: string[];
}

function summarise(sessionId: string, channels: string[], selection: string) {
  return api.POST("/api/sessions/{session_id}/operations/summarise_channels", {
    params: { path: { session_id: sessionId } },
    body: { channels: channels.join(","), selection },
  });
}

const formatted = (value: number | null | undefined) => (value === null || value === undefined ? "—" : value.toFixed(2));

/** What the views select together: each view's term, how many records the intersection
 * holds, and the mean of each channel on the selection against every record. */
export function SelectionSection({ sessionId, channels }: SelectionSectionProps) {
  const terms = useSelection((state) => state.terms);
  const clear = useSelection((state) => state.clear);
  const clearAll = useSelection((state) => state.clearAll);
  const selection = useSharedSelection();
  const drawn = VIEWS.filter((view) => terms[view] !== undefined);

  const all = useQuery({
    queryKey: ["summary", sessionId, channels, ""],
    enabled: channels.length > 0,
    queryFn: async () => unwrap(await summarise(sessionId, channels, "")),
  });
  const selected = useQuery({
    queryKey: ["summary", sessionId, channels, selection],
    enabled: channels.length > 0 && selection !== "",
    queryFn: async () => unwrap(await summarise(sessionId, channels, selection)),
  });

  return (
    <section aria-labelledby="gk-selection-heading" className="gk-inspector-section">
      <h2 id="gk-selection-heading">Selection</h2>
      {drawn.length === 0 ? (
        <p className="gk-muted">Select on any chart. The timeline, the scatter and the rose filter each other.</p>
      ) : (
        <>
          <p className="gk-selection-count" aria-live="polite">
            {selected.isError ? (
              <span role="alert">{selected.error.message}</span>
            ) : (
              <>
                <strong>{selected.data?.selection?.records ?? "…"}</strong>
                <span className="gk-muted"> of {selected.data?.selection?.of_records ?? "…"} records</span>
              </>
            )}
          </p>
          <ul className="gk-terms" aria-label="Selection terms">
            {drawn.map((view) => {
              const term = terms[view];
              if (!term) return null;
              return (
                <li key={view} className="gk-term">
                  <span className="gk-term-label">{VIEW_LABELS[view]}</span>
                  <span className="gk-term-text">{describeTerm(term)}</span>
                  <button
                    type="button"
                    className="gk-icon-button"
                    aria-label={`Clear the ${VIEW_LABELS[view].toLowerCase()} term`}
                    onClick={() => clear(view)}
                  >
                    ×
                  </button>
                </li>
              );
            })}
          </ul>
          <button type="button" className="gk-button" onClick={clearAll}>
            Clear selection
          </button>
        </>
      )}
      {channels.length > 0 && (
        <table className="gk-compare">
          <caption className="gk-muted">Mean, selection against every record</caption>
          <thead>
            <tr>
              <th scope="col">Channel</th>
              <th scope="col">Selection</th>
              <th scope="col">All</th>
            </tr>
          </thead>
          <tbody>
            {channels.map((channel) => (
              <tr key={channel}>
                <th scope="row">{channel}</th>
                <td>{selection ? formatted(selected.data?.channels[channel]?.mean) : "—"}</td>
                <td>{formatted(all.data?.channels[channel]?.mean)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
