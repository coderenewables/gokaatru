import { describe, expect, it } from "vitest";

import { describeSite, formatChange, kindLabel, timezoneNotice } from "../workbench/projects/helpers";

describe("project helpers", () => {
  it("names each declared timezone in the notice and skips undeclared ones", () => {
    expect(
      timezoneNotice([
        { name: "Mast", timezone: "UTC+0" },
        { name: "Lidar", timezone: "UTC+1" },
        { name: "Empty", timezone: null },
      ]),
    ).toBe("The campaigns declare different timezones: Mast UTC+0; Lidar UTC+1.");
  });

  it("describes a site from what is known and says so when nothing is", () => {
    expect(describeSite({ latitude: 55.25, longitude: 7.75, elevation_m: 12.4, timezone: "UTC+1" })).toBe(
      "55.2500°, 7.7500° · 12 m · UTC+1",
    );
    expect(describeSite({ latitude: null, longitude: null, timezone: null })).toBe("No site declared yet");
    expect(describeSite({ latitude: 0, longitude: 0 })).toBe("0.0000°, 0.0000°");
  });

  it("formats a change in UTC and labels the kinds", () => {
    expect(formatChange("2026-11-25T13:05:59+00:00")).toBe("2026-11-25 13:05 UTC");
    expect(formatChange("not a date")).toBe("not a date");
    expect(kindLabel("floating_lidar")).toBe("Floating lidar");
  });
});
