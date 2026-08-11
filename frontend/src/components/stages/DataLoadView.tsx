// Standalone data import and site configuration.
//
// Three entry paths: (a) upload local files, (b) import a BrightHub location,
// (c) load a shared dataset. After load: sensor inventory + site/hub config.
import { useEffect, useState } from "react";

import { useWorkspaceStore } from "../../store/useWorkspaceStore";
import { RunButton } from "../common/RunButton";
import type { SensorRow } from "../../types/analysis";

type LoadPath = "upload" | "brighthub" | "dataset";

export function DataLoadView() {
  const [path, setPath] = useState<LoadPath>("upload");
  const brighthubPromptRequired = useWorkspaceStore((state) => state.brighthubPromptRequired);

  useEffect(() => {
    if (brighthubPromptRequired) setPath("brighthub");
  }, [brighthubPromptRequired]);

  const sensors = useWorkspaceStore((state) => state.sensors);
  const deleteSensors = useWorkspaceStore((state) => state.deleteSensors);
  const [selected, setSelected] = useState<Set<string>>(() => new Set(sensors.map((sensor) => sensor.name)));
  const [applyOnSave, setApplyOnSave] = useState(true);

  useEffect(() => {
    setSelected(new Set(sensors.map((sensor) => sensor.name)));
  }, [sensors]);

  const excludedCount = sensors.length - selected.size;

  const applySelection = async () => {
    const excluded = sensors.filter((sensor) => !selected.has(sensor.name)).map((sensor) => sensor.name);
    if (excluded.length > 0) await deleteSensors(excluded);
  };

  return (
    <div className="stage-view">
      <div className="path-toggle" role="tablist">
        <PathTab id="upload" active={path === "upload"} onClick={setPath} label="Upload files" />
        <PathTab id="brighthub" active={path === "brighthub"} onClick={setPath} label="BrightHub import" />
        <PathTab id="dataset" active={path === "dataset"} onClick={setPath} label="Shared dataset" />
      </div>

      {path === "upload" ? <UploadPath /> : null}
      {path === "brighthub" ? <BrightHubPath /> : null}
      {path === "dataset" ? <DatasetPath /> : null}

      <SensorInventory sensors={sensors} selected={selected} setSelected={setSelected} />
      <SiteConfigForm
        applyOnSave={applyOnSave}
        setApplyOnSave={setApplyOnSave}
        excludedCount={excludedCount}
        applySelection={applySelection}
      />
    </div>
  );
}

function PathTab({
  id,
  active,
  onClick,
  label,
}: {
  id: LoadPath;
  active: boolean;
  onClick: (id: LoadPath) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      className={active ? "path-tab active" : "path-tab"}
      onClick={() => onClick(id)}
    >
      {label}
    </button>
  );
}

function UploadPath() {
  const uploadSessionFile = useWorkspaceStore((state) => state.uploadSessionFile);
  const summary = useWorkspaceStore((state) => state.summary);
  const [timeseriesFile, setTimeseriesFile] = useState<File | null>(null);
  const [datamodelFile, setDatamodelFile] = useState<File | null>(null);

  return (
    <section className="path-panel">
      <h3>Upload files</h3>
      <p className="muted">
        Timeseries (.csv/.tsv/.txt/.xlsx) and IEA Task 43 data model (.json).
      </p>
      <div className="dropzone-row">
        <FileInput
          label="Timeseries"
          accept=".csv,.tsv,.txt,.xlsx"
          file={timeseriesFile}
          onChange={setTimeseriesFile}
        />
        <FileInput
          label="Data model"
          accept=".json,application/json"
          file={datamodelFile}
          onChange={setDatamodelFile}
        />
      </div>
      <div className="path-actions">
        <RunButton
          label="Upload timeseries"
          onClick={() => {
            if (timeseriesFile) void uploadSessionFile("timeseries", timeseriesFile);
          }}
          disabled={!timeseriesFile}
        />
        <RunButton
          label="Upload data model"
          variant="secondary"
          onClick={() => {
            if (datamodelFile) void uploadSessionFile("datamodel", datamodelFile);
          }}
          disabled={!datamodelFile}
        />
      </div>
      {summary?.timeseries_loaded ? (
        <p className="status-ok">✓ Timeseries loaded</p>
      ) : (
        <p className="muted">Timeseries not yet loaded.</p>
      )}
      {summary?.sensor_mapping_loaded ? (
        <p className="status-ok">✓ Data model loaded</p>
      ) : (
        <p className="muted">Data model not yet loaded.</p>
      )}
    </section>
  );
}

