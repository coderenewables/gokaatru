import type { DockviewApi, SerializedDockview } from "dockview-react";
import { readStored, writeStored } from "../storage";

/** The panels of Prepare (plan §3.2). Each id is also its dockview component name. */
export const PANELS = {
  data: "Data",
  reanalysis: "Reanalysis",
  timeline: "Timeline",
  scatter: "Scatter",
  rose: "Wind rose",
  profile: "Profile",
  inspector: "Inspector",
} as const;

export type PanelId = keyof typeof PANELS;

export const LAYOUT_KEY = "gk-workbench-layout-v1";

/** The arrangement of plan §3.2: data on the left, the timeline across the top, three charts
 * below it, the inspector on the right. */
export function addDefaultLayout(api: DockviewApi): void {
  api.clear();
  api.addPanel({ id: "timeline", component: "timeline", title: PANELS.timeline });
  api.addPanel({ id: "data", component: "data", title: PANELS.data, position: { referencePanel: "timeline", direction: "left" } });
  api.addPanel({ id: "reanalysis", component: "reanalysis", title: PANELS.reanalysis, position: { referencePanel: "data", direction: "within" }, inactive: true });
  api.addPanel({ id: "inspector", component: "inspector", title: PANELS.inspector, position: { referencePanel: "timeline", direction: "right" } });
  api.addPanel({ id: "scatter", component: "scatter", title: PANELS.scatter, position: { referencePanel: "timeline", direction: "below" } });
  api.addPanel({ id: "rose", component: "rose", title: PANELS.rose, position: { referencePanel: "scatter", direction: "right" } });
  api.addPanel({ id: "profile", component: "profile", title: PANELS.profile, position: { referencePanel: "rose", direction: "right" } });
  api.getPanel("data")?.group.api.setSize({ width: 240 });
  api.getPanel("inspector")?.group.api.setSize({ width: 300 });
  api.getPanel("timeline")?.api.setActive();
}

/** A saved arrangement, or null when none is stored or it no longer describes these panels. */
export function storedLayout(): SerializedDockview | null {
  const raw = readStored(LAYOUT_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as SerializedDockview;
    const known = new Set(Object.keys(PANELS));
    const panels = Object.values(parsed.panels ?? {});
    return panels.length > 0 && panels.every((panel) => known.has(String(panel.contentComponent))) ? parsed : null;
  } catch {
    return null;
  }
}

export function saveLayout(api: DockviewApi): void {
  writeStored(LAYOUT_KEY, JSON.stringify(api.toJSON()));
}

export function forgetLayout(): void {
  writeStored(LAYOUT_KEY, null);
}
