// Stage 2 — Reanalysis acquisition (spec §4 / Stage 2).
//
// The provider and date window are chosen on the Data import page and the
// download runs there on "Save config and setup"; this stage reviews the
// result, re-runs acquisition if needed, and hosts the homogeneity test.
import { useState } from "react";

import { useWorkspaceStore } from "../../store/useWorkspaceStore";
import { NodeTable } from "../common/NodeTable";
import { MiniMap } from "../common/MiniMap";
import { RunButton } from "../common/RunButton";

export function ReanalysisView() {
  const config = useWorkspaceStore((state) => state.config);
  const saveConfig = useWorkspaceStore((state) => state.saveConfig);
  const fetchBrightHubReanalysisNodes = useWorkspaceStore(
    (state) => state.fetchBrightHubReanalysisNodes,
  );
  const downloadBrightHubReanalysis = useWorkspaceStore(
    (state) => state.downloadBrightHubReanalysis,
  );
  const invokeSessionOperation = useWorkspaceStore((state) => state.invokeSessionOperation);
  const runReanalysisAcquisition = useWorkspaceStore((state) => state.runReanalysisAcquisition);
  const setReanalysisProgress = useWorkspaceStore((state) => state.setReanalysisProgress);
  const source = config.reanalysis.acquisitionSource;
  const summary = useWorkspaceStore((state) => state.summary);
  const runHomogeneity = useWorkspaceStore((state) => state.runHomogeneity);
  const applyHomogeneityCutoff = useWorkspaceStore((state) => state.applyHomogeneityCutoff);
  const homogeneityReport = useWorkspaceStore((state) => state.homogeneityReport);

  const startDate = config.reanalysis.startDate;
  const endDate = config.reanalysis.endDate;

  const brighthubStatus = useWorkspaceStore((state) => state.brighthubStatus);
  const brighthubReanalysis = useWorkspaceStore((state) => state.brighthubReanalysis);
  const era5Nodes = useWorkspaceStore((state) => state.era5Nodes);
  const merraNodes = useWorkspaceStore((state) => state.merraNodes);
  const siteMap = useWorkspaceStore((state) => state.siteMap);
  const earthdatahubStatus = useWorkspaceStore((state) => state.earthdatahubStatus);

  const authenticated = brighthubStatus?.authenticated ?? false;
  const earthdatahubConfigured = earthdatahubStatus?.configured ?? false;
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
  //
  // Interpolation needs all four bounding-grid nodes' data present, not just the site's own
  // coordinate (that mismatch is what left ERA5 - not just MERRA-2 - showing unavailable in
  // the Analysis Engine on this path). "Find" discovers the four nodes; "Extract" must fetch
  // each of their own coordinates, not the site's, mirroring how the BrightHub path downloads
  // every one of its nodes rather than a single point.
  const [directEra5Nodes, setDirectEra5Nodes] = useState<Array<{ latitude: number; longitude: number }>>([]);

  const findEra5Direct = async () => {
    const result = await invokeSessionOperation<{ nodes: Array<{ latitude: number; longitude: number }> }>(
      "Find ERA5 nodes (direct)",
      "POST",
      "/era5/nodes",
      { latitude: lat, longitude: lon },
    );
    setDirectEra5Nodes(result?.nodes ?? []);
  };
  const extractEra5Direct = async () => {
    // Sequential, not concurrent: firing all four nodes at once was tried and
    // live-reproduced as worse - EarthDataHub reset/rejected simultaneous connections from
    // the same credential, so all four failed outright (502) instead of just being slow.
    // A slow sequential success beats a fast concurrent failure.
    try {
      for (let index = 0; index < directEra5Nodes.length; index += 1) {
        const node = directEra5Nodes[index];
        setReanalysisProgress({
          provider: "earthdatahub",
          phase: "downloading",
          dataset: "ERA5",
          current: index + 1,
          total: directEra5Nodes.length,
          latitude: node.latitude,
          longitude: node.longitude,
        });
        await invokeSessionOperation("Extract ERA5 (direct)", "POST", "/era5/extract", {
          latitude: node.latitude,
          longitude: node.longitude,
          start_date: startDate,
          end_date: endDate,
        });
      }
    } finally {
      setReanalysisProgress(null);
    }
  };
  const interpolateEra5 = async () => {
    setReanalysisProgress({ provider: source, phase: "interpolating", dataset: "ERA5" });
    try {
      await invokeSessionOperation("Interpolate ERA5 to site", "POST", "/era5/interpolate");
    } finally {
      setReanalysisProgress(null);
    }
  };

  return (
    <div className="stage-view">
      <section className="path-panel">
        <h3>Acquisition settings</h3>
        <p className="muted">
          Provider{" "}
          <strong>{source === "brighthub" ? "BrightHub (ERA5 + MERRA-2)" : "Direct ERA5 (EarthDataHub)"}</strong>,{" "}
          {startDate} → {endDate}, lat {lat.toFixed(3)}, lon {lon.toFixed(3)}. Chosen on the Data
          import page; change it there and save to re-acquire.
        </p>
        <div className="path-actions">
          <RunButton label="Re-run acquisition" variant="secondary" onClick={() => void runReanalysisAcquisition()} />
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
          <p className="muted">ERA5 only; no MERRA-2 on this path.</p>
          {!earthdatahubConfigured ? (
            <p className="muted">Configure your EarthDataHub credential in Stage 1 first.</p>
          ) : (
            <>
              <div className="path-actions">
                <RunButton label="Find ERA5 nodes" onClick={findEra5Direct} />
                <RunButton
                  label="Extract node data"
                  variant="secondary"
                  onClick={extractEra5Direct}
                  disabled={directEra5Nodes.length === 0}
                />
                <RunButton label="Interpolate to site" onClick={interpolateEra5} />
              </div>
              <p className="muted">
                {directEra5Nodes.length > 0
                  ? `${directEra5Nodes.length} surrounding node(s) found — extract each before interpolating.`
                  : "Find the surrounding nodes first."}
              </p>
            </>
          )}
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
