import { describe, expect, it } from "vitest";

import { toMetricRows, flattenConfigDiff, formatMetricValue } from "../lib/scenarioCompare";
import { readChatSettings, writeChatSettings, defaultModelForProvider } from "../lib/copilotAgent";

describe("scenarioCompare", () => {
  it("toMetricRows computes deltas vs the first session", () => {
    const rows = toMetricRows([
      {
        name: "LT Mean Speed",
        unit: "m/s",
        values: { s1: 7.5, s2: 7.8 },
      },
    ]);
    expect(rows[0].deltas.s1).toBe(0);
    expect(rows[0].deltas.s2).toBeCloseTo(0.3, 5);
  });

  it("flattenConfigDiff groups by pair", () => {
    const flat = flattenConfigDiff({
      "a<->b": [{ key: "hub_height_m", a: 120, b: 140 }],
    });
    expect(flat[0].pair).toBe("a<->b");
    expect(flat[0].entries[0].key).toBe("hub_height_m");
  });

  it("formatMetricValue formats by unit", () => {
    expect(formatMetricValue(8.123, "%")).toBe("8.12%");
    expect(formatMetricValue(7.5, "m/s")).toBe("7.50 m/s");
    expect(formatMetricValue(null, "m/s")).toBe("—");
    expect(formatMetricValue(1.23456, "")).toBe("1.235");
  });
});

describe("copilotAgent settings", () => {
  it("defaultModelForProvider returns known defaults", () => {
    expect(defaultModelForProvider("openai")).toBe("gpt-4o");
    expect(defaultModelForProvider("anthropic")).toContain("claude");
    expect(defaultModelForProvider("groq")).toContain("llama");
  });

  it("readChatSettings falls back to defaults when localStorage empty", () => {
    window.localStorage.clear();
    const s = readChatSettings();
    expect(s.provider).toBe("openai");
    expect(s.model).toBe("gpt-4o");
    expect(s.apiKey).toBe("");
  });

  it("writeChatSettings round-trips through readChatSettings", () => {
    writeChatSettings({ provider: "anthropic", model: "claude-x", apiKey: "sk-test" });
    const s = readChatSettings();
    expect(s).toEqual({ provider: "anthropic", model: "claude-x", apiKey: "sk-test" });
    window.localStorage.clear();
  });
});