function FileInput({
  label,
  accept,
  file,
  onChange,
}: {
  label: string;
  accept: string;
  file: File | null;
  onChange: (file: File | null) => void;
}) {
  return (
    <label className="file-input">
      <span className="file-input-label">{label}</span>
      <input
        type="file"
        accept={accept}
        onChange={(e) => onChange(e.target.files?.[0] ?? null)}
      />
      {file ? <span className="file-input-name">{file.name}</span> : <span className="muted">No file selected</span>}
    </label>
  );
}

function BrightHubPath() {
  const brighthubStatus = useWorkspaceStore((state) => state.brighthubStatus);
  const brighthubLocations = useWorkspaceStore((state) => state.brighthubLocations);
  const refreshBrightHub = useWorkspaceStore((state) => state.refreshBrightHub);
  const loginBrightHub = useWorkspaceStore((state) => state.loginBrightHub);
  const importBrightHubLocation = useWorkspaceStore((state) => state.importBrightHubLocation);
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [selectedUuid, setSelectedUuid] = useState("");
  const [applyCleaningLog, setApplyCleaningLog] = useState(true);

  useEffect(() => {
    refreshBrightHub();
  }, [refreshBrightHub]);

  const authenticated = brighthubStatus?.authenticated ?? false;

  if (!authenticated) {
    return (
      <section className="path-panel">
        <h3>Connect to BrightHub</h3>
        <p className="muted">Enter your BrightHub OAuth client credentials.</p>
        <div className="form-grid">
          <label className="form-field">
            <span>Client ID</span>
            <input type="text" value={clientId} onChange={(e) => setClientId(e.target.value)} />
          </label>
          <label className="form-field">
            <span>Client secret</span>
            <input
              type="password"
              value={clientSecret}
              onChange={(e) => setClientSecret(e.target.value)}
            />
          </label>
        </div>
        <RunButton
          label="Log in"
          onClick={() => loginBrightHub({ clientId, clientSecret })}
          disabled={!clientId || !clientSecret}
        />
      </section>
    );
  }

  return (
    <section className="path-panel">
      <h3>Import BrightHub location</h3>
      <div className="form-grid">
        <label className="form-field">
          <span>Location</span>
          <select value={selectedUuid} onChange={(e) => setSelectedUuid(e.target.value)}>
            <option value="">Select a location…</option>
            {brighthubLocations.map((loc) => (
              <option key={loc.uuid} value={loc.uuid}>
                {loc.name || loc.uuid}
                {loc.latitude_ddeg != null ? ` (${loc.latitude_ddeg}, ${loc.longitude_ddeg})` : ""}
              </option>
            ))}
          </select>
        </label>
        <label className="form-check">
          <input
            type="checkbox"
            checked={applyCleaningLog}
            onChange={(e) => setApplyCleaningLog(e.target.checked)}
          />
          <span>Apply cleaning log</span>
        </label>
      </div>
      <div className="path-actions">
        <RunButton
          label="Import location"
          onClick={() => {
            if (selectedUuid) {
              void importBrightHubLocation({ uuid: selectedUuid, apply_cleaning_log: applyCleaningLog });
            }
          }}
          disabled={!selectedUuid}
        />
        <RunButton label="Log out" variant="secondary" onClick={() => useWorkspaceStore.getState().logoutBrightHub()} />
      </div>
    </section>
  );
}

