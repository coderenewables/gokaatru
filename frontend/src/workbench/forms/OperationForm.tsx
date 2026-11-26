import { useId } from "react";

import type { Field } from "./schema";
import "./forms.css";

export interface OperationFormProps {
  fields: Field[];
  inputs: Record<string, string | boolean>;
  onChange: (name: string, value: string | boolean) => void;
  /** Why a parameter cannot be sent yet, by parameter name: the form's own and the server's. */
  errors?: Record<string, string>;
  channels?: string[];
  sources?: string[];
  disabled?: boolean;
}

/** An operation's parameters as controls, generated from its schema (P3-9). A list is typed
 * comma-separated; channel and source names are offered while typing, never forced. */
export function OperationForm({ fields, inputs, onChange, errors = {}, channels = [], sources = [], disabled }: OperationFormProps) {
  const id = useId();
  const lists = { channels, sources };
  if (fields.length === 0) return <p className="gk-muted">It takes no parameters.</p>;
  return (
    <div className="gk-form">
      {Object.entries(lists).map(([name, values]) =>
        values.length > 0 ? (
          <datalist key={name} id={`${id}-${name}`}>
            {values.map((value) => (
              <option key={value} value={value} />
            ))}
          </datalist>
        ) : null,
      )}
      {fields.map((field) => {
        const value = inputs[field.name];
        const error = errors[field.name];
        const describedBy = error ? `${id}-${field.name}-error` : undefined;
        if (field.kind === "boolean") {
          return (
            <label key={field.name} className="gk-check">
              <input
                type="checkbox"
                checked={Boolean(value)}
                disabled={disabled}
                onChange={(event) => onChange(field.name, event.target.checked)}
              />
              {field.label}
            </label>
          );
        }
        const numeric = field.kind === "number" || field.kind === "integer";
        return (
          <label key={field.name} className="gk-field">
            <span>
              {field.label}
              {field.required ? " (needed)" : ""}
            </span>
            {field.choices ? (
              <select value={String(value ?? "")} disabled={disabled} onChange={(event) => onChange(field.name, event.target.value)}>
                {!field.required && <option value="">(default)</option>}
                {field.choices.map((choice) => (
                  <option key={choice} value={choice}>
                    {choice}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type={numeric ? "number" : "text"}
                step={field.kind === "integer" ? 1 : "any"}
                inputMode={numeric ? "decimal" : undefined}
                value={String(value ?? "")}
                disabled={disabled}
                list={field.suggest && lists[field.suggest].length > 0 ? `${id}-${field.suggest}` : undefined}
                placeholder={field.kind === "numbers" || field.kind === "texts" ? "comma-separated" : field.kind === "json" ? "JSON" : undefined}
                aria-invalid={error ? true : undefined}
                aria-describedby={describedBy}
                onChange={(event) => onChange(field.name, event.target.value)}
              />
            )}
            {error && (
              <span id={describedBy} className="gk-field-error">
                {error}
              </span>
            )}
          </label>
        );
      })}
    </div>
  );
}
