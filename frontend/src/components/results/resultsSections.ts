// Results view section registry.
//
// Kept separate from ResultsView.tsx so the orchestrator stays thin (same
// spirit as lib/stages.ts). `RunOverviewSection` is the always-visible header
// and is intentionally NOT a switchable nav item.

export type ResultsSectionId =
  | "measured"
  | "shear"
  | "reanalysis"
  | "ltc"
  | "ensemble"
  | "clipping";

export interface ResultsSectionMeta {
  id: ResultsSectionId;
  label: string;
}

export const RESULTS_SECTIONS: ResultsSectionMeta[] = [
  { id: "measured", label: "Measured Data" },
  { id: "shear", label: "Shear & Extrapolation" },
  { id: "reanalysis", label: "Reanalysis" },
  { id: "ltc", label: "Long-Term Correction" },
  { id: "ensemble", label: "Ensemble & Uncertainty" },
  { id: "clipping", label: "Clipping & Scenarios" },
];
