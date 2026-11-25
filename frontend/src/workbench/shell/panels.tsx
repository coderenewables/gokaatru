import type { IDockviewPanelProps } from "dockview-react";
import type { FunctionComponent } from "react";

import { DataPanel } from "../datatree/DataPanel";
import { InspectorPanel } from "../inspector/InspectorPanel";
import { PalettePanel } from "../model/PalettePanel";
import { PipelinePanel } from "../model/PipelinePanel";
import { StepPanel } from "../model/StepPanel";
import { ProfilePanel } from "../profile/ProfilePanel";
import { ReanalysisPanel } from "../reanalysis/ReanalysisPanel";
import { RosePanel } from "../rose/RosePanel";
import { ScatterPanel } from "../scatter/ScatterPanel";
import { TimelinePanel } from "../timeline/TimelinePanel";
import { PANEL_TITLES, PHASE_PANELS, type PanelId, type PhaseId } from "./layout";

/** What a panel shows before its view is built or before a campaign holds data for it. Not a
 * landmark of its own: dockview's group around it is already the region named after the
 * panel, and a second one of the same name is axe's landmark-unique. */
export function EmptyPanel({ children }: { children: string }) {
  return (
    <div className="gk-panel gk-panel-empty">
      <p>{children}</p>
    </div>
  );
}

const EMPTY: Record<PanelId, string> = {
  data: "The campaign's channels, by height, appear here once its data is loaded.",
  timeline: "Every channel over time, with flags as bands. Drag across it to select a period.",
  scatter: "Two channels against each other. Lasso the points that disagree.",
  rose: "Direction frequency by sector. Click a sector to select it.",
  profile: "Mean speed by height for the selection.",
  reanalysis: "Reanalysis nodes around the site, taken one at a time and interpolated to it.",
  inspector: "What is selected, and what can be done with it.",
  palette: "The methods, by stage. Drag one onto the pipeline.",
  pipeline: "The campaign's chain of methods, in the order their inputs require.",
  step: "The selected step's parameters, status and result.",
  matrix: "The sweep's axes by their levels. Tick the cells to sweep.",
  monitor: "The sweep as it runs, scenario by scenario.",
  scenarios: "Every scenario of the sweep, filtered by the brushes.",
  distribution: "A metric's distribution across the scenarios. Brush a range to filter.",
  parallel: "Each scenario across the metrics and axes. Brush an axis to filter.",
  sensitivity: "How much each axis moves the metric.",
  gates: "Which scenarios each admissibility gate let through.",
  pinned: "Two scenarios side by side, configuration and results.",
};

function emptyPanel(id: PanelId): FunctionComponent<IDockviewPanelProps> {
  function Panel() {
    return <EmptyPanel>{EMPTY[id]}</EmptyPanel>;
  }
  Panel.displayName = `${PANEL_TITLES[id].replace(/\s/g, "")}Panel`;
  return Panel;
}

/** The view each panel id renders; a view not built yet shows what it will hold. */
const BUILT: Partial<Record<PanelId, FunctionComponent<IDockviewPanelProps>>> = {
  data: DataPanel,
  inspector: InspectorPanel,
  palette: PalettePanel,
  pipeline: PipelinePanel,
  profile: ProfilePanel,
  reanalysis: ReanalysisPanel,
  rose: RosePanel,
  scatter: ScatterPanel,
  step: StepPanel,
  timeline: TimelinePanel,
};

export function panelComponents(phase: PhaseId = "prepare"): Record<string, FunctionComponent<IDockviewPanelProps>> {
  const ids = Object.keys(PHASE_PANELS[phase]) as PanelId[];
  return Object.fromEntries(ids.map((id) => [id, BUILT[id] ?? emptyPanel(id)]));
}
