import { describe, expect, it } from "vitest";

import { formRules, needsDates, ruleFields, ruleInputs, ruleRequest, shown, takesDates, type RuleInfo } from "../workbench/prepare/rules";

const rule = (name: string, default_params: Record<string, unknown>): RuleInfo => ({ name, description: name, default_params });

const STUCK = rule("stuck_sensor", { consecutive_count: 6, calm_threshold_mps: 0.1 });
const EXPRESSION = rule("expression_filter", { expression: "Spd_100m < 0 or Spd_100m > 50" });
const PERIOD = rule("custom_period_exclude", { start: "YYYY-MM-DD", end: "YYYY-MM-DD" });

describe("the cleaning rules as forms", () => {
  it("leaves out the rule a flag drawn on a chart makes", () => {
    const list = [rule("range_check", {}), rule("exclude_selection", { definition: {} }), STUCK];
    expect(formRules(list).map((item) => item.name)).toEqual(["range_check", "stuck_sensor"]);
  });

  it("makes a field per default parameter, a whole number for a count", () => {
    const fields = ruleFields(STUCK);
    expect(fields.map((field) => [field.name, field.kind])).toEqual([
      ["consecutive_count", "integer"],
      ["calm_threshold_mps", "number"],
    ]);
    expect(ruleInputs(fields)).toEqual({ consecutive_count: "6", calm_threshold_mps: "0.1" });
  });

  it("needs a text parameter, whose default is an example rather than a value", () => {
    const [field] = ruleFields(EXPRESSION);
    expect(field.required).toBe(true);
    expect(ruleInputs([field])).toEqual({ expression: "" });
  });

  it("gives the period rule dates, not start and end fields", () => {
    expect(ruleFields(PERIOD)).toEqual([]);
    expect(needsDates("custom_period_exclude")).toBe(true);
    expect(needsDates("stuck_sensor")).toBe(false);
    expect(takesDates("exclude_selection")).toBe(false);
  });
});

describe("the request a rule's form makes", () => {
  const fields = ruleFields(STUCK);

  it("sends the parameters as the JSON text the operation takes, with the dates as typed", () => {
    const { request } = ruleRequest(STUCK, "Spd_100m", fields, { consecutive_count: "8", calm_threshold_mps: "0.1" }, { start: "2023-03-02", end: "" });
    expect(request).toEqual({
      rule_type: "stuck_sensor",
      sensor: "Spd_100m",
      params: JSON.stringify({ consecutive_count: 8, calm_threshold_mps: 0.1 }),
      start_date: "2023-03-02",
      end_date: "",
    });
  });

  it("refuses to be sent without a sensor, with a half-typed number, or a period without its ends", () => {
    expect(ruleRequest(STUCK, "", fields, ruleInputs(fields), { start: "", end: "" }).errors.sensor).toBeDefined();
    const half = ruleRequest(STUCK, "Spd_100m", fields, { consecutive_count: "six", calm_threshold_mps: "0.1" }, { start: "", end: "" });
    expect(half.request).toBeNull();
    expect(half.errors.consecutive_count).toMatch(/number/);
    const period = ruleRequest(PERIOD, "Spd_100m", [], {}, { start: "2023-03-02", end: "" });
    expect(period.request).toBeNull();
    expect(period.errors.end).toBeDefined();
    expect(ruleRequest(PERIOD, "Spd_100m", [], {}, { start: "2023-03-02", end: "2023-03-03" }).request?.params).toBe("{}");
  });

  it("leaves a rule with no parameters an empty object", () => {
    expect(ruleRequest(rule("range_check", {}), "Spd_100m", [], {}, { start: "", end: "" }).request?.params).toBe("{}");
  });
});

describe("a number shown for reading", () => {
  it("is rounded for display, whole numbers untouched, absence a dash", () => {
    expect(shown(0.123456)).toBe("0.123");
    expect(shown(48)).toBe("48");
    expect(shown(null)).toBe("—");
    expect(shown(Number.NaN)).toBe("—");
  });
});
