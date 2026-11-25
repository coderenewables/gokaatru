/** The workbench's keyboard commands (plan §3.3 "Anywhere"). A key typed into a field is the
 * field's: undo inside a text box undoes the typing, not the analysis. */
export type KeyCommand = "undo" | "redo" | "palette";

export function keyCommand(event: Pick<KeyboardEvent, "key" | "ctrlKey" | "metaKey" | "shiftKey" | "target">): KeyCommand | null {
  if (!(event.ctrlKey || event.metaKey)) return null;
  const key = event.key.toLowerCase();
  if (key === "k") return "palette";
  const target = event.target as HTMLElement | null;
  const typing =
    target !== null &&
    (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName ?? ""));
  if (typing) return null;
  if (key === "z") return event.shiftKey ? "redo" : "undo";
  if (key === "y") return "redo";
  return null;
}
