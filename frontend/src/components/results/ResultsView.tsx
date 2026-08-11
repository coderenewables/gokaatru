// Results — read-only aggregate view across all workflow stages.
//
// A single-screen presentation of a completed (or partially completed)
// analysis run for a seasoned wind resource analyst. This page NEVER triggers
// computation: it reads state already in the store and renders
// already-computed Plotly figures via PlotFrame / lightweight load* summary
// selectors (the same read-only pattern SensorReviewView uses). No RunButton,
// no mutating store actions.
import { useMemo, useState } from "react";

import { useWorkspaceStore } from "../../store/useWorkspaceStore";
import { RESULTS_SECTIONS, type ResultsSectionId } from "./resultsSections";
import { RunOverviewSection } from "./RunOverviewSection";
import { MeasuredDataSection } from "./MeasuredDataSection";
import { ShearSection } from "./ShearSection";
import { ReanalysisSection } from "./ReanalysisSection";
import { LtcSection } from "./LtcSection";
import { EnsembleUncertaintySection } from "./EnsembleUncertaintySection";
import { ClippingScenariosSection } from "./ClippingScenariosSection";

export function ResultsView() {
  const clippingReport = useWorkspaceStore((state) => state.clippingReport);
  const scenarios = useWorkspaceStore((state) => state.scenarios);

  // The Clipping & Scenarios section only appears when there is data for it.
  const hasClippingData = clippingReport != null || scenarios.length > 0;
  const sections = useMemo(
    () =>
      RESULTS_SECTIONS.filter((section) => section.id !== "clipping" || hasClippingData),
    [hasClippingData],
  );

  const [activeSection, setActiveSection] = useState<ResultsSectionId>("measured");
  const resolvedSection = sections.some((s) => s.id === activeSection)
    ? activeSection
    : sections[0]?.id ?? "measured";

  return (
    <div className="sensor-overview-view">
      <header className="sensor-overview-header">
        <div>
          <p className="sensor-overview-eyebrow">Analysis results</p>
          <h2>Results</h2>
          <p className="muted">
            A read-only summary of everything this session has produced so far. Open a section to
            review measured data, reanalysis, long-term correction, ensemble, and uncertainty.
          </p>
        </div>
      </header>

      {/* Always-visible run overview: what has been done and what's missing. */}
      <RunOverviewSection />

      <div className="sensor-overview-layout">
        <nav className="sensor-overview-nav" aria-label="Results sections">
          {sections.map((section) => (
            <button
              key={section.id}
              type="button"
              className={resolvedSection === section.id ? "active" : undefined}
              aria-current={resolvedSection === section.id ? "page" : undefined}
              onClick={() => setActiveSection(section.id)}
            >
              {section.label}
            </button>
          ))}
        </nav>

        <div className="sensor-overview-content">
          {resolvedSection === "measured" ? <MeasuredDataSection /> : null}
          {resolvedSection === "shear" ? <ShearSection /> : null}
          {resolvedSection === "reanalysis" ? <ReanalysisSection /> : null}
          {resolvedSection === "ltc" ? <LtcSection /> : null}
          {resolvedSection === "ensemble" ? <EnsembleUncertaintySection /> : null}
          {resolvedSection === "clipping" && hasClippingData ? <ClippingScenariosSection /> : null}
        </div>
      </div>
    </div>
  );
}
