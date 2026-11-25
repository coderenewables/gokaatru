import { bodyOf, inputsOf, type Field } from "../forms/schema";

/** A rule as list_cleaning_rules gives it: a name and the parameters it takes, with defaults. */
export interface RuleInfo {
  name: string;
  description: string;
  default_params: Record<string, unknown>;
}

/** The rule a flag drawn on a chart makes: its definition is frozen from a selection, so
 * the inspector writes it, not a form. */
const DRAWN_RULE = "exclude_selection";

/** Rules that take their period from the dates: the period is the rule. */
const PERIOD_RULE = "custom_period_exclude";

/** The rules a form can write, in the order the server lists them. */
export function formRules(rules: RuleInfo[]): RuleInfo[] {
  return rules.filter((rule) => rule.name !== DRAWN_RULE);
}

export function takesDates(rule: string): boolean {
  return rule !== DRAWN_RULE;
}

export function needsDates(rule: string): boolean {
  return rule === PERIOD_RULE;
}

function fieldFor(name: string, value: unknown): Field {
  let kind: Field["kind"] = "json";
  if (typeof value === "number") kind = name.endsWith("_count") ? "integer" : "number";
  else if (typeof value === "string") kind = "text";
  else if (typeof value === "boolean") kind = "boolean";
  else if (Array.isArray(value)) kind = value.every((item) => typeof item === "number") && value.length > 0 ? "numbers" : "texts";
  return {
    name,
    label: name.replace(/_/g, " "),
    kind,
    // A text default is an example (an expression), never a value to send unasked.
    required: typeof value === "string",
    nullable: false,
    defaultValue: typeof value === "string" ? undefined : value,
    choices: null,
    suggest: name === "sensors" ? "channels" : null,
  };
}

/** One field per default parameter. The period rule's start and end are the dates, not fields. */
export function ruleFields(rule: RuleInfo): Field[] {
  if (rule.name === PERIOD_RULE) return [];
  return Object.entries(rule.default_params).map(([name, value]) => fieldFor(name, value));
}

export function ruleInputs(fields: Field[]): Record<string, string | boolean> {
  return inputsOf(fields, {});
}

export interface RuleRequest {
  rule_type: string;
  sensor: string;
  params: string;
  start_date: string;
  end_date: string;
}

/** The request a filled form makes (the body of the preview and of the apply), or what is
 * missing; the same body drives both, so what is previewed is what is applied. */
export function ruleRequest(
  rule: RuleInfo,
  sensor: string,
  fields: Field[],
  inputs: Record<string, string | boolean>,
  dates: { start: string; end: string },
): { request: RuleRequest | null; errors: Record<string, string> } {
  const { body, errors } = bodyOf(fields, inputs);
  if (!sensor) errors.sensor = "Choose the sensor the rule cleans";
  if (needsDates(rule.name)) {
    if (!dates.start) errors.start = "The period needs a start";
    if (!dates.end) errors.end = "The period needs an end";
  }
  if (Object.keys(errors).length > 0) return { request: null, errors };
  const withDates = takesDates(rule.name);
  return {
    request: {
      rule_type: rule.name,
      sensor,
      params: JSON.stringify(body),
      start_date: withDates ? dates.start : "",
      end_date: withDates ? dates.end : "",
    },
    errors,
  };
}

/** A number for display only, the server's value untouched; absent as a dash. */
export function shown(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return Number.isInteger(value) ? String(value) : value.toFixed(digits);
}
