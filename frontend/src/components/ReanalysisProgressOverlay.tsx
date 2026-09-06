// Page-blocking progress popup shown while ERA5/MERRA-2 reanalysis data is being acquired
// (BrightHub or direct EarthDataHub). Both acquisition paths already work node-by-node
// server-side; this surfaces that granularity instead of a single opaque "Downloading..."
// label, since a single EarthDataHub node can take minutes and users need to see it's
// making progress rather than assume it's stuck (see CLAUDE.md's EarthDataHub notes).
import { useWorkspaceStore } from "../store/useWorkspaceStore";

const PROVIDER_LABEL: Record<"brighthub" | "earthdatahub", string> = {
  brighthub: "BrightHub",
  earthdatahub: "EarthDataHub (direct)",
};

function phaseTitle(phase: string, dataset: string | undefined, provider: "brighthub" | "earthdatahub"): string {
  const label = PROVIDER_LABEL[provider];
  if (phase === "finding_nodes") return `Finding ERA5 nodes — ${label}`;
  if (phase === "interpolating") return `Interpolating ${dataset ?? ""} to site — ${label}`;
  return `Downloading ${dataset ?? "reanalysis"} — ${label}`;
}

export function ReanalysisProgressOverlay() {
  const progress = useWorkspaceStore((state) => state.reanalysisProgress);
  if (!progress) return null;

  const { provider, phase, dataset, current, total, latitude, longitude, distanceKm } = progress;
  const hasNode = typeof latitude === "number" && typeof longitude === "number";
  const hasCount = typeof current === "number" && typeof total === "number";

  return (
    <div className="modal-overlay reanalysis-progress-overlay" role="alertdialog" aria-live="assertive">
      <div className="modal-card reanalysis-progress-card">
        <div className="reanalysis-progress-spinner" aria-hidden="true" />
        <h2>{phaseTitle(phase, dataset, provider)}</h2>
        {hasCount ? (
          <p className="reanalysis-progress-count">
            Node {current} of {total}
          </p>
        ) : null}
        {hasNode ? (
          <p className="reanalysis-progress-coord">
            lat {latitude.toFixed(4)}, lon {longitude.toFixed(4)}
            {typeof distanceKm === "number" ? ` · ${distanceKm.toFixed(1)} km from site` : ""}
          </p>
        ) : null}
        <p className="muted reanalysis-progress-note">
          {provider === "earthdatahub"
            ? "EarthDataHub's cold-read latency varies by grid cell — a single node can take from "
              + "seconds up to several minutes. This is expected; please keep this tab open."
            : "This can take a little while depending on BrightHub's response time."}
        </p>
      </div>
    </div>
  );
}
