import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";

import { api, unwrap } from "../api";
import { useCampaign } from "../shell/context";
import { BrightHubCredentials } from "./BrightHubCredentials";
import "./reanalysis.css";
import {
  PROVIDER_NAMES,
  cacheText,
  coordinateText,
  datasetsFor,
  interpolationSource,
  loadedText,
  nodeText,
  progressText,
  sortByDistance,
  stepText,
  summarise,
  type Dataset,
  type GridNode,
  type Loaded,
  type NodeOutcome,
  type Progress,
  type Provider,
} from "./steps";

interface Failure {
  step: string;
  message: string;
}

// The long-term reference period the current interface offers; BrightHub's download takes none.
const DEFAULT_START = "2000-01-01";
const DEFAULT_END = "2025-12-31";

const message = (error: unknown): string => (error instanceof Error ? error.message : String(error));

/** Reanalysis acquisition (plan §3.2 Prepare): find the nodes around the site, take them one at
 * a time, interpolate each source to the site. One node at a time on both providers: the direct
 * EarthDataHub store resets simultaneous connections from one credential. */
export function ReanalysisPanel() {
  const { sessionId } = useCampaign();
  const queryClient = useQueryClient();
  const path = { params: { path: { session_id: sessionId } } };

  const [provider, setProvider] = useState<Provider>("brighthub");
  const [startDate, setStartDate] = useState(DEFAULT_START);
  const [endDate, setEndDate] = useState(DEFAULT_END);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [outcomes, setOutcomes] = useState<NodeOutcome[]>([]);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [loaded, setLoaded] = useState<Loaded[] | null>(null);
  const [running, setRunning] = useState(false);
  const busy = useRef(false);

  const site = useQuery({
    queryKey: ["run-config", sessionId],
    queryFn: async () =>
      unwrap(await api.POST("/api/sessions/{session_id}/operations/get_run_config", { ...path, body: {} })),
  });
  const latitude = site.data?.location?.latitude ?? null;
  const longitude = site.data?.location?.longitude ?? null;

  const brightHub = useQuery({
    queryKey: ["brighthub-status", sessionId],
    queryFn: async () => unwrap(await api.POST("/api/sessions/{session_id}/operations/brighthub_status", { ...path, body: {} })),
  });
  const earthDataHub = useQuery({
    queryKey: ["earthdatahub-status", sessionId],
    queryFn: async () => unwrap(await api.POST("/api/sessions/{session_id}/operations/earthdatahub_status", { ...path, body: {} })),
  });
  const signedIn =
    provider === "brighthub"
      ? brightHub.data?.authenticated === true
      : earthDataHub.data?.configured === true;

  async function run(siteLatitude: number, siteLongitude: number) {
    if (busy.current) return;
    busy.current = true;
    setRunning(true);
    setFailure(null);
    setLoaded(null);
    setOutcomes([]);
    const done: NodeOutcome[] = [];
    const interpolated: Dataset[] = [];
    let at: Progress = { phase: "finding_nodes", dataset: "ERA5" };
    const enter = (next: Progress) => {
      at = next;
      setProgress(next);
    };
    try {
      enter(at);
      const nodesByDataset: Partial<Record<Dataset, GridNode[]>> = {};
      const body = { latitude: siteLatitude, longitude: siteLongitude };
      if (provider === "brighthub") {
        const found = unwrap(await api.POST("/api/sessions/{session_id}/operations/brighthub_find_reanalysis_nodes", { ...path, body }));
        // The finder records the nodes, nearest first, with their distance from the site.
        const own = (nodes: typeof found.era5_nodes): GridNode[] =>
          sortByDistance(
            nodes.map((n) => ({
              latitude: Number(n.latitude_ddeg),
              longitude: Number(n.longitude_ddeg),
              distance_km: typeof n.distance_km === "number" ? n.distance_km : null,
            })),
          );
        nodesByDataset.ERA5 = own(found.era5_nodes);
        nodesByDataset["MERRA-2"] = own(found.merra2_nodes);
      } else {
        const found = unwrap(await api.POST("/api/sessions/{session_id}/operations/find_era5_nodes", { ...path, body })) as {
          nodes?: GridNode[];
        };
        nodesByDataset.ERA5 = sortByDistance(found.nodes ?? []);
      }

      for (const dataset of datasetsFor(provider)) {
        const nodes = nodesByDataset[dataset] ?? [];
        if (nodes.length === 0) throw new Error(`No ${dataset} nodes were found around the site.`);
        for (let index = 0; index < nodes.length; index += 1) {
          const node = nodes[index];
          enter({ phase: "downloading", dataset, current: index + 1, total: nodes.length, node });
          let cache: string | null = null;
          if (provider === "brighthub") {
            const response = unwrap(
              await api.POST("/api/sessions/{session_id}/operations/brighthub_download_reanalysis", {
                ...path,
                body: {
                  dataset,
                  nodes_json: JSON.stringify([{ latitude_ddeg: node.latitude, longitude_ddeg: node.longitude }]),
                  source: "brighthub",
                },
              }),
            );
            cache = response.items[0]?.cache ?? null;
          } else {
            const at = { latitude: node.latitude, longitude: node.longitude };
            unwrap(await api.POST("/api/sessions/{session_id}/operations/extract_era5_data", { ...path, body: { ...at, start_date: startDate, end_date: endDate } }));
            // ERA5 holds u and v; interpolation reads the speed and direction derived from them.
            unwrap(await api.POST("/api/sessions/{session_id}/operations/compute_era5_wind_speed", { ...path, body: at }));
          }
          done.push({ dataset, node, cache });
          setOutcomes([...done]);
        }
      }

      for (const dataset of datasetsFor(provider)) {
        enter({ phase: "interpolating", dataset });
        unwrap(
          await api.POST("/api/sessions/{session_id}/operations/interpolate_era5_to_site", {
            ...path,
            body: { source: interpolationSource(dataset) },
          }),
        );
        interpolated.push(dataset);
      }
      setLoaded(summarise(done, interpolated));
    } catch (error) {
      setFailure({ step: stepText(at, provider), message: message(error) });
      if (done.length > 0) setLoaded(summarise(done, interpolated));
    } finally {
      setProgress(null);
      setRunning(false);
      busy.current = false;
      await queryClient.invalidateQueries({ queryKey: ["session", sessionId] });
    }
  }

  const datesValid = provider === "brighthub" || (startDate !== "" && endDate !== "" && endDate >= startDate);
  const whyNot =
    latitude === null || longitude === null
      ? "The campaign has no site coordinate yet. Build its data model to set one."
      : !signedIn
        ? `Sign in to ${PROVIDER_NAMES[provider]} first.`
        : !datesValid
          ? "The end date must be on or after the start date."
          : null;

  return (
    <div className="gk-panel gk-reanalysis">
      <fieldset className="gk-re-group" disabled={running}>
        <legend>Provider</legend>
        {(Object.keys(PROVIDER_NAMES) as Provider[]).map((id) => (
          <label key={id} className="gk-re-choice">
            <input type="radio" name="reanalysis-provider" checked={provider === id} onChange={() => setProvider(id)} />{" "}
            {PROVIDER_NAMES[id]}
            <span className="gk-muted"> {datasetsFor(id).join(" and ")}</span>
          </label>
        ))}
      </fieldset>

      {provider === "brighthub" ? (
        <BrightHubCredentials
          sessionId={sessionId}
          authenticated={brightHub.data?.authenticated === true}
          disabled={running}
          onChanged={() => void brightHub.refetch()}
        />
      ) : (
        <EarthDataHubCredentials
          sessionId={sessionId}
          configured={signedIn}
          disabled={running}
          onChanged={() => void earthDataHub.refetch()}
        />
      )}

      <section aria-labelledby="gk-re-site" className="gk-re-group">
        <h2 id="gk-re-site">Site</h2>
        {latitude !== null && longitude !== null ? (
          <p>
            Nodes are found around <strong>{coordinateText(latitude, longitude)}</strong>.
          </p>
        ) : (
          <p className="gk-muted">{site.isPending ? "Reading the site…" : "The campaign has no site coordinate yet."}</p>
        )}
        {provider === "earthdatahub" && (
          <div className="gk-re-row">
            <label>
              From
              <input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} disabled={running} />
            </label>
            <label>
              To
              <input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} disabled={running} />
            </label>
          </div>
        )}
      </section>

      <div className="gk-re-row">
        <button
          type="button"
          className="gk-button gk-button-primary"
          disabled={whyNot !== null || running}
          onClick={() => latitude !== null && longitude !== null && void run(latitude, longitude)}
        >
          {running ? "Acquiring…" : "Acquire reanalysis"}
        </button>
        {whyNot && !running && <span className="gk-muted">{whyNot}</span>}
      </div>

      <div className="gk-re-progress" aria-live="polite" aria-atomic="false">
        {progress && (
          <p>
            <strong>{progressText(progress)}</strong>
            {progress.node && <span className="gk-muted"> {nodeText(progress.node)}</span>}
          </p>
        )}
        {outcomes.length > 0 && (
          <ul className="gk-re-nodes" aria-label="Nodes taken">
            {outcomes.map((outcome) => (
              <li key={`${outcome.dataset}-${outcome.node.latitude}-${outcome.node.longitude}`}>
                {outcome.dataset} {nodeText(outcome.node)}: {cacheText(outcome.cache)}
              </li>
            ))}
          </ul>
        )}
        {failure && (
          <p role="alert" className="gk-re-failure">
            <strong>{failure.step} failed.</strong> {failure.message}
          </p>
        )}
        {loaded && (
          <section aria-labelledby="gk-re-loaded">
            <h2 id="gk-re-loaded">{failure ? "Loaded before the failure" : "Loaded"}</h2>
            <ul>
              {loaded.map((row) => (
                <li key={row.dataset}>{loadedText(row)}</li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  );
}

function EarthDataHubCredentials(props: {
  sessionId: string;
  configured: boolean;
  disabled: boolean;
  onChanged: () => void;
}) {
  const path = { params: { path: { session_id: props.sessionId } } };
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function save(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      unwrap(await api.POST("/api/sessions/{session_id}/operations/earthdatahub_set_credential", { ...path, body: { pat: token } }));
      setToken("");
      props.onChanged();
    } catch (failed) {
      setError(message(failed));
    }
  }

  async function clear() {
    setError(null);
    try {
      unwrap(await api.POST("/api/sessions/{session_id}/operations/earthdatahub_clear_credential", { ...path, body: {} }));
      props.onChanged();
    } catch (failed) {
      setError(message(failed));
    }
  }

  return (
    <section aria-labelledby="gk-re-edh" className="gk-re-group">
      <h2 id="gk-re-edh">EarthDataHub token</h2>
      {props.configured ? (
        <div className="gk-re-row">
          <span>A token is set for this session.</span>
          <button type="button" className="gk-button" onClick={() => void clear()} disabled={props.disabled}>
            Clear token
          </button>
        </div>
      ) : (
        <form onSubmit={(event) => void save(event)} className="gk-re-form">
          <label>
            Personal access token
            <input type="password" value={token} onChange={(event) => setToken(event.target.value)} autoComplete="off" />
          </label>
          <button type="submit" className="gk-button" disabled={props.disabled || token === ""}>
            Set token
          </button>
        </form>
      )}
      {error && (
        <p role="alert" className="gk-re-failure">
          {error}
        </p>
      )}
      <p className="gk-muted gk-re-note">Held by the server for this session only.</p>
    </section>
  );
}
