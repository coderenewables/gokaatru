import { afterEach, describe, expect, it } from "vitest";

import { describeTerm } from "../workbench/selection/describe";
import {
  type Definition,
  crossfilter,
  inlineSelection,
  unionOf,
  useSelection,
} from "../workbench/selection/store";

const march: Definition = { kind: "time_range", start: "2023-03-01T00:00:00Z", end: "2023-03-08T00:00:00Z" };
const may: Definition = { kind: "time_range", start: "2023-05-01T00:00:00Z", end: "2023-05-03T00:00:00Z" };
const west: Definition = { kind: "sector", channel: "Dir_100m", from_deg: 240, to_deg: 300 };
const box: Definition = {
  kind: "intersection",
  of: [
    { kind: "band", channel: "Spd_80m", min: 4, max: 9 },
    { kind: "band", channel: "Spd_100m", min: 5, max: 11 },
  ],
};

describe("the crossfilter selection", () => {
  afterEach(() => useSelection.getState().clearAll());

  it("is nothing until a view draws a term, then that term alone", () => {
    expect(crossfilter({})).toBeNull();
    expect(inlineSelection(null)).toBe("");
    expect(crossfilter({ rose: west })).toEqual(west);
  });

  it("intersects the views' terms in a fixed order, whatever order they were drawn in", () => {
    expect(crossfilter({ rose: west, timeline: march, scatter: box })).toEqual({
      kind: "intersection",
      of: [march, box, west],
    });
  });

  it("replaces a view's term, or with Shift adds to it as a union", () => {
    const { draw } = useSelection.getState();
    draw("timeline", march);
    draw("timeline", may);
    expect(useSelection.getState().terms.timeline).toEqual(may);
    draw("timeline", march, true);
    expect(useSelection.getState().terms.timeline).toEqual({ kind: "union", of: [may, march] });
    draw("timeline", may, true);
    expect(useSelection.getState().terms.timeline).toEqual({ kind: "union", of: [may, march, may] });
    expect(unionOf(march, may)).toEqual({ kind: "union", of: [march, may] });
  });

  it("clears one view's term, or every term", () => {
    const { draw, clear, clearAll } = useSelection.getState();
    draw("timeline", march);
    draw("rose", west);
    clear("timeline");
    expect(useSelection.getState().terms).toEqual({ rose: west });
    clearAll();
    expect(useSelection.getState().terms).toEqual({});
  });

  it("words each kind of term for its chip", () => {
    expect(describeTerm(march)).toBe("2023-03-01 00:00 UTC to 2023-03-08 00:00 UTC");
    expect(describeTerm(west)).toBe("Dir_100m 240° to 300°");
    expect(describeTerm(box)).toBe("Spd_80m 4 to 9, Spd_100m 5 to 11");
    expect(describeTerm(unionOf(march, may))).toBe(
      "2023-03-01 00:00 UTC to 2023-03-08 00:00 UTC or 2023-05-01 00:00 UTC to 2023-05-03 00:00 UTC",
    );
    expect(
      describeTerm({ kind: "polygon", x_channel: "Spd_80m", y_channel: "Spd_100m", vertices: [[0, 0], [1, 0], [1, 1]] }),
    ).toBe("Spd_80m against Spd_100m, lasso of 3 points");
    expect(describeTerm({ kind: "band", channel: "Spd_80m", min: 2.5 })).toBe("Spd_80m at least 2.5");
  });

  it("is sent inline as the JSON the server's selection parameter takes", () => {
    expect(JSON.parse(inlineSelection(crossfilter({ timeline: march, rose: west })))).toEqual({
      kind: "intersection",
      of: [march, west],
    });
  });
});
