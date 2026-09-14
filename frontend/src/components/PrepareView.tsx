// Prepare phase (design doc: Prepare) — merges Data import, Data cleaning, Reanalysis
// acquisition, Sensor Overview and the Stepper into one screen with an internal section
// switcher, ending in the stamped fixed-prefix hash. Composes DataLoadView, StageShell
// and SensorReviewView unchanged; only the entry point is new.
import { useEffect } from "react";
import clsx from "clsx";

import { DataLoadView } from "./stages/DataLoadView";
import { StageShell } from "./stages/StageShell";
import { SensorReviewView } from "./SensorReviewView";
import { ResultsView } from "./results/ResultsView";
import { useWorkspaceStore } from "../store/useWorkspaceStore";
import { meanCoverage } from "../lib/prepareStats";

const SECTIONS: Array<{ id: "data" | "pipeline" | "sensors" | "results"; label: string }> = [
  { id: "data", label: "Data loading" },
  { id: "pipeline", label: "Pipeline" },
  { id: "sensors", label: "Sensor Overview" },
  { id: "results", label: "Results" },
];

export function PrepareView() {
  const session = useWorkspaceStore((state) => state.session);
  const sensors = useWorkspaceStore((state) => state.sensors);
  const prepareSection = useWorkspaceStore((state) => state.prepareSection);
  const setPrepareSection = useWorkspaceStore((state) => state.setPrepareSection);
  const prefixHash = useWorkspaceStore((state) => state.prefixHash);
  const reanalysisSourcesForPrefix = useWorkspaceStore((state) => state.reanalysisSourcesForPrefix);
  const cleaningActionsCount = useWorkspaceStore((state) => state.cleaningActionsCount);
  const loadPrefixHash = useWorkspaceStore((state) => state.loadPrefixHash);
  const setActivePhase = useWorkspaceStore((state) => state.setActivePhase);

  useEffect(() => {
    if (session) void loadPrefixHash();
  }, [session, loadPrefixHash]);

  const recovery = meanCoverage(sensors);

  return (
    <div className="prepare-view">
      <div className="prepare-intro">
        <h1>Everything the scenarios will share</h1>
        <p>
          Import, cleaning and reanalysis sit outside the scenario space on purpose: they run
          once and every scenario inherits them, so the spread measures methodology rather
          than filter settings. One prefix, stamped and hashed, then the engine.
        </p>
      </div>

      <div className="prepare-stat-tiles">
        <div className="prepare-stat-tile">
          <span className="prepare-stat-label">Data recovery</span>
          <span className="prepare-stat-value">{recovery === null ? "—" : `${recovery.toFixed(1)}%`}</span>
        </div>
        <div className="prepare-stat-tile">
          <span className="prepare-stat-label">Reanalysis sources</span>
          <span className="prepare-stat-value">{reanalysisSourcesForPrefix.length || "—"}</span>
        </div>
        <div className="prepare-stat-tile">
          <span className="prepare-stat-label">Cleaning actions</span>
          <span className="prepare-stat-value">{cleaningActionsCount}</span>
        </div>
      </div>

      <nav className="prepare-section-nav" aria-label="Prepare sections">
        {SECTIONS.map((section) => (
          <button
            key={section.id}
            type="button"
            className={clsx("prepare-section-tab", { active: prepareSection === section.id })}
            aria-current={prepareSection === section.id ? "page" : undefined}
            onClick={() => setPrepareSection(section.id)}
          >
            {section.label}
          </button>
        ))}
      </nav>

      {prepareSection === "data" ? <DataLoadView /> : null}
      {prepareSection === "pipeline" ? <StageShell /> : null}
      {prepareSection === "sensors" ? <SensorReviewView /> : null}
      {prepareSection === "results" ? <ResultsView /> : null}

      {prefixHash ? (
        <div className="prepare-stamp-banner">
          <div>
            <strong>Prefix stamped · {prefixHash}</strong>
            <p>
              Cleaning, reanalysis and the sensor set are frozen. The engine crosses
              methodology on top of this.
            </p>
          </div>
          <button type="button" className="primary-button" onClick={() => setActivePhase("run")}>
            Design the sweep
          </button>
        </div>
      ) : null}
    </div>
  );
}
