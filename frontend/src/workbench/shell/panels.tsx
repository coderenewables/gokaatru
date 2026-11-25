import type { IDockviewPanelProps } from "dockview-react";
import type { FunctionComponent } from "react";

import type { PanelId } from "./layout";

/** What a panel shows before its view is built or before a campaign holds data for it. Not a
 * landmark of its own: dockview's group around it is already the region named after the
 * panel, and a second one of the same name is axe's landmark-unique. */
export function EmptyPanel({ children }: { title: string; children: string }) {
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

export function emptyPanel(id: PanelId, title: string): FunctionComponent<IDockviewPanelProps> {
  function Panel() {
    return <EmptyPanel title={title}>{EMPTY[id]}</EmptyPanel>;
  }
  Panel.displayName = `${title.replace(/\s/g, "")}Panel`;
  return Panel;
}
