// Stage 7 — Clipping analysis (spec §4 / Stage 7).
//
// Advisory: pick the representative historical window that minimizes combined
// historic + climate uncertainty. Renders the per-start-year U-curve and lets
// the analyst capture a chosen representative start year.
import { useEffect, useState } from "react";

import { useWorkspaceStore } from "../../store/useWorkspaceStore";
import { Disclosure } from "../common/Disclosure";
import { RunButton } from "../common/RunButton";
import type { ClippingReport } from "../../types/analysis";

export function ClippingView() {
  const ltcResults = useWorkspaceStore((state) => state.ltcResults);
  const ensembleSummary = useWorkspaceStore((state) => state.ensembleSummary);
  const clippingColumns = useWorkspaceStore((state) => state.clippingColumns);
  const clippingReport = useWorkspaceStore((state) => state.clippingReport);
  const loadClippingColumns = useWorkspaceStore((state) => state.loadClippingColumns);
  const runClippingAnalysis = useWorkspaceStore((state) => state.runClippingAnalysis);
  const activity = useWorkspaceStore((state) => state.activity);

  const [source, setSource] = useState<string>(ensembleSummary?.available ? "ensemble" : ltcResults[0]?.algorithm ?? "");
  const [speedCol, setSpeedCol] = useState<string>("");
  const [chosenYear, setChosenYear] = useState<number | null>(null);

  useEffect(() => {
    if (source) void loadClippingColumns(source);
  }, [source, loadClippingColumns]);

  useEffect(() => {
    if (clippingColumns.length > 0 && !speedCol) {
      const preferred = clippingColumns.find((c) => c === "Ensemble_Speed") ?? clippingColumns[0];
      setSpeedCol(preferred);
    }
  }, [clippingColumns, speedCol]);

  const report: ClippingReport | null = clippingReport;
  useEffect(() => {
    if (report) setChosenYear(report.optimal_start_year);
  }, [report]);

  const run = () => {
    if (!speedCol || !source) return;
    void runClippingAnalysis({ speed_col: speedCol, source });
  };

  const sourceOptions = [
    ...(ensembleSummary?.available ? [{ value: "ensemble", label: "Ensemble" }] : []),
    ...ltcResults.map((r) => ({ value: r.algorithm, label: r.algorithm })),
  ];

  return (
    <div className="stage-view">
      <section className="path-panel">
        <h3>Source & column</h3>
        <p className="muted">
          Clipping is advisory — it does not mutate session state. It recommends the historical start year
          that minimizes combined historic + climate uncertainty.
        </p>
        <div className="form-grid">
          <label className="form-field">
            <span>Source</span>
            <select value={source} onChange={(e) => setSource(e.target.value)}>
              <option value="">Select source…</option>
              {sourceOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>
          <label className="form-field">
            <span>Speed column</span>
            <select value={speedCol} onChange={(e) => setSpeedCol(e.target.value)}>
              <option value="">Select column…</option>
              {clippingColumns.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="path-actions">
          <RunButton label="Run clipping analysis" onClick={run} disabled={!source || !speedCol} />
        </div>
        {sourceOptions.length === 0 ? (
          <p className="muted">Run an LTC algorithm or ensemble (Stage 6 / 8) first.</p>
        ) : null}
      </section>

      {report ? (
        <>
          <section className="path-panel">
            <h3>Result</h3>
            <dl className="metrics-grid">
              <Tile label="Optimal start year" value={String(report.optimal_start_year)} />
              <Tile label="Min combined uncertainty" value={`${report.min_uncertainty.toFixed(3)}`} />
              <Tile label="Full-series IAV" value={`${(report.iav * 100).toFixed(1)}%`} />
            </dl>
            {/* The minimum-window floor, the structural bias that favours short windows,
                and which exponent selected this period all arrive in the response. */}
            <Disclosure source={report} title="What this window selection assumes" />
            <div className="form-field">
              <span>Representative start year (EYA reporting)</span>
              <input
                type="number"
                value={chosenYear ?? report.optimal_start_year}
                onChange={(e) => setChosenYear(Number(e.target.value))}
              />
            </div>
            <p className="muted">
              Representative years: {chosenYear ?? report.optimal_start_year} → end of record.
            </p>
          </section>

          <section className="path-panel">
            <h3>Combined-uncertainty curve</h3>
            <UncertaintyCurve report={report} chosenYear={chosenYear ?? report.optimal_start_year} />
          </section>
        </>
      ) : (
        <p className="muted">
          {activity.some((a) => a.label === "Clipping failed")
            ? "Last clipping run failed — see activity log."
            : "No clipping report yet."}
        </p>
      )}
    </div>
  );
}

function UncertaintyCurve({ report, chosenYear }: { report: ClippingReport; chosenYear: number }) {
  const rows = report.analysis_data;
  if (rows.length === 0) return <p className="muted">No analysis rows.</p>;

  const years = rows.map((r) => r.start_year);
  const historic = rows.map((r) => r.historic_uncertainty);
  const climate = rows.map((r) => r.climate_uncertainty);
  const combined = rows.map((r) => r.combined_uncertainty);
  const maxY = Math.max(...historic, ...climate, ...combined, 0.001);

  return (
    <div className="uncertainty-curve">
      <svg viewBox="0 0 600 220" width="100%" role="img" aria-label="Combined uncertainty by start year">
        {/* axes */}
        <line x1="40" y1="10" x2="40" y2="190" stroke="#d8d2c4" />
        <line x1="40" y1="190" x2="590" y2="190" stroke="#d8d2c4" />
        {/* chosen-year marker */}
        {(() => {
          const xRange = 550;
          const xFor = (y: number) =>
            40 +
            (years.length > 1
              ? ((y - years[0]) / (years[years.length - 1] - years[0])) * xRange
              : xRange / 2);
          const yFor = (v: number) => 190 - (v / maxY) * 175;
          const mkPath = (vals: number[]) =>
            vals.map((v, i) => `${i === 0 ? "M" : "L"} ${xFor(years[i])} ${yFor(v)}`).join(" ");
          const chosenX = xFor(chosenYear);
          return (
            <>
              <path d={mkPath(historic)} fill="none" stroke="#5f716a" strokeWidth="1.5" />
              <path d={mkPath(climate)} fill="none" stroke="#c86a2a" strokeWidth="1.5" />
              <path d={mkPath(combined)} fill="none" stroke="#0b7a6f" strokeWidth="2" />
              <line x1={chosenX} y1="10" x2={chosenX} y2="190" stroke="#083434" strokeDasharray="4 3" />
              {years.map((y, i) =>
                i % Math.ceil(years.length / 8) === 0 ? (
                  <text key={y} x={xFor(y)} y="205" textAnchor="middle" fontSize="9" fill="#5f716a">
                    {y}
                  </text>
                ) : null,
              )}
            </>
          );
        })()}
      </svg>
      <div className="legend">
        <span><i style={{ background: "#0b7a6f" }} /> Combined</span>
        <span><i style={{ background: "#5f716a" }} /> Historic</span>
        <span><i style={{ background: "#c86a2a" }} /> Climate</span>
        <span className="muted">Dashed = chosen year</span>
      </div>

      <table className="data-table">
        <thead>
          <tr>
            <th>Start year</th>
            <th>N years</th>
            <th>Mean speed</th>
            <th>IAV</th>
            <th>LTA ratio</th>
            <th>Historic</th>
            <th>Climate</th>
            <th>Combined</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.start_year} className={r.start_year === chosenYear ? "row-highlight" : ""}>
              <td>{r.start_year}</td>
              <td>{r.n_years}</td>
              <td>{r.mean_speed.toFixed(2)}</td>
              <td>{(r.iav * 100).toFixed(1)}%</td>
              <td>{r.lta_ratio.toFixed(3)}</td>
              <td>{r.historic_uncertainty.toFixed(3)}</td>
              <td>{r.climate_uncertainty.toFixed(3)}</td>
              <td>{r.combined_uncertainty.toFixed(3)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-tile">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
