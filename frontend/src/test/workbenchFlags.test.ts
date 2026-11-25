import { describe, expect, it } from "vitest";

import {
  defaultInstrument,
  flagProblem,
  instrumentColumns,
  reasonLabel,
  selectionFlagBody,
} from "../workbench/inspector/flagForm";
import { contiguousBounds } from "../workbench/rose/geometry";

const instrument = (name: string, type: string, height: number, statistics: string[] = [], inData = true) => ({
  name, sensor_type: type, height_m: height, statistics, in_data: inData, mapped_as: null,
});

describe("the flag form", () => {
  it("covers the whole instrument, the highest cup in the data by default", () => {
    const listed = [
      instrument("Tmp_120m", "temperature", 120),
      instrument("Spd_120m", "wind_speed", 120, [], false),
      instrument("Spd_100m", "wind_speed", 100, ["Spd_100m_sd", "Spd_100m_max"]),
    ];
    expect(defaultInstrument(listed)?.name).toBe("Spd_100m");
    expect(instrumentColumns(listed[2])).toEqual(["Spd_100m", "Spd_100m_sd", "Spd_100m_max"]);
    expect(instrumentColumns(undefined)).toEqual([]);
  });

  it("says what is missing before a flag can be applied", () => {
    expect(flagProblem([], "icing", "")).toBe("Tick at least one column to flag.");
    expect(flagProblem(["Spd_100m"], "", "")).toBe("Choose a reason.");
    expect(flagProblem(["Spd_100m"], "other", "  ")).toMatch(/needs a note/);
    expect(flagProblem(["Spd_100m"], "other", "bird")).toBeNull();
  });

  it("freezes the selection into one exclude_selection rule over the ticked columns", () => {
    const definition = { kind: "time_range" as const, start: "2023-03-14T00:00:00Z", end: "2023-03-15T00:00:00Z" };
    const body = selectionFlagBody(definition, ["Spd_100m", "Spd_100m_sd"], "icing", " frozen ");
    expect(body).toMatchObject({ rule_type: "exclude_selection", sensor: "Spd_100m", start_date: "", end_date: "" });
    expect(JSON.parse(body.params)).toEqual({ definition, sensors: ["Spd_100m_sd"], reason: "icing", note: "frozen" });
    expect(reasonLabel("mast_or_boom_effect")).toBe("Mast or boom effect");
  });

  it("turns one run of rose sectors into a tower-shadow range, wrapping through north", () => {
    expect(contiguousBounds([8, 9])).toEqual([225, 285]);
    expect(contiguousBounds([11, 0, 1])).toEqual([315, 45]);
    expect(contiguousBounds([0])).toEqual([345, 15]);
    expect(contiguousBounds([2, 5])).toBeNull();
    expect(contiguousBounds([])).toBeNull();
    expect(contiguousBounds([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11])).toBeNull();
  });
});
