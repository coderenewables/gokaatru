import type { Definition } from "./store";

const number = (value: number) => (Number.isInteger(value) ? String(value) : value.toFixed(2).replace(/0+$/, ""));

function instant(value: string): string {
  const stamp = new Date(value);
  if (Number.isNaN(stamp.getTime())) return value;
  return stamp.toISOString().slice(0, 16).replace("T", " ") + " UTC";
}

/** A term in words, for its chip in the inspector. The server words the frozen definition of
 * an applied flag itself (server/core/selection.py ``describe``), for the log. */
export function describeTerm(definition: Definition): string {
  switch (definition.kind) {
    case "time_range":
      if (definition.start && definition.end) return `${instant(definition.start)} to ${instant(definition.end)}`;
      return definition.start ? `from ${instant(definition.start)}` : `before ${instant(definition.end ?? "")}`;
    case "sector":
      return `${definition.channel} ${number(definition.from_deg)}° to ${number(definition.to_deg)}°`;
    case "band":
      if (definition.min !== undefined && definition.max !== undefined) {
        return `${definition.channel} ${number(definition.min)} to ${number(definition.max)}`;
      }
      return definition.min !== undefined
        ? `${definition.channel} at least ${number(definition.min)}`
        : `${definition.channel} below ${number(definition.max ?? 0)}`;
    case "polygon":
      return `${definition.x_channel} against ${definition.y_channel}, lasso of ${definition.vertices.length} points`;
    case "union":
      return definition.of.map(describeTerm).join(" or ");
    case "intersection":
      return definition.of.map(describeTerm).join(", ");
  }
}