function DatasetPath() {
  const datasets = useWorkspaceStore((state) => state.datasets);
  const datasetPreview = useWorkspaceStore((state) => state.datasetPreview);
  const refreshDatasets = useWorkspaceStore((state) => state.refreshDatasets);
  const previewDataset = useWorkspaceStore((state) => state.previewDataset);
  const loadDataset = useWorkspaceStore((state) => state.loadDataset);

  useEffect(() => {
    refreshDatasets();
  }, [refreshDatasets]);

  if (datasets.length === 0) {
    return (
      <section className="path-panel">
        <h3>Shared dataset pool</h3>
        <p className="muted">No shared datasets available. Upload one via the datasets API to populate the pool.</p>
      </section>
    );
  }

  return (
    <section className="path-panel">
      <h3>Shared dataset pool</h3>
      <table className="data-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Date range</th>
            <th>Coverage</th>
            <th>Sensors</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {datasets.map((d) => {
            const id = (d.dataset_id ?? d.id) as string | undefined;
            if (!id) return null;
            return (
              <tr key={id}>
                <td>{d.name ?? id.slice(0, 8)}</td>
                <td>
                  {d.date_range ? `${d.date_range.start} → ${d.date_range.end}` : "—"}
                </td>
                <td>{typeof d.coverage_pct === "number" ? `${d.coverage_pct.toFixed(1)}%` : "—"}</td>
                <td>{d.sensor_count ?? "—"}</td>
                <td className="row-actions">
                  <button type="button" className="link-button" onClick={() => previewDataset(id)}>
                    Preview
                  </button>
                  <button type="button" className="link-button" onClick={() => loadDataset(id)}>
                    Load
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {datasetPreview ? (
        <details className="preview-details">
          <summary>
            Preview ({datasetPreview.total_rows ?? datasetPreview.rows?.length ?? 0} rows)
          </summary>
          <pre className="preview-payload">
            {JSON.stringify(datasetPreview.rows?.slice(0, 5) ?? datasetPreview.preview_rows?.slice(0, 5), null, 2)}
          </pre>
        </details>
      ) : null}
    </section>
  );
}

interface SensorInventoryProps {
  sensors: SensorRow[];
  selected: Set<string>;
  setSelected: React.Dispatch<React.SetStateAction<Set<string>>>;
}

function SensorInventory({ sensors, selected, setSelected }: SensorInventoryProps) {
  if (sensors.length === 0) return null;

  // Group sensors by type for display.
  const grouped = sensors.reduce<Record<string, typeof sensors>>((acc, s) => {
    (acc[s.sensor_type] ??= []).push(s);
    return acc;
  }, {});

  // Display order: speed first, then direction, temperature, pressure, humidity,
  // then any remaining types alphabetically.
  const TYPE_ORDER = [
    "wind_speed",
    "wind_direction",
    "temperature",
    "pressure",
    "humidity",
  ];
  const types = Object.keys(grouped).sort((a, b) => {
    const ia = TYPE_ORDER.indexOf(a);
    const ib = TYPE_ORDER.indexOf(b);
    if (ia !== -1 && ib !== -1) return ia - ib;
    if (ia !== -1) return -1;
    if (ib !== -1) return 1;
    return a.localeCompare(b);
  });

  const toggle = (name: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const toggleGroup = (names: string[]) => {
    setSelected((prev) => {
      const allSelected = names.every((n) => prev.has(n));
      const next = new Set(prev);
      if (allSelected) {
        names.forEach((n) => next.delete(n));
      } else {
        names.forEach((n) => next.add(n));
      }
      return next;
    });
  };

  const toggleAll = () => {
    setSelected((previous) => (
      previous.size === sensors.length ? new Set() : new Set(sensors.map((sensor) => sensor.name))
    ));
  };

  const selectedCount = selected.size;

  return (
    <section className="path-panel">
      <div className="sensor-inventory-header">
        <h3>Analysis sensor selection</h3>
        {sensors.length > 0 ? (
          <span className="muted">{selectedCount} included · {sensors.length - selectedCount} excluded</span>
        ) : null}
      </div>
      <p className="muted sensor-hint">
        Select the sensors to include in analysis. Excluded sensors are removed from the session data,
        so Sensor Overview and subsequent stages use only this selection. Load the data file again or
        re-import from BrightHub to restore them.
      </p>
      <label className="sensor-group-header">
        <input
          type="checkbox"
          aria-label="Select all sensors"
          checked={selectedCount === sensors.length}
          onChange={toggleAll}
        />
        <strong>Select all</strong>
      </label>
      {types.map((type) => {
        const groupSensors = grouped[type];
        const groupNames = groupSensors.map((s) => s.name);
        const groupAllSelected = groupNames.every((n) => selected.has(n));
        return (
          <div key={type} className="sensor-group">
            <label className="sensor-group-header">
              <input
                type="checkbox"
                checked={groupAllSelected}
                onChange={() => toggleGroup(groupNames)}
              />
              <strong>{type}</strong>
              <span className="muted">({groupSensors.length})</span>
            </label>
            <table className="data-table sensor-table">
              <thead>
                <tr>
                  <th></th>
                  <th>Name</th>
                  <th>Height (m)</th>
                  <th>Coverage</th>
                  <th>Records</th>
                </tr>
              </thead>
              <tbody>
                {groupSensors.map((s) => (
                  <tr key={s.name} className={selected.has(s.name) ? "row-selected" : ""}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`Include ${s.name}`}
                        checked={selected.has(s.name)}
                        onChange={() => toggle(s.name)}
                      />
                    </td>
                    <td>{s.name}</td>
                    <td>{s.height_m}</td>
                    <td>{s.data_coverage_pct.toFixed(1)}%</td>
                    <td>{s.record_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </section>
  );
}

interface SiteConfigFormProps {
  applyOnSave: boolean;
  setApplyOnSave: (value: boolean) => void;
  excludedCount: number;
  applySelection: () => Promise<void>;
}

function SiteConfigForm({ applyOnSave, setApplyOnSave, excludedCount, applySelection }: SiteConfigFormProps) {
  const config = useWorkspaceStore((state) => state.config);
  const updateConfigValue = useWorkspaceStore((state) => state.updateConfigValue);
  const saveConfigAndRunModel = useWorkspaceStore((state) => state.saveConfigAndRunModel);

  return (
    <section className="path-panel">
      <h3>Site & hub height</h3>
      <p className="muted">Saved to runconfig as project_name / location / hub_height_m.</p>
      <div className="form-grid">
        <label className="form-field">
          <span>Project name</span>
          <input
            type="text"
            value={config.project.name}
            onChange={(e) => updateConfigValue("project.name", e.target.value)}
          />
        </label>
        <label className="form-field">
          <span>Measurement type</span>
          <select
            value={config.project.measurementType}
            onChange={(e) => updateConfigValue("project.measurementType", e.target.value)}
          >
            <option value="mast">Mast</option>
            <option value="lidar">Lidar</option>
            <option value="sodar">Sodar</option>
            <option value="floating-lidar">Floating lidar</option>
            <option value="hybrid">Hybrid</option>
          </select>
        </label>
        <label className="form-field">
          <span>Latitude</span>
          <input
            type="number"
            step="0.0001"
            value={config.site.latitude}
            onChange={(e) => updateConfigValue("site.latitude", Number(e.target.value))}
          />
        </label>
        <label className="form-field">
          <span>Longitude</span>
          <input
            type="number"
            step="0.0001"
            value={config.site.longitude}
            onChange={(e) => updateConfigValue("site.longitude", Number(e.target.value))}
          />
        </label>
        <label className="form-field">
          <span>Elevation (m)</span>
          <input
            type="number"
            step="0.1"
            value={config.site.elevationM}
            onChange={(e) => updateConfigValue("site.elevationM", Number(e.target.value))}
          />
        </label>
        <label className="form-field">
          <span>Hub height (m)</span>
          <input
            type="number"
            step="0.1"
            value={config.site.hubHeightM || ""}
            onChange={(e) => updateConfigValue("site.hubHeightM", Number(e.target.value))}
          />
        </label>
      </div>
      <p className="muted">Hub height is required to build and run the default model.</p>
      {excludedCount > 0 ? (
        <label className="form-check apply-selection-check">
          <input
            type="checkbox"
            checked={applyOnSave}
            onChange={(e) => setApplyOnSave(e.target.checked)}
          />
          <span>Apply sensor selection ({excludedCount} excluded will be removed from analysis)</span>
        </label>
      ) : null}
      <RunButton
        label="Save config and run model"
        onClick={async () => {
          if (applyOnSave && excludedCount > 0) await applySelection();
          void saveConfigAndRunModel();
        }}
      />
    </section>
  );
}
