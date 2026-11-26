import type { Schemas } from "../../api/client";
import type { Definition } from "../selection/store";

export type Instrument = Schemas["Instrument"];

/** An instrument's columns: its own, then the statistics it logs (decisions/0014.2). */
export function instrumentColumns(instrument: Instrument | undefined): string[] {
  return instrument ? [instrument.name, ...instrument.statistics] : [];
}

/** The instrument a flag covers until the analyst picks another: the highest cup in the
 * data, which is the timeline's first channel and the scatter's y axis by default. */
export function defaultInstrument(instruments: Instrument[]): Instrument | undefined {
  const present = instruments.filter((instrument) => instrument.in_data);
  return present.find((instrument) => instrument.sensor_type === "wind_speed") ?? present[0];
}

/** Why the flag cannot be applied yet, or null when it can. */
export function flagProblem(columns: string[], reason: string, note: string): string | null {
  if (columns.length === 0) return "Tick at least one column to flag.";
  if (!reason) return "Choose a reason.";
  if (reason === "other" && !note.trim()) return "A flag whose reason is 'other' needs a note saying why.";
  return null;
}

/** The apply_cleaning_rule body of an exclude_selection flag: the selection's definition
 * frozen into the rule (decisions/0014.1), the first ticked column as the drawn one. */
export function selectionFlagBody(definition: Definition, columns: string[], reason: string, note: string) {
  return {
    rule_type: "exclude_selection",
    sensor: columns[0],
    params: JSON.stringify({ definition, sensors: columns.slice(1), reason, note: note.trim() }),
    start_date: "",
    end_date: "",
  };
}

/** The reason codes as an analyst reads them. */
export function reasonLabel(reason: string): string {
  const text = reason.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}
