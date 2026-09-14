// Interrogate phase (design doc: Interrogate) — Spread, Gates, Sensitivity and Summary
// as one scrolling report under a single metric switch, instead of four sub-tabs that
// each asked the analyst to re-pick the metric. Composes the existing sweep-result
// components unchanged; they already share one `metric` field on useSweepStore.
import { SpreadSummaryView } from "./sweep/SpreadSummaryView";
import { SpreadExplorer } from "./sweep/SpreadExplorer";
import { SensitivityView } from "./sweep/SensitivityView";
import { GateReportView } from "./sweep/GateReportView";

export function InterrogateView() {
  return (
    <div className="interrogate-view">
      <SpreadSummaryView />
      <SpreadExplorer />
      <SensitivityView />
      <GateReportView />
    </div>
  );
}
