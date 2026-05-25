import { buildRunconfigUpdates, hydrateConfigFromRunconfig, serializeConfigToRunconfig, setConfigValue } from "../lib/configSync";

describe("config sync", () => {
  it("hydrates known top-level session fields into the typed config", () => {
    const config = hydrateConfigFromRunconfig({
      project_name: "Horns Rev",
      measurement_type: "lidar",
      hub_height_m: 140,
      location: { latitude: 55.52, longitude: 7.89, elevation_m: 12 },
    });

    expect(config.project.name).toBe("Horns Rev");
    expect(config.project.measurementType).toBe("lidar");
    expect(config.site.hubHeightM).toBe(140);
    expect(config.site.latitude).toBeCloseTo(55.52);
  });

  it("builds dotted runconfig updates only for changed values", () => {
    const base = serializeConfigToRunconfig(hydrateConfigFromRunconfig({ project_name: "Baseline" }));
    const modified = serializeConfigToRunconfig(setConfigValue(hydrateConfigFromRunconfig({ project_name: "Baseline" }), "site.hubHeightM", 160));
    const updates = buildRunconfigUpdates(base, modified);

    expect(updates.find((update) => update.key === "hub_height_m")?.value).toBe(160);
    expect(updates.find((update) => update.key === "site.hubHeightM")?.value).toBe(160);
  });
});