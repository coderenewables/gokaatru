import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import openapi from "../api/openapi.json";
import { OperationForm } from "../workbench/forms/OperationForm";
import { type Field, type JsonSchema, bodyOf, fieldsOf, fromInput, inputsOf, labelOf } from "../workbench/forms/schema";

const schemas = (openapi as { components: { schemas: Record<string, JsonSchema> } }).components.schemas;
/** The body model of every generated operation route (server/operations.py parameters_model). */
const PARAMETERS = Object.entries(schemas).filter(([name]) => name.endsWith("Parameters"));

const EXTRAPOLATE: JsonSchema = {
  type: "object",
  required: ["hub_height_m"],
  properties: {
    hub_height_m: { type: "number" },
    shear_model: { type: "string", default: "power_law" },
    reference_columns: { anyOf: [{ type: "array", items: { type: "string" } }, { type: "null" }], default: null },
    extrapolate_reanalysis: { type: "boolean", default: true },
  },
};

function sample(field: Field, property: JsonSchema): string | boolean {
  switch (field.kind) {
    case "boolean":
      return true;
    case "number":
      return "1.5";
    case "integer":
      return "3";
    case "numbers":
      return "80, 100";
    case "texts":
      return "Spd_80m, Spd_100m";
    case "json":
      return property.type === "array" ? "[]" : "{}";
    default:
      return field.choices?.[0] ?? "x";
  }
}

function matches(schema: JsonSchema, value: unknown): boolean {
  const options = schema.anyOf ?? [schema];
  return options.some((option) => {
    switch (option.type) {
      case "null":
        return value === null;
      case "string":
        return typeof value === "string";
      case "number":
        return typeof value === "number";
      case "integer":
        return Number.isInteger(value);
      case "boolean":
        return typeof value === "boolean";
      case "array":
        return Array.isArray(value) && value.every((item) => (option.items ? matches(option.items, item) : true));
      default:
        return true;
    }
  });
}

describe("labels", () => {
  it("names the unit of a parameter", () => {
    expect(labelOf("hub_height_m")).toBe("hub height (m)");
    expect(labelOf("min_speed_mps")).toBe("min speed (m/s)");
    expect(labelOf("measurement_uncertainty_pct")).toBe("measurement uncertainty (%)");
    expect(labelOf("algorithm")).toBe("algorithm");
  });
});

describe("a form from a schema", () => {
  const fields = fieldsOf(EXTRAPOLATE);

  it("gives each parameter the control its shape takes", () => {
    expect(fields.map((field) => [field.name, field.kind, field.required, field.nullable])).toEqual([
      ["hub_height_m", "number", true, false],
      ["shear_model", "text", false, false],
      ["reference_columns", "texts", false, true],
      ["extrapolate_reanalysis", "boolean", false, false],
    ]);
    expect(fields.find((field) => field.name === "reference_columns")?.suggest).toBe("channels");
  });

  it("refuses a missing needed value and a word where a number goes", () => {
    expect(bodyOf(fields, {}).errors).toEqual({ hub_height_m: "hub height (m) is needed" });
    expect(fromInput(fields[0], "high")).toEqual({ ok: false, error: "hub height (m) must be a number" });
  });

  it("leaves untouched defaults to the operation and sends what was filled", () => {
    const { body, errors } = bodyOf(fields, { hub_height_m: "120", reference_columns: "Spd_80m, Spd_100m" });
    expect(errors).toEqual({});
    expect(body).toEqual({
      hub_height_m: 120,
      shear_model: "power_law",
      reference_columns: ["Spd_80m", "Spd_100m"],
      extrapolate_reanalysis: true,
    });
  });

  it("reopens on a step's own parameters", () => {
    const inputs = inputsOf(fields, { hub_height_m: 90, reference_columns: ["Spd_60m"], extrapolate_reanalysis: false });
    expect(inputs).toEqual({ hub_height_m: "90", shear_model: "power_law", reference_columns: "Spd_60m", extrapolate_reanalysis: false });
    expect(bodyOf(fields, inputs).body).toMatchObject({ hub_height_m: 90, reference_columns: ["Spd_60m"], extrapolate_reanalysis: false });
  });
});

describe("every operation's parameters", () => {
  it("are all in the OpenAPI document", () => {
    expect(PARAMETERS.length).toBeGreaterThan(100);
  });

  it.each(PARAMETERS)("%s gets a control for each parameter, and a filled form is a valid body", (_, schema) => {
    const fields = fieldsOf(schema);
    expect(fields.map((field) => field.name).sort()).toEqual(Object.keys(schema.properties ?? {}).sort());
    const filled = Object.fromEntries(fields.map((field) => [field.name, sample(field, (schema.properties ?? {})[field.name])]));
    const { body, errors } = bodyOf(fields, filled);
    expect(errors).toEqual({});
    for (const name of schema.required ?? []) expect(body).toHaveProperty(name);
    for (const [name, value] of Object.entries(body)) {
      expect(matches((schema.properties ?? {})[name], value), `${name} = ${JSON.stringify(value)}`).toBe(true);
    }
  });
});

describe("the form", () => {
  it("renders a control for each parameter and reports changes by name", () => {
    const fields = fieldsOf(EXTRAPOLATE);
    const onChange = vi.fn();
    render(<OperationForm fields={fields} inputs={inputsOf(fields, {})} onChange={onChange} channels={["Spd_80m"]} errors={{ hub_height_m: "hub height (m) is needed" }} />);
    const hub = screen.getByLabelText(/hub height \(m\)/);
    expect(hub).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("hub height (m) is needed")).toBeInTheDocument();
    fireEvent.change(hub, { target: { value: "120" } });
    expect(onChange).toHaveBeenCalledWith("hub_height_m", "120");
    fireEvent.click(screen.getByLabelText("extrapolate reanalysis"));
    expect(onChange).toHaveBeenCalledWith("extrapolate_reanalysis", false);
  });
});
