import { useMemo, useState } from "react";

import { previewAssetJson } from "../lib/normalization";
import { useWorkspaceStore } from "../store/useWorkspaceStore";

function formatMetric(value: unknown, suffix = "") {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  return `${String(value)}${suffix}`;
}

export function SetupView() {
  const config = useWorkspaceStore((state) => state.config);
  const summary = useWorkspaceStore((state) => state.summary);
  const datasets = useWorkspaceStore((state) => state.datasets);
  const datasetPreview = useWorkspaceStore((state) => state.datasetPreview);
  const sensors = useWorkspaceStore((state) => state.sensors);
  const assets = useWorkspaceStore((state) => state.assets);
  const brighthubStatus = useWorkspaceStore((state) => state.brighthubStatus);
  const brighthubLocations = useWorkspaceStore((state) => state.brighthubLocations);
  const updateConfigValue = useWorkspaceStore((state) => state.updateConfigValue);
  const saveConfig = useWorkspaceStore((state) => state.saveConfig);
  const resetConfig = useWorkspaceStore((state) => state.resetConfig);
  const previewDataset = useWorkspaceStore((state) => state.previewDataset);
  const loadDataset = useWorkspaceStore((state) => state.loadDataset);
  const uploadSharedDataset = useWorkspaceStore((state) => state.uploadSharedDataset);
  const uploadSessionFile = useWorkspaceStore((state) => state.uploadSessionFile);
  const loginBrightHub = useWorkspaceStore((state) => state.loginBrightHub);
  const logoutBrightHub = useWorkspaceStore((state) => state.logoutBrightHub);
  const importBrightHubLocation = useWorkspaceStore((state) => state.importBrightHubLocation);

  const [sharedName, setSharedName] = useState("");
  const [sharedTimeseries, setSharedTimeseries] = useState<File | null>(null);
  const [sharedDatamodel, setSharedDatamodel] = useState<File | null>(null);
  const [sessionTimeseries, setSessionTimeseries] = useState<File | null>(null);
  const [sessionDatamodel, setSessionDatamodel] = useState<File | null>(null);
  const [brighthubClientId, setBrighthubClientId] = useState("");
  const [brighthubClientSecret, setBrighthubClientSecret] = useState("");

  const summaryCards = useMemo(
    () => [
      { label: "Timeseries", value: summary?.timeseries_loaded ? "Loaded" : "Pending" },
      { label: "Sensors", value: formatMetric(summary?.sensor_count) },
      { label: "Coverage", value: formatMetric(summary?.avg_coverage_pct, "%") },
      { label: "Cleaning rules", value: formatMetric(summary?.cleaning_rules_applied) },
      { label: "ERA5", value: summary?.era5_interpolated_ready ? "Interpolated" : "Not ready" },
      { label: "LTC runs", value: formatMetric((summary?.ltc_algorithms_run ?? []).length) },
    ],
    [summary],
  );

  return (
    <div className="workspace-grid">
      <section className="panel panel-span-2">
        <div className="panel-header">
          <div>
            <p className="panel-kicker">Phase 1</p>
            <h2>Central config</h2>
          </div>
          <div className="button-row">
            <button className="secondary-button" onClick={() => resetConfig()} type="button">
              Reset draft
            </button>
            <button className="primary-button" onClick={() => void saveConfig()} type="button">
              Save runconfig
            </button>
          </div>
        </div>

        <div className="form-grid">
          <label>
            <span>Project name</span>
            <input
              onChange={(event) => updateConfigValue("project.name", event.target.value)}
              type="text"
              value={config.project.name}
            />
          </label>
          <label>
            <span>Measurement type</span>
            <select
              onChange={(event) => updateConfigValue("project.measurementType", event.target.value)}
              value={config.project.measurementType}
            >
              <option value="mast">Mast</option>
              <option value="lidar">Lidar</option>
              <option value="sodar">Sodar</option>
              <option value="floating-lidar">Floating lidar</option>
              <option value="hybrid">Hybrid</option>
            </select>
          </label>
          <label>
            <span>Hub height (m)</span>
            <input
              onChange={(event) => updateConfigValue("site.hubHeightM", Number(event.target.value))}
              type="number"
              value={config.site.hubHeightM}
            />
          </label>
          <label>
            <span>Rotor diameter (m)</span>
            <input
              onChange={(event) => updateConfigValue("site.rotorDiameterM", Number(event.target.value))}
              type="number"
              value={config.site.rotorDiameterM}
            />
          </label>
          <label>
            <span>Latitude</span>
            <input
              onChange={(event) => updateConfigValue("site.latitude", Number(event.target.value))}
              step="0.000001"
              type="number"
              value={config.site.latitude}
            />
          </label>
          <label>
            <span>Longitude</span>
            <input
              onChange={(event) => updateConfigValue("site.longitude", Number(event.target.value))}
              step="0.000001"
              type="number"
              value={config.site.longitude}
            />
          </label>
          <label>
            <span>Elevation (m)</span>
            <input
              onChange={(event) => updateConfigValue("site.elevationM", Number(event.target.value))}
              type="number"
              value={config.site.elevationM}
            />
          </label>
          <label>
            <span>Timezone</span>
            <input onChange={(event) => updateConfigValue("site.timeZone", event.target.value)} type="text" value={config.site.timeZone} />
          </label>
          <label className="field-span-2">
            <span>Notes</span>
            <textarea onChange={(event) => updateConfigValue("project.notes", event.target.value)} rows={4} value={config.project.notes} />
          </label>
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="panel-kicker">Phase 1</p>
            <h2>Readiness</h2>
          </div>
        </div>
        <div className="summary-grid">
          {summaryCards.map((card) => (
            <article className="metric-card" key={card.label}>
              <span>{card.label}</span>
              <strong>{card.value}</strong>
            </article>
          ))}
        </div>
        <div className="sensor-summary">
          <p className="panel-kicker">Sensor inventory</p>
          <p>{sensors.length} mapped sensor row(s)</p>
        </div>
      </section>

      <section className="panel panel-span-2">
        <div className="panel-header">
          <div>
            <p className="panel-kicker">Phase 1</p>
            <h2>Data ingestion</h2>
            <p className="muted-text">
              Choose the path that matches your intent: load files into the current workspace now, or save a reusable dataset pair for future workspaces.
            </p>
          </div>
        </div>

        <div className="ingestion-stack">
          <article className="ingestion-card">
            <div className="ingestion-card-header">
              <div>
                <p className="panel-kicker">Primary path</p>
                <h3>Load files into the current workspace</h3>
              </div>
              <span className="status-pill">Active session</span>
            </div>
            <p className="muted-text">
              Use this path for direct CSV plus IEA Task 43 JSON/datamodel ingestion when you want the files applied to the current browser session immediately.
            </p>
            <div className="summary-grid ingestion-snapshot">
              <article className="metric-card">
                <span>Timeseries status</span>
                <strong>{summary?.timeseries_loaded ? "Loaded" : "Pending"}</strong>
              </article>
              <article className="metric-card">
                <span>Datamodel status</span>
                <strong>{summary?.sensor_mapping_loaded ? "Loaded" : "Pending"}</strong>
              </article>
            </div>
            <div className="form-grid form-grid-compact">
              <label>
                <span>Session timeseries CSV</span>
                <input onChange={(event) => setSessionTimeseries(event.target.files?.[0] ?? null)} type="file" />
              </label>
              <label>
                <span>IEA Task 43 JSON / session datamodel</span>
                <input onChange={(event) => setSessionDatamodel(event.target.files?.[0] ?? null)} type="file" />
              </label>
            </div>
            <div className="button-row">
              <button
                className="primary-button"
                disabled={sessionTimeseries === null}
                onClick={() => sessionTimeseries && void uploadSessionFile("timeseries", sessionTimeseries)}
                type="button"
              >
                Load timeseries into workspace
              </button>
              <button
                className="secondary-button"
                disabled={sessionDatamodel === null}
                onClick={() => sessionDatamodel && void uploadSessionFile("datamodel", sessionDatamodel)}
                type="button"
              >
                Load datamodel into workspace
              </button>
            </div>
          </article>

          <article className="ingestion-card">
            <div className="ingestion-card-header">
              <div>
                <p className="panel-kicker">Reusable path</p>
                <h3>Save a shared dataset pair</h3>
              </div>
              <span className="status-pill">Shared library</span>
            </div>
            <p className="muted-text">
              Save a named timeseries plus datamodel pair to the shared dataset library. It will not affect the current workspace until you explicitly load it.
            </p>
            <div className="form-grid form-grid-compact">
              <label>
                <span>Dataset name</span>
                <input onChange={(event) => setSharedName(event.target.value)} type="text" value={sharedName} />
              </label>
              <label>
                <span>Timeseries file</span>
                <input onChange={(event) => setSharedTimeseries(event.target.files?.[0] ?? null)} type="file" />
              </label>
              <label>
                <span>Datamodel file</span>
                <input onChange={(event) => setSharedDatamodel(event.target.files?.[0] ?? null)} type="file" />
              </label>
            </div>
            <div className="button-row">
              <button
                className="secondary-button"
                disabled={sharedTimeseries === null || sharedDatamodel === null}
                onClick={() => {
                  if (sharedTimeseries && sharedDatamodel) {
                    void uploadSharedDataset({ name: sharedName, timeseriesFile: sharedTimeseries, datamodelFile: sharedDatamodel });
                  }
                }}
                type="button"
              >
                Save dataset pair to library
              </button>
            </div>

            <div className="dataset-list">
              {datasets.length === 0 ? <p className="muted-text">No shared datasets are available yet.</p> : null}
              {datasets.map((dataset, index) => {
                const datasetId = String(dataset.dataset_id ?? dataset.id ?? `dataset-${index}`);
                return (
                  <article className="dataset-card" key={datasetId}>
                    <div>
                      <h3>{String(dataset.name ?? datasetId)}</h3>
                      <p>
                        {String(dataset.timeseries_filename ?? "timeseries")}, {String(dataset.datamodel_filename ?? "datamodel")}
                      </p>
                    </div>
                    <div className="button-row">
                      <button className="secondary-button" onClick={() => void previewDataset(datasetId)} type="button">
                        Preview
                      </button>
                      <button className="primary-button" onClick={() => void loadDataset(datasetId)} type="button">
                        Load into workspace
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          </article>
        </div>
      </section>

      <section className="panel panel-span-2">
        <div className="panel-header">
          <div>
            <p className="panel-kicker">Phase 1</p>
            <h2>BrightHub import</h2>
          </div>
        </div>

        <div className="form-grid form-grid-compact">
          <label>
            <span>Client ID</span>
            <input onChange={(event) => setBrighthubClientId(event.target.value)} type="text" value={brighthubClientId} />
          </label>
          <label>
            <span>Client secret</span>
            <input onChange={(event) => setBrighthubClientSecret(event.target.value)} type="password" value={brighthubClientSecret} />
          </label>
        </div>
        <div className="button-row">
          <button
            className="primary-button"
            disabled={brighthubClientId.trim().length === 0 || brighthubClientSecret.trim().length === 0}
            onClick={() => void loginBrightHub({ clientId: brighthubClientId, clientSecret: brighthubClientSecret })}
            type="button"
          >
            Connect BrightHub
          </button>
          <button className="secondary-button" disabled={!brighthubStatus?.authenticated} onClick={() => void logoutBrightHub()} type="button">
            Disconnect
          </button>
          <span className={`status-pill ${brighthubStatus?.authenticated ? "" : "status-pill-busy"}`}>
            {brighthubStatus?.authenticated ? "Authenticated" : "Not connected"}
          </span>
        </div>
        <p className="muted-text">
          BrightHub import loads both the measurement timeseries and the datamodel into the current workspace session using the backend import route.
        </p>

        <div className="dataset-list">
          {!brighthubStatus?.authenticated ? <p className="muted-text">Connect BrightHub to browse measurement locations and import them into this session.</p> : null}
          {brighthubStatus?.authenticated && brighthubLocations.length === 0 ? <p className="muted-text">No BrightHub locations are currently available for this account.</p> : null}
          {brighthubLocations.map((location) => (
            <article className="dataset-card" key={location.uuid}>
              <div>
                <h3>{location.name || location.uuid}</h3>
                <p>
                  {location.latitude_ddeg ?? "-"}, {location.longitude_ddeg ?? "-"}
                </p>
              </div>
              <button
                className="primary-button"
                onClick={() =>
                  void importBrightHubLocation({
                    uuid: location.uuid,
                    name: location.name,
                    latitude_ddeg: location.latitude_ddeg,
                    longitude_ddeg: location.longitude_ddeg,
                  })
                }
                type="button"
              >
                Import into session
              </button>
            </article>
          ))}
        </div>
      </section>

      <section className="panel panel-span-2">
        <div className="panel-header">
          <div>
            <p className="panel-kicker">Standardization layer</p>
            <h2>Normalized asset library</h2>
          </div>
        </div>
        <div className="asset-list">
          {assets.map((asset) => (
            <article className="asset-card" key={asset.id}>
              <div className="asset-card-header">
                <h3>{asset.label}</h3>
                <span className="status-pill">{asset.format}</span>
              </div>
              <p>{asset.summary}</p>
              <p className="asset-compatibility">Compatible with {asset.compatibility.join(", ")}</p>
              <pre>{previewAssetJson(asset)}</pre>
            </article>
          ))}
        </div>
      </section>

      <section className="panel panel-span-2">
        <div className="panel-header">
          <div>
            <p className="panel-kicker">Dataset preview</p>
            <h2>Tabular preview</h2>
          </div>
        </div>

        {datasetPreview === null ? <p className="muted-text">Preview a shared dataset to inspect its normalized tabular shape.</p> : null}
        {datasetPreview !== null ? (
          <div className="preview-table-wrapper">
            <table className="preview-table">
              <thead>
                <tr>
                  {(datasetPreview.columns ?? Object.keys((datasetPreview.rows ?? datasetPreview.preview_rows ?? [])[0] ?? {})).map((column) => (
                    <th key={column}>{column}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(datasetPreview.rows ?? datasetPreview.preview_rows ?? []).map((row, index) => (
                  <tr key={`${index}-${JSON.stringify(row)}`}>
                    {(datasetPreview.columns ?? Object.keys(row)).map((column) => (
                      <td key={column}>{String(row[column] ?? "")}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
    </div>
  );
}