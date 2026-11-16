import { describe, expect, it } from "vitest";

import { toMetricRows, flattenConfigDiff, formatMetricValue } from "../lib/scenarioCompare";
import {
  readChatSettings,
  writeChatSettings,
  defaultModelForProvider,
  SUPPORTED_COPILOT_PROVIDERS,
} from "../lib/copilotAgent";

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
    expect(defaultModelForProvider("groq")).toContain("llama");
  });

  it("supported providers equal the backend's _PROVIDER_URLS keys", () => {
    // tests/test_chat_ssrf.py pins the same literal list on the backend.
    expect([...SUPPORTED_COPILOT_PROVIDERS]).toEqual(["openai", "openrouter", "groq", "together"]);
  });

  it("a saved provider the backend does not support falls back to openai", () => {
    window.localStorage.setItem(
      "gokaatru-chat-settings",
      JSON.stringify({ provider: "anthropic", model: "claude-x", apiKey: "sk-test" }),
    );
    const s = readChatSettings();
    expect(s.provider).toBe("openai");
    expect(s.model).toBe(defaultModelForProvider("openai"));
    expect(s.apiKey).toBe("sk-test");
    expect(s.replacedProvider).toBe("anthropic");
    window.localStorage.clear();
  });

  it("a supported saved provider is kept and not flagged as replaced", () => {
    writeChatSettings({ provider: "groq", model: "m", apiKey: "k" });
    const s = readChatSettings();
    expect(s.provider).toBe("groq");
    expect(s.model).toBe("m");
    expect(s.replacedProvider).toBeUndefined();
    window.localStorage.clear();
  });

  it("assistant data changes are off unless the saved value is exactly true", () => {
    for (const value of ["yes", 1, null, undefined]) {
      window.localStorage.setItem(
        "gokaatru-chat-settings",
        JSON.stringify({ provider: "openai", model: "gpt-4o", apiKey: "k", allowMutatingTools: value }),
      );
      expect(readChatSettings().allowMutatingTools).toBe(false);
    }
    writeChatSettings({ provider: "openai", model: "gpt-4o", apiKey: "k", allowMutatingTools: true });
    expect(readChatSettings().allowMutatingTools).toBe(true);
    window.localStorage.clear();
  });

  it("readChatSettings falls back to defaults when localStorage empty", () => {
    window.localStorage.clear();
    const s = readChatSettings();
    expect(s.provider).toBe("openai");
    expect(s.model).toBe("gpt-4o");
    expect(s.apiKey).toBe("");
  });

  it("writeChatSettings round-trips through readChatSettings", () => {
    writeChatSettings({ provider: "openrouter", model: "x/y", apiKey: "sk-test" });
    const s = readChatSettings();
    // allowMutatingTools is off for settings written without it (owner decision 2026-11-17).
    expect(s).toEqual({
      provider: "openrouter",
      model: "x/y",
      apiKey: "sk-test",
      allowMutatingTools: false,
    });
    window.localStorage.clear();
  });

  it("readChatSettings honours an explicit read-only assistant", () => {
    writeChatSettings({
      provider: "openai",
      model: "gpt-4o",
      apiKey: "sk-test",
      allowMutatingTools: false,
    });
    expect(readChatSettings().allowMutatingTools).toBe(false);
    window.localStorage.clear();
  });
});
