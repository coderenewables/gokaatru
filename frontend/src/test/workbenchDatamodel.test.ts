import { describe, expect, it } from "vitest";

import { classify, inLoadOrder } from "../workbench/datamodel/loading";
import {
  EMPTY_LOCATION,
  blockers,
  buildSpec,
  chipsFromDraft,
  chipsFromSpec,
  edit,
  levels,
  locationFromSpec,
  parseNumber,
  unplaced,
} from "../workbench/datamodel/spec";

const column = (over: Record<string, unknown>) => ({
  name: "x",
  role: "measurement",
  measurement_type_id: "wind_speed",
  height_m: null,
  statistic_type_id: null,
  parent: null,
  reason: null,
  ...over,
});

const draft = [
  column({ name: "Spd_80m", height_m: 80 }),
  column({ name: "Spd_80m_sd", role: "statistic", statistic_type_id: "sd", parent: "Spd_80m", height_m: 80 }),
  column({ name: "Spd_80m_max", role: "statistic", statistic_type_id: "max", parent: "Spd_80m", height_m: 80 }),
  column({ name: "Dir_100m", measurement_type_id: "wind_direction", height_m: 100 }),
  column({ name: "WS_Avg", reason: "No height token in the header — declare the height in metres." }),
  column({ name: "Batt", role: "ignored", measurement_type_id: null, reason: "not a sensor" }),
];
const WHERE = { ...EMPTY_LOCATION, offset: "0" };

describe("the draft as chips", () => {
  const drafted = chipsFromDraft(draft as never);
  it("keeps standard deviations with their parent and lists the rest as not built", () => {
    expect(drafted.chips.map((chip) => chip.name)).toEqual(["Spd_80m", "Dir_100m", "WS_Avg"]);
    expect(drafted.chips[0].statistics).toEqual([{ column_name: "Spd_80m_sd", statistic_type_id: "sd" }]);
    expect(drafted.notBuilt.map((item) => item.name)).toEqual(["Spd_80m_max", "Batt"]);
  });
  it("leaves a column with no height without one, with the draft's reason", () => {
    expect(unplaced(drafted.chips).map((chip) => chip.name)).toEqual(["WS_Avg"]);
    expect(drafted.chips[2].height).toBeNull();
    expect(drafted.chips[2].reason).toContain("declare the height");
  });
  it("orders levels highest first, once each", () => {
    const moved = edit(drafted.chips, "WS_Avg", { height: 80 });
    expect(levels(moved)).toEqual([100, 80]);
    expect(unplaced(moved)).toEqual([]);
    expect(moved[2].reason).toBeNull();
  });
});

describe("what blocks a build", () => {
  const chips = chipsFromDraft(draft as never).chips;
  it("names the column with no height and the missing timezone", () => {
    const reasons = blockers(chips, EMPTY_LOCATION);
    expect(reasons.some((reason) => reason.includes("WS_Avg"))).toBe(true);
    expect(reasons.some((reason) => reason.toLowerCase().includes("timezone"))).toBe(true);
  });
  it("accepts an offset of zero, which is a timezone", () => {
    expect(blockers(edit(chips, "WS_Avg", { height: 60 }), WHERE)).toEqual([]);
  });
  it("accepts an IANA name instead of an offset", () => {
    expect(blockers(edit(chips, "WS_Avg", { height: 60 }), { ...EMPTY_LOCATION, timezone: "Europe/Copenhagen" })).toEqual([]);
  });
  it("refuses a lone coordinate, a bad number and an offset out of range", () => {
    const placed = edit(chips, "WS_Avg", { height: 60 });
    expect(blockers(placed, { ...WHERE, latitude: "55" }).join(" ")).toContain("both the latitude and the longitude");
    expect(blockers(placed, { ...WHERE, latitude: "x", longitude: "1" }).join(" ")).toContain("latitude");
    expect(blockers(placed, { ...WHERE, offset: "30" }).join(" ")).toContain("offset");
  });
  it("refuses a boom outside 0 to 360", () => {
    expect(blockers(edit(chips, "Spd_80m", { boom: 360 }), WHERE).join(" ")).toContain("Spd_80m");
  });
});

describe("the spec", () => {
  const chips = edit(chipsFromDraft(draft as never).chips, "WS_Avg", { height: 60, boom: 90 });
  const where = { ...WHERE, name: "Ridge", latitude: "55.25", longitude: "7.75" };
  const spec = buildSpec(chips, where) as { location: Record<string, unknown>; points: Array<Record<string, unknown>> };
  it("carries the location, heights, boom and statistics", () => {
    expect(spec.location).toEqual({ name: "Ridge", latitude_ddeg: 55.25, longitude_ddeg: 7.75, offset_from_utc_hrs: 0 });
    expect(spec.points[0]).toEqual({
      name: "Spd_80m",
      measurement_type_id: "wind_speed",
      height_m: 80,
      statistics: [{ column_name: "Spd_80m_sd", statistic_type_id: "sd" }],
    });
    expect(spec.points[2]).toMatchObject({ name: "WS_Avg", height_m: 60, boom_orientation_deg: 90 });
  });
  it("reads back to the same chips and location, and adds unplaced drafted columns", () => {
    const back = chipsFromSpec(spec, chipsFromDraft(draft as never));
    expect(back).toEqual(chips.map((chip) => ({ ...chip, reason: null })));
    expect(locationFromSpec(spec)).toMatchObject({ name: "Ridge", latitude: "55.25", offset: "0" });
    const partial = chipsFromSpec({ ...spec, points: spec.points.slice(0, 2) }, chipsFromDraft(draft as never));
    expect(unplaced(partial).map((chip) => chip.name)).toEqual(["WS_Avg"]);
  });
});

describe("numbers and files", () => {
  it("parses a typed number, nothing for an empty field and NaN for text", () => {
    expect(parseNumber(" 12.5 ")).toBe(12.5);
    expect(parseNumber("")).toBeNull();
    expect(Number.isNaN(parseNumber("12 m"))).toBe(true);
  });
  it("classifies by extension and sends the records first", () => {
    expect(classify("a.CSV")).toBe("timeseries");
    expect(classify("a.xlsx")).toBe("timeseries");
    expect(classify("model.json")).toBe("datamodel");
    expect(classify("a.png")).toBeNull();
    const files = [new File([""], "model.json"), new File([""], "mast.csv")];
    expect(inLoadOrder(files).map((file) => file.name)).toEqual(["mast.csv", "model.json"]);
  });
});
