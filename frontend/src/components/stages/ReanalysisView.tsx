// Stage 2 — Reanalysis acquisition (spec §4 / Stage 2).
//
// BrightHub path (ERA5 + MERRA-2): find nodes, download, interpolate,
// optional homogeneity test. Direct ERA5 path available as a fallback.
import { useState } from "react";

import { useWorkspaceStore } from "../../store/useWorkspaceStore";
import { NodeTable } from "../common/NodeTable";
import { MiniMap } from "../common/MiniMap";
import { RunButton } from "../common/RunButton";

type Source = "brighthub" | "earthdatahub";

export function ReanalysisView() {
  const config = useWorkspaceStore((state) => state.config);
  const updateConfigValue = useWorkspaceStore((state) => state.updateConfigValue);
  const saveConfig = useWorkspaceStore((state) => state.saveConfig);
  const fetchBrightHubReanalysisNodes = useWorkspaceStore(
    (state) => state.fetchBrightHubReanalysisNodes,
  );
  const downloadBrightHubReanalysis = useWorkspaceStore(
    (state) => state.downloadBrightHubReanalysis,
  );
  const invokeSessionOperation = useWorkspaceStore((state) => state.invokeSessionOperation);
  const summary = useWorkspaceStore((state) => state.summary);
  const runHomogeneity = useWorkspaceStore((state) => state.runHomogeneity);
  const applyHomogeneityCutoff = useWorkspaceStore((state) => state.applyHomogeneityCutoff);
  const homogeneityReport = useWorkspaceStore((state) => state.homogeneityReport);

  const [source, setSource] = useState<Source>("brighthub");
  const [startDate, setStartDate] = useState(config.reanalysis.startDate);
  const [endDate, setEndDate] = useState(config.reanalysis.endDate);

  const brighthubStatus = useWorkspaceStore((state) => state.brighthubStatus);
  const brighthubReanalysis = useWorkspaceStore((state) => state.brighthubReanalysis);
  const era5Nodes = useWorkspaceStore((state) => state.era5Nodes);
  const merraNodes = useWorkspaceStore((state) => state.merraNodes);
  const siteMap = useWorkspaceStore((state) => state.siteMap);

  const authenticated = brighthubStatus?.authenticated ?? false;
  const lat = config.site.latitude;
  const lon = config.site.longitude;

  const findNodes = async () => {
    await saveConfig();
    await fetchBrightHubReanalysisNodes({ latitude: lat, longitude: lon });
  };

  const downloadEra5 = () =>
    downloadBrightHubReanalysis({ dataset: "ERA5", source, useNodes: "era5" });
  const downloadMerra = () =>
    downloadBrightHubReanalysis({ dataset: "MERRA-2", source: "brighthub", useNodes: "merra2" });

  // Direct ERA5 path (EarthDataHub Zarr): find + extract + interpolate.
  const findEra5Direct = async () => {
    await invokeSessionOperation("Find ERA5 nodes (direct)", "POST", "/era5/nodes", {
      latitude: lat,
      longitude: lon,
    });
  };
  const extractEra5Direct = async () => {
    await invokeSessionOperation("Extract ERA5 (direct)", "POST", "/era5/extract", {
      latitude: lat,
      longitude: lon,
      start_date: startDate,
      end_date: endDate,
    });
  };
  const interpolateEra5 = async () => {
    await invokeSessionOperation("Interpolate ERA5 to site", "POST", "/era5/interpolate");
  };

  return (
    <div className="stage-view">
      <section className="path-panel">
        <h3>Site coordinate</h3>
        <p className="muted">
          Lat {lat.toFixed(3)}, lon {lon.toFixed(3)}. Set in Stage 1; update there if needed.
        </p>
        <div className="form-grid">
          <label className="form-field">
            <span>Provider</span>
            <select value={source} onChange={(e) => setSource(e.target.value as Source)}>
              <option value="brighthub">BrightHub (ERA5 + MERRA-2)</option>
              <option value="earthdatahub">Direct ERA5 (EarthDataHub)</option>
            </select>
          </label>
          <label className="form-field">
            <span>Start date</span>
            <input
              type="date"
              value={startDate}
              onChange={(e) => {
                setStartDate(e.target.value);
                updateConfigValue("reanalysis.startDate", e.target.value);
              }}
            />
          </label>
          <label className="form-field">
            <span>End date</span>
            <input
              type="date"
              value={endDate}
              onChange={(e) => {
                setEndDate(e.target.value);
                updateConfigValue("reanalysis.endDate", e.target.value);
              }}
            />
          </label>
        </div>
      </section>

      {source === "brighthub" ? (
        <>
          <section className="path-panel">
            <h3>BrightHub reanalysis nodes</h3>
            {!authenticated ? (
              <p className="muted">Connect to BrightHub in Stage 1 first.</p>
            ) : (
              <>
                <div className="path-actions">
                  <RunButton label="Find surrounding nodes" onClick={findNodes} />
                </div>
                {brighthubReanalysis ? (
                  <>
                    <h4>ERA5 nodes</h4>
                    <NodeTable nodes={era5Nodes} provider="ERA5" />
                    <h4>MERRA-2 nodes</h4>
                    <NodeTable nodes={merraNodes} provider="MERRA-2" />
                  </>
                ) : null}
              </>
            )}
          </section>

          {brighthubReanalysis ? (
            <section className="path-panel">
              <h3>Download & interpolate</h3>
              <div className="path-actions">
                <RunButton label="Download ERA5" onClick={downloadEra5} />
                <RunButton
                  label="Download MERRA-2"
                  variant="secondary"
                  onClick={downloadMerra}
                />
                <RunButton label="Interpolate to site" onClick={interpolateEra5} />
              </div>
              {summary?.era5_interpolated_ready ? (
                <p className="status-ok">✓ ERA5 interpolated to site</p>
              ) : (
                <p className="muted">Interpolated series not yet ready.</p>
              )}
            </section>
          ) : null}
        </>
      ) : (
        <section className="path-panel">
          <h3>Direct ERA5 (EarthDataHub)</h3>
          <p className="muted">ERA5 only; no MERRA-2 on this path. Requires a configured PAT.</p>
          <div className="path-actions">
            <RunButton label="Find ERA5 nodes" onClick={findEra5Direct} />
            <RunButton label="Extract node data" variant="secondary" onClick={extractEra5Direct} />
            <RunButton label="Interpolate to site" onClick={interpolateEra5} />
          </div>
        </section>
      )}

      <section className="path-panel">
        <h3>Homogeneity (optional)</h3>
        <p className="muted">Pettitt change-point test on ERA5 node series to recommend a start year.</p>
        <div className="path-actions">
          <RunButton
            label="Run annual test"
            onClick={() => runHomogeneity("annual")}
          />
          <RunButton
            label="Run monthly test"
            variant="secondary"
            onClick={() => runHomogeneity("monthly")}
          />
          <RunButton
            label="Apply cutoff year"
            variant="secondary"
            onClick={() => {
              const fallback = homogeneityReport?.[0]?.recommended_start_year ?? 2003;
              const yearStr = window.prompt("Cutoff start year (e.g. 2003):", String(fallback));
              if (yearStr) {
                const year = Number(yearStr);
                if (Number.isFinite(year)) {
                  void applyHomogeneityCutoff(year);
                }
              }
            }}
          />
        </div>

        {homogeneityReport && homogeneityReport.length > 0 ? (
          <table className="data-table homogeneity-table">
            <thead>
              <tr>
                <th>Dataset</th>
                <th>Recommended start year</th>
                <th>Pettitt p-value</th>
                <th>Trend / year</th>
              </tr>
            </thead>
            <tbody>
              {homogeneityReport.map((d) => {
                const significant = d.pettitt_p_value < 0.05;
                return (
                  <tr key={d.name}>
                    <td>{d.name}</td>
                    <td>
                      <strong>{d.recommended_start_year}</strong>
                    </td>
                    <td className={significant ? "status-warn" : "status-ok"}>
                      {d.pettitt_p_value.toFixed(4)}
                      {significant ? " ⚠ change-point" : ""}
                    </td>
                    <td>{d.trend_per_year.toFixed(4)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <p className="muted">No homogeneity report yet. Run the test to see per-dataset recommendations.</p>
        )}
      </section>

      {siteMap ? (
        <section className="path-panel">
          <h3>Site overview map</h3>
          <MiniMap geojson={siteMap} />
        </section>
      ) : null}
    </div>
  );
}
