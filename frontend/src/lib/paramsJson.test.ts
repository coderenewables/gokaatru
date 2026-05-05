import { describe, expect, it } from "vitest";

import { parseLooseJson } from "./paramsJson";

describe("parseLooseJson", () => {
  it("repairs Windows paths that include an invalid unicode-style escape prefix", () => {
    const input = String.raw`{"file_path":"D:\gokaatru\data\uploads\HKW-B-FLS-Boxkite_timeseries_data.csv","alias":"HKW-B-FLS-Boxkite"}`;

    const result = parseLooseJson(input);

    expect(result).toEqual({
      ok: true,
      recovered: true,
      value: {
        file_path: String.raw`D:\gokaatru\data\uploads\HKW-B-FLS-Boxkite_timeseries_data.csv`,
        alias: "HKW-B-FLS-Boxkite",
      },
    });
  });
});