import { afterEach, describe, expect, it, vi } from "vitest";

import { LAYOUT_KEY, PANELS, forgetLayout, storedLayout } from "../workbench/shell/layout";
import { readStored, writeStored } from "../workbench/storage";

const panel = (component: string) => ({ id: component, contentComponent: component, title: component });

describe("the workbench layout in browser storage", () => {
  afterEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it("is restored when it describes the workbench's panels", () => {
    const layout = { grid: {}, panels: { timeline: panel("timeline"), rose: panel("rose") } };
    window.localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout));
    expect(storedLayout()).toEqual(layout);
  });

  it("is ignored when it is not JSON, empty, or names a panel the workbench does not have", () => {
    window.localStorage.setItem(LAYOUT_KEY, "{not json");
    expect(storedLayout()).toBeNull();
    window.localStorage.setItem(LAYOUT_KEY, JSON.stringify({ grid: {}, panels: {} }));
    expect(storedLayout()).toBeNull();
    window.localStorage.setItem(LAYOUT_KEY, JSON.stringify({ grid: {}, panels: { old: panel("sweepMonitor") } }));
    expect(storedLayout()).toBeNull();
  });

  it("is forgotten on reset", () => {
    window.localStorage.setItem(LAYOUT_KEY, "{}");
    forgetLayout();
    expect(window.localStorage.getItem(LAYOUT_KEY)).toBeNull();
  });

  it("names the Prepare panels of plan §3.2 and the reanalysis panel", () => {
    expect(Object.values(PANELS)).toEqual(["Data", "Reanalysis", "Timeline", "Scatter", "Wind rose", "Profile", "Inspector"]);
  });

  it("falls back quietly when storage refuses", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(readStored(LAYOUT_KEY)).toBeNull();
    expect(() => writeStored(LAYOUT_KEY, "{}")).not.toThrow();
    expect(storedLayout()).toBeNull();
  });
});
