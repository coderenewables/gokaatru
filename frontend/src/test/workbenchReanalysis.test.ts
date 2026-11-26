import { describe, expect, it } from "vitest";

import {
  cacheText,
  coordinateText,
  datasetsFor,
  interpolationSource,
  loadedText,
  nodeText,
  progressText,
  sortByDistance,
  stepText,
  summarise,
  type NodeOutcome,
} from "../workbench/reanalysis/steps";

const node = (latitude: number, longitude: number, distance_km?: number) => ({ latitude, longitude, distance_km });

describe("the acquisition's steps", () => {
  it("takes ERA5 and MERRA-2 from BrightHub and ERA5 alone from EarthDataHub, each with its own interpolation source", () => {
    expect(datasetsFor("brighthub")).toEqual(["ERA5", "MERRA-2"]);
    expect(datasetsFor("earthdatahub")).toEqual(["ERA5"]);
    expect(interpolationSource("ERA5")).toBe("era5");
    expect(interpolationSource("MERRA-2")).toBe("merra2");
  });

  it("orders nodes nearest first, those without a distance last, and leaves its input alone", () => {
    const listed = [node(1, 1, 9.5), node(2, 2), node(3, 3, 2.1), node(4, 4, 5)];
    expect(sortByDistance(listed).map((n) => n.latitude)).toEqual([3, 4, 1, 2]);
    expect(listed.map((n) => n.latitude)).toEqual([1, 2, 3, 4]);
  });
});

describe("the progress wording", () => {
  it("names the phase, the dataset and the node's place in the set", () => {
    expect(progressText({ phase: "finding_nodes", dataset: "ERA5" })).toBe("Finding ERA5 nodes around the site");
    expect(progressText({ phase: "downloading", dataset: "MERRA-2", current: 3, total: 4 })).toBe("MERRA-2 node 3 of 4");
    expect(progressText({ phase: "interpolating", dataset: "MERRA-2" })).toBe("Interpolating MERRA-2 to the site");
  });

  it("words the failed step by what the provider does with a node", () => {
    const at = { phase: "downloading" as const, dataset: "ERA5" as const, current: 3, total: 4 };
    expect(stepText(at, "brighthub")).toBe("Downloading ERA5 node 3 of 4");
    expect(stepText(at, "earthdatahub")).toBe("Extracting ERA5 node 3 of 4");
    expect(stepText({ phase: "interpolating", dataset: "ERA5" }, "earthdatahub")).toBe("Interpolating ERA5 to the site");
  });

  it("writes a coordinate with its hemisphere and a node with its distance when known", () => {
    expect(coordinateText(55.25, 7.75)).toBe("55.25°N 7.75°E");
    expect(coordinateText(-33.9, -70.123)).toBe("33.90°S 70.12°W");
    expect(nodeText(node(55.25, 7.5, 12.34))).toBe("55.25°N 7.50°E, 12.3 km from the site");
    expect(nodeText(node(55.25, 7.5))).toBe("55.25°N 7.50°E");
  });

  it("says where a node came from", () => {
    expect(cacheText("hit")).toBe("from the project's cache");
    expect(cacheText("downloaded")).toBe("downloaded");
    expect(cacheText("empty")).toBe("no rows returned");
    expect(cacheText(null)).toBe("extracted");
  });
});

describe("what was loaded", () => {
  const outcomes: NodeOutcome[] = [
    { dataset: "ERA5", node: node(1, 1), cache: "hit" },
    { dataset: "ERA5", node: node(1, 2), cache: "downloaded" },
    { dataset: "MERRA-2", node: node(1, 1), cache: "hit" },
  ];

  it("counts nodes and cache hits per dataset, ERA5 first, and omits a dataset never taken", () => {
    expect(summarise(outcomes, ["ERA5"])).toEqual([
      { dataset: "ERA5", nodes: 2, cached: 1, interpolated: true },
      { dataset: "MERRA-2", nodes: 1, cached: 1, interpolated: false },
    ]);
    expect(summarise(outcomes.slice(0, 2), [])).toHaveLength(1);
    expect(summarise([], [])).toEqual([]);
  });

  it("words a row, singular and plural", () => {
    expect(loadedText({ dataset: "ERA5", nodes: 4, cached: 0, interpolated: true })).toBe(
      "ERA5: 4 nodes, interpolated to the site",
    );
    expect(loadedText({ dataset: "MERRA-2", nodes: 1, cached: 1, interpolated: false })).toBe(
      "MERRA-2: 1 node, 1 from the cache, not interpolated",
    );
  });
});
