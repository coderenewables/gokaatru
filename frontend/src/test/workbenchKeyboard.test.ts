import { describe, expect, it, vi } from "vitest";

import { historyLine } from "../workbench/history/useHistory";
import { matching } from "../workbench/shell/CommandPalette";
import { keyCommand } from "../workbench/shell/keys";
import { adjacentBand, type FlagBand } from "../workbench/timeline/helpers";

const press = (key: string, modifiers: { ctrl?: boolean; meta?: boolean; shift?: boolean } = {}, tag = "DIV") => ({
  key,
  ctrlKey: modifiers.ctrl ?? false,
  metaKey: modifiers.meta ?? false,
  shiftKey: modifiers.shift ?? false,
  target: { tagName: tag, isContentEditable: false } as unknown as EventTarget,
});

describe("the keyboard", () => {
  it("maps Ctrl or Cmd with Z, Shift+Z, Y and K, and leaves typing in a field alone", () => {
    expect(keyCommand(press("z", { ctrl: true }))).toBe("undo");
    expect(keyCommand(press("Z", { meta: true, shift: true }))).toBe("redo");
    expect(keyCommand(press("y", { ctrl: true }))).toBe("redo");
    expect(keyCommand(press("k", { ctrl: true }))).toBe("palette");
    expect(keyCommand(press("z"))).toBeNull();
    expect(keyCommand(press("z", { ctrl: true }, "INPUT"))).toBeNull();
    expect(keyCommand(press("z", { ctrl: true }, "TEXTAREA"))).toBeNull();
    expect(keyCommand(press("k", { ctrl: true }, "INPUT"))).toBe("palette");
  });

  it("narrows the palette by every word typed", () => {
    const run = vi.fn();
    const commands = [
      { id: "a", label: "Show the Wind rose panel", run },
      { id: "b", label: "Show the Timeline panel", run },
      { id: "c", label: "Undo the last change", run },
    ];
    expect(matching(commands, "show rose").map((command) => command.id)).toEqual(["a"]);
    expect(matching(commands, "  ").map((command) => command.id)).toEqual(["a", "b", "c"]);
    expect(matching(commands, "zzz")).toEqual([]);
  });

  it("says what an undo or redo changed", () => {
    expect(historyLine("Undid", { operation: "apply_cleaning_rule", parameters: { rule_type: "exclude_selection" } })).toBe(
      "Undid apply cleaning rule (exclude_selection).",
    );
    expect(historyLine("Redid", { operation: "remove_sensors", parameters: {} })).toBe("Redid remove sensors.");
  });

  it("steps through the flag bands in time with the arrow keys", () => {
    const band = (sensor: string, start: number, sequence: number): FlagBand => ({
      sensor,
      start,
      end: start + 10,
      interval: { first: `t${start}`, last: `t${start}`, next: null, records: 1, rule_sequence: sequence, rule_type: "r", reason: "x", actor: "user", flagged_at: "" },
    });
    const bands = [band("Spd_80m", 50, 2), band("Spd_100m", 10, 1), band("Spd_100m", 50, 2)];
    expect(adjacentBand(bands, null, 1)?.start).toBe(10);
    expect(adjacentBand(bands, null, -1)?.sensor).toBe("Spd_80m");
    const first = adjacentBand(bands, null, 1);
    const second = adjacentBand(bands, first, 1);
    expect([second?.sensor, second?.start]).toEqual(["Spd_100m", 50]);
    expect(adjacentBand(bands, second, 1)?.sensor).toBe("Spd_80m");
    expect(adjacentBand(bands, adjacentBand(bands, null, -1), 1)).toBeNull();
    expect(adjacentBand([], null, 1)).toBeNull();
  });
});
