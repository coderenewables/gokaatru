import type { DockviewApi, SerializedDockview } from "dockview-react";
import { readStored, writeStored } from "../storage";

/** The phases of the work (plan §3.2), each its own arrangement of panels. */
export const PHASES = {
  prepare: "Prepare",
  model: "Model",
  run: "Run",
  interrogate: "Interrogate",
} as const;

export type PhaseId = keyof typeof PHASES;

/** The panels of Prepare (plan §3.2). Each id is also its dockview component name. */
export const PANELS = {
  data: "Data",
  reanalysis: "Reanalysis",
  timeline: "Timeline",
  scatter: "Scatter",
  rose: "Wind rose",
  profile: "Profile",
  inspector: "Inspector",
  rules: "Cleaning rules",
  overview: "Sensor overview",
} as const;

/** Every phase's panels; ids are unique across phases, as dockview names components by them. */
export const PHASE_PANELS = {
  prepare: PANELS,
  model: { palette: "Methods", pipeline: "Pipeline", step: "Step" },
  run: { matrix: "Sweep design", monitor: "Run" },
  interrogate: {
    scenarios: "Scenarios",
    distribution: "Distribution",
    parallel: "Parallel coordinates",
    sensitivity: "Sensitivity",
    gates: "Gates",
    pinned: "Side by side",
  },
} as const satisfies Record<PhaseId, Record<string, string>>;

export type PanelId = { [P in PhaseId]: keyof (typeof PHASE_PANELS)[P] }[PhaseId];

/** Every panel's title, whatever its phase. */
export const PANEL_TITLES: Record<PanelId, string> = Object.assign({}, ...Object.values(PHASE_PANELS));

export function isPhase(value: string | null | undefined): value is PhaseId {
  return value !== null && value !== undefined && value in PHASES;
}

/** The phase the address names, Prepare when it names none or one that does not exist. */
export function phaseFromAddress(search: string): PhaseId {
  const phase = new URLSearchParams(search).get("phase");
  return isPhase(phase) ? phase : "prepare";
}

/** Versioned with the panel set: an arrangement saved before a panel existed would hide it.
 * v3 adds the cleaning rules and the sensor overview, which a v2 arrangement lacks. */
export const LAYOUT_KEY = "gk-workbench-layout-v3";

export function layoutKey(phase: PhaseId): string {
  return phase === "prepare" ? LAYOUT_KEY : `gk-workbench-layout-v1-${phase}`;
}

type Placement = { id: PanelId; next?: { to: PanelId; direction: "left" | "right" | "below" | "above" | "within" }; inactive?: boolean };

/** Each phase's arrangement: Prepare's is plan §3.2 (data on the left, the timeline across the
 * top, three charts below, the inspector on the right). */
const ARRANGEMENT: Record<PhaseId, { panels: Placement[]; sizes: [PanelId, number][]; active: PanelId }> = {
  prepare: {
    panels: [
      { id: "timeline" },
      { id: "data", next: { to: "timeline", direction: "left" } },
      { id: "reanalysis", next: { to: "data", direction: "within" }, inactive: true },
      { id: "inspector", next: { to: "timeline", direction: "right" } },
      { id: "rules", next: { to: "inspector", direction: "within" }, inactive: true },
      { id: "scatter", next: { to: "timeline", direction: "below" } },
      { id: "overview", next: { to: "scatter", direction: "within" }, inactive: true },
      { id: "rose", next: { to: "scatter", direction: "right" } },
      { id: "profile", next: { to: "rose", direction: "right" } },
    ],
    sizes: [["data", 240], ["inspector", 300]],
    active: "timeline",
  },
  model: {
    panels: [
      { id: "pipeline" },
      { id: "palette", next: { to: "pipeline", direction: "left" } },
      { id: "step", next: { to: "pipeline", direction: "right" } },
    ],
    sizes: [["palette", 240], ["step", 340]],
    active: "pipeline",
  },
  run: {
    panels: [{ id: "matrix" }, { id: "monitor", next: { to: "matrix", direction: "right" } }],
    sizes: [["monitor", 380]],
    active: "matrix",
  },
  interrogate: {
    panels: [
      { id: "distribution" },
      { id: "parallel", next: { to: "distribution", direction: "right" } },
      { id: "scenarios", next: { to: "distribution", direction: "below" } },
      { id: "sensitivity", next: { to: "scenarios", direction: "right" } },
      { id: "gates", next: { to: "sensitivity", direction: "within" }, inactive: true },
      { id: "pinned", next: { to: "sensitivity", direction: "within" }, inactive: true },
    ],
    sizes: [],
    active: "distribution",
  },
};

export function addDefaultLayout(api: DockviewApi, phase: PhaseId = "prepare"): void {
  api.clear();
  const arrangement = ARRANGEMENT[phase];
  for (const placement of arrangement.panels) {
    api.addPanel({
      id: placement.id,
      component: placement.id,
      title: PANEL_TITLES[placement.id],
      ...(placement.next ? { position: { referencePanel: placement.next.to, direction: placement.next.direction } } : {}),
      ...(placement.inactive ? { inactive: true } : {}),
    });
  }
  for (const [id, width] of arrangement.sizes) api.getPanel(id)?.group.api.setSize({ width });
  api.getPanel(arrangement.active)?.api.setActive();
}

/** A saved arrangement, or null when none is stored or it no longer describes these panels. */
export function storedLayout(phase: PhaseId = "prepare"): SerializedDockview | null {
  const raw = readStored(layoutKey(phase));
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as SerializedDockview;
    const known = new Set(Object.keys(PHASE_PANELS[phase]));
    const panels = Object.values(parsed.panels ?? {});
    return panels.length > 0 && panels.every((panel) => known.has(String(panel.contentComponent))) ? parsed : null;
  } catch {
    return null;
  }
}

export function saveLayout(api: DockviewApi, phase: PhaseId = "prepare"): void {
  writeStored(layoutKey(phase), JSON.stringify(api.toJSON()));
}

export function forgetLayout(phase: PhaseId = "prepare"): void {
  writeStored(layoutKey(phase), null);
}
