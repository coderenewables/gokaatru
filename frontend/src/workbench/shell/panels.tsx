import type { IDockviewPanelProps } from "dockview-react";
import type { FunctionComponent } from "react";

import { DataPanel } from "../datatree/DataPanel";
import { InspectorPanel } from "../inspector/InspectorPanel";
import { RosePanel } from "../rose/RosePanel";
import { TimelinePanel } from "../timeline/TimelinePanel";
import { PANELS, type PanelId } from "./layout";

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
  inspector: "What is selected, and what can be done with it.",
};

function emptyPanel(id: PanelId): FunctionComponent<IDockviewPanelProps> {
  function Panel() {
    return <EmptyPanel>{EMPTY[id]}</EmptyPanel>;
  }
  Panel.displayName = `${PANELS[id].replace(/\s/g, "")}Panel`;
  return Panel;
}

/** The view each panel id renders; a view not built yet shows what it will hold. */
const BUILT: Partial<Record<PanelId, FunctionComponent<IDockviewPanelProps>>> = {
  data: DataPanel,
  inspector: InspectorPanel,
  rose: RosePanel,
  timeline: TimelinePanel,
};

export function panelComponents(): Record<PanelId, FunctionComponent<IDockviewPanelProps>> {
  const ids = Object.keys(PANELS) as PanelId[];
  return Object.fromEntries(ids.map((id) => [id, BUILT[id] ?? emptyPanel(id)])) as Record<
    PanelId,
    FunctionComponent<IDockviewPanelProps>
  >;
}
