import type { DragEndEvent } from "@dnd-kit/core";
import { afterEach, describe, expect, it, vi } from "vitest";

import { dropOnChart, useCharts } from "../workbench/charts/store";
import { type ChartDrop, resolveDrop } from "../workbench/dnd";

function drag(source: unknown, target: unknown): DragEndEvent {
  return {
    active: { data: { current: source } },
    over: target === undefined ? null : { data: { current: target } },
  } as unknown as DragEndEvent;
}

describe("dropping a channel on a chart", () => {
  afterEach(() => useCharts.getState().reset());

  it("hands the channel and the chart to the handler, and ignores anything else", () => {
    const onDrop = vi.fn();
    const timeline: ChartDrop = { kind: "timeline", shown: ["Spd_100m"] };
    resolveDrop(drag({ kind: "channel", channel: "Tmp_100m" }, timeline), onDrop);
    expect(onDrop).toHaveBeenCalledWith("Tmp_100m", timeline);
    resolveDrop(drag({ kind: "channel", channel: "Tmp_100m" }, undefined), onDrop);
    resolveDrop(drag({ kind: "panel" }, timeline), onDrop);
    expect(onDrop).toHaveBeenCalledTimes(1);
  });

  it("adds to the timeline once, sets a scatter axis and the rose's vane", () => {
    dropOnChart("Tmp_100m", { kind: "timeline", shown: ["Spd_100m", "Spd_80m"] });
    expect(useCharts.getState().timeline).toEqual(["Spd_100m", "Spd_80m", "Tmp_100m"]);
    dropOnChart("Spd_80m", { kind: "timeline", shown: ["Spd_100m", "Spd_80m"] });
    expect(useCharts.getState().timeline).toEqual(["Spd_100m", "Spd_80m"]);
    dropOnChart("Spd_60m", { kind: "scatter", axis: "x", shown: { x: "Spd_80m", y: "Spd_100m" } });
    expect(useCharts.getState().scatter).toEqual({ x: "Spd_60m", y: "Spd_100m" });
    dropOnChart("Dir_80m", { kind: "rose" });
    expect(useCharts.getState().rose).toBe("Dir_80m");
    useCharts.getState().removeFromTimeline("Spd_80m", ["Spd_100m", "Spd_80m"]);
    expect(useCharts.getState().timeline).toEqual(["Spd_100m"]);
    useCharts.getState().reset();
    expect(useCharts.getState()).toMatchObject({ timeline: null, scatter: null, rose: null });
  });
});
