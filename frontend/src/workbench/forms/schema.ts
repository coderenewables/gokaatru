/** Parameter forms generated from an operation's declared schema (decisions/0015.1, P3-9).
 *
 * Every operation publishes the JSON schema of its parameters (GET /operations, the same one
 * the MCP tool and the generated route read). The few shapes it takes map onto controls:
 * text, a number, a whole number, a switch, or a comma-separated list. Nothing here knows any
 * one operation; a new operation gets its form without a line of interface code.
 */

export interface JsonSchema {
  type?: string;
  anyOf?: JsonSchema[];
  items?: JsonSchema;
  enum?: unknown[];
  default?: unknown;
  description?: string;
  title?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
}

export type FieldKind = "text" | "number" | "integer" | "boolean" | "numbers" | "texts" | "json";

export interface Field {
  name: string;
  label: string;
  kind: FieldKind;
  required: boolean;
  /** An empty control sends null rather than leaving the parameter out. */
  nullable: boolean;
  defaultValue: unknown;
  choices: string[] | null;
  /** What to offer while typing: the campaign's channels or the reanalysis sources. */
  suggest: "channels" | "sources" | null;
}

const UNITS: [RegExp, string][] = [
  [/_mps$/, "m/s"],
  [/_m$/, "m"],
  [/_pct$/, "%"],
  [/_deg$/, "°"],
  [/_hours$/, "h"],
  [/_years$/, "years"],
];

/** The parameter's name as a label, its unit suffix in brackets: hub_height_m, "hub height (m)". */
export function labelOf(name: string): string {
  for (const [pattern, unit] of UNITS) {
    if (pattern.test(name)) return `${name.replace(pattern, "").replace(/_/g, " ")} (${unit})`;
  }
  return name.replace(/_/g, " ");
}

function suggestionFor(name: string): Field["suggest"] {
  if (name === "reference_source" || name === "source") return "sources";
  if (/(_col|_cols|_columns|_sensor|_sensors|^sensor_name|^sensor_names|^channels?|^x_channel|^y_channel)$/.test(name)) {
    return name === "height_sensors" ? null : "channels";
  }
  return null;
}

function kindOf(schema: JsonSchema): FieldKind {
  switch (schema.type) {
    case "string":
      return "text";
    case "number":
      return "number";
    case "integer":
      return "integer";
    case "boolean":
      return "boolean";
    case "array":
      return schema.items?.type === "number" || schema.items?.type === "integer" ? "numbers" : schema.items?.type === "string" ? "texts" : "json";
    default:
      return "json";
  }
}

/** One field per parameter, in the order the schema lists them. */
export function fieldsOf(schema: JsonSchema): Field[] {
  const required = new Set(schema.required ?? []);
  return Object.entries(schema.properties ?? {}).map(([name, property]) => {
    const options = property.anyOf ?? [property];
    const concrete = options.filter((option) => option.type !== "null");
    const nullable = concrete.length < options.length;
    const shape = concrete.length === 1 ? concrete[0] : { type: undefined };
    return {
      name,
      label: labelOf(name),
      kind: kindOf(shape),
      required: required.has(name),
      nullable,
      defaultValue: property.default,
      choices: Array.isArray(shape.enum) ? shape.enum.map(String) : null,
      suggest: suggestionFor(name),
    };
  });
}

/** What a control shows for a value: text for everything but a switch. */
export function toInput(field: Field, value: unknown): string | boolean {
  if (field.kind === "boolean") return value === undefined || value === null ? Boolean(field.defaultValue) : Boolean(value);
  if (value === undefined || value === null) return "";
  if (field.kind === "numbers" || field.kind === "texts") return Array.isArray(value) ? value.join(", ") : String(value);
  if (field.kind === "json") return JSON.stringify(value);
  return String(value);
}

export type Parsed = { ok: true; value: unknown; omit: boolean } | { ok: false; error: string };

/** A control's content as the parameter's value. An empty optional control is left out, so
 * the operation's own default applies; an empty nullable one sends null. */
export function fromInput(field: Field, input: string | boolean): Parsed {
  if (field.kind === "boolean") return { ok: true, value: Boolean(input), omit: false };
  const text = String(input).trim();
  if (text === "") {
    if (field.nullable) return { ok: true, value: null, omit: field.defaultValue === null && !field.required };
    if (field.required) return { ok: false, error: `${field.label} is needed` };
    return { ok: true, value: undefined, omit: true };
  }
  switch (field.kind) {
    case "number":
    case "integer": {
      const value = Number(text);
      if (!Number.isFinite(value)) return { ok: false, error: `${field.label} must be a number` };
      if (field.kind === "integer" && !Number.isInteger(value)) return { ok: false, error: `${field.label} must be a whole number` };
      return { ok: true, value, omit: false };
    }
    case "numbers": {
      const parts = text.split(",").map((part) => part.trim()).filter(Boolean);
      const values = parts.map(Number);
      if (values.some((value) => !Number.isFinite(value))) return { ok: false, error: `${field.label} must be numbers separated by commas` };
      return { ok: true, value: values, omit: false };
    }
    case "texts":
      return { ok: true, value: text.split(",").map((part) => part.trim()).filter(Boolean), omit: false };
    case "json":
      try {
        return { ok: true, value: JSON.parse(text), omit: false };
      } catch {
        return { ok: false, error: `${field.label} must be JSON` };
      }
    default:
      return { ok: true, value: text, omit: false };
  }
}

/** The request body a filled form makes, or why it cannot be sent yet. */
export function bodyOf(fields: Field[], inputs: Record<string, string | boolean>): { body: Record<string, unknown>; errors: Record<string, string> } {
  const body: Record<string, unknown> = {};
  const errors: Record<string, string> = {};
  for (const field of fields) {
    const input = inputs[field.name] ?? toInput(field, field.defaultValue);
    const parsed = fromInput(field, input);
    if (!parsed.ok) errors[field.name] = parsed.error;
    else if (!parsed.omit) body[field.name] = parsed.value;
  }
  return { body, errors };
}

/** The controls' content for given parameters, as a form opens on a step it already has. */
export function inputsOf(fields: Field[], parameters: Record<string, unknown>): Record<string, string | boolean> {
  return Object.fromEntries(fields.map((field) => [field.name, toInput(field, field.name in parameters ? parameters[field.name] : field.defaultValue)]));
}
