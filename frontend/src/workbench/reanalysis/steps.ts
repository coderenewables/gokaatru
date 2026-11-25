export type Provider = "brighthub" | "earthdatahub";
export type Dataset = "ERA5" | "MERRA-2";
export type Phase = "finding_nodes" | "downloading" | "interpolating";

export interface GridNode {
  latitude: number;
  longitude: number;
  distance_km?: number | null;
}

export interface Progress {
  phase: Phase;
  dataset: Dataset;
  current?: number;
  total?: number;
  node?: GridNode;
}

export interface NodeOutcome {
  dataset: Dataset;
  node: GridNode;
  /** `hit` (the project's cache covered the campaign), `downloaded` or `empty`; null where the
   * route does not say (the direct EarthDataHub extraction). */
  cache: string | null;
}

export const PROVIDER_NAMES: Record<Provider, string> = {
  brighthub: "BrightHub",
  earthdatahub: "EarthDataHub (direct)",
};

/** What each provider can supply: EarthDataHub's direct store holds ERA5 only. */
export function datasetsFor(provider: Provider): Dataset[] {
  return provider === "brighthub" ? ["ERA5", "MERRA-2"] : ["ERA5"];
}

/** The interpolation route's `source` for a dataset. */
export function interpolationSource(dataset: Dataset): "era5" | "merra2" {
  return dataset === "ERA5" ? "era5" : "merra2";
}

/** Nearest first, so a refusal part-way leaves the closest nodes done and the order is the
 * same whatever order the service listed them in. */
export function sortByDistance<T extends GridNode>(nodes: readonly T[]): T[] {
  return [...nodes].sort(
    (a, b) => (a.distance_km ?? Number.POSITIVE_INFINITY) - (b.distance_km ?? Number.POSITIVE_INFINITY),
  );
}

export function coordinateText(latitude: number, longitude: number): string {
  const lat = `${Math.abs(latitude).toFixed(2)}°${latitude < 0 ? "S" : "N"}`;
  const lon = `${Math.abs(longitude).toFixed(2)}°${longitude < 0 ? "W" : "E"}`;
  return `${lat} ${lon}`;
}

export function nodeText(node: GridNode): string {
  const where = coordinateText(node.latitude, node.longitude);
  return node.distance_km === null || node.distance_km === undefined
    ? where
    : `${where}, ${node.distance_km.toFixed(1)} km from the site`;
}

export function progressText(progress: Progress): string {
  if (progress.phase === "finding_nodes") return `Finding ${progress.dataset} nodes around the site`;
  if (progress.phase === "interpolating") return `Interpolating ${progress.dataset} to the site`;
  const of = progress.current !== undefined && progress.total !== undefined ? ` node ${progress.current} of ${progress.total}` : "";
  return `${progress.dataset}${of}`;
}

/** The step a failure is reported against. */
export function stepText(progress: Progress, provider: Provider): string {
  const verb = provider === "brighthub" ? "Downloading" : "Extracting";
  if (progress.phase === "downloading") return `${verb} ${progressText(progress)}`;
  return progressText(progress);
}

export function cacheText(cache: string | null): string {
  if (cache === "hit") return "from the project's cache";
  if (cache === "downloaded") return "downloaded";
  if (cache === "empty") return "no rows returned";
  return "extracted";
}

export interface Loaded {
  dataset: Dataset;
  nodes: number;
  cached: number;
  interpolated: boolean;
}

export function summarise(outcomes: readonly NodeOutcome[], interpolated: readonly Dataset[]): Loaded[] {
  const order: Dataset[] = ["ERA5", "MERRA-2"];
  return order
    .map((dataset) => {
      const own = outcomes.filter((outcome) => outcome.dataset === dataset);
      return {
        dataset,
        nodes: own.length,
        cached: own.filter((outcome) => outcome.cache === "hit").length,
        interpolated: interpolated.includes(dataset),
      };
    })
    .filter((row) => row.nodes > 0);
}

export function loadedText(row: Loaded): string {
  const nodes = `${row.nodes} ${row.nodes === 1 ? "node" : "nodes"}`;
  const cached = row.cached > 0 ? `, ${row.cached} from the cache` : "";
  return `${row.dataset}: ${nodes}${cached}, ${row.interpolated ? "interpolated to the site" : "not interpolated"}`;
}
