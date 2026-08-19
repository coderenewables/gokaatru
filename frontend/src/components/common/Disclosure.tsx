// Disclosure panel — surfaces the caveats a backend response carries about its own numbers.
//
// The logic audit added warning, note and basis fields across nearly every tool response:
// which bin the IEC turbulence figure actually came from, whether the extreme-wind GEV was
// fitted at all, that cleaning rule order changed the answer, that the ensemble blend mixes
// two error definitions, what the uncertainty model's independence assumption costs. None of
// it reached a screen — the whole audit was legible only to whoever read the raw response.
//
// This renders those fields **by naming convention** rather than by enumerating them, so a
// disclosure field added to any tool tomorrow appears here without frontend work. That is
// deliberate: the alternative is a per-field UI that silently omits whatever nobody
// remembered to wire up, which is the failure mode the audit was about in the first place.
import { useState } from "react";

/** How deep to look for nested disclosure. Most live one level down (`combination.note`). */
const MAX_DEPTH = 2;

/** Keys that are disclosure but do not match the naming convention. */
const EXTRA_NOTE_KEYS = new Set(["reason", "implausibility", "basis_note"]);

/** Boolean flags worth surfacing when true — each marks a result as qualified. */
const FLAG_LABELS: Record<string, string> = {
  method_is_mixed: "Produced by two different physical models",
  weight_basis_is_mixed: "Component weights rest on two different error definitions",
  order_is_material: "Rule order affects this result",
  screening_only: "Screening basis only — not a design value",
  selection_is_exponent_sensitive: "The selected window depends on an undocumented constant",
  below_largest_observed: "Return level sits below the largest observed maximum",
  cap_applied: "A cap was applied and withheld further credit",
  min_window_years_applied: "A minimum-window floor constrained the selection",
};

export interface DisclosureItem {
  kind: "warning" | "note" | "basis" | "flag";
  /** Dotted path, used as the React key and to label where the field came from. */
  path: string;
  label: string;
  text: string;
}

function humanise(key: string): string {
  const trimmed = key.replace(/_(warning|note|basis)$/, "").replace(/_/g, " ");
  if (!trimmed) return key.replace(/_/g, " ");
  return trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
}

function classify(key: string): DisclosureItem["kind"] | null {
  if (key === "warning" || key.endsWith("_warning")) return "warning";
  if (key === "note" || key.endsWith("_note") || EXTRA_NOTE_KEYS.has(key)) return "note";
  if (key === "basis" || key.endsWith("_basis")) return "basis";
  return null;
}

/**
 * Walk a response object and collect every disclosure field it carries.
 *
 * Exported so a view can count items before deciding to render, and so the behaviour is
 * testable without mounting a component.
 */
export function collectDisclosure(
  source: unknown,
  prefix = "",
  depth = 0,
): DisclosureItem[] {
  if (source == null || typeof source !== "object" || Array.isArray(source)) return [];
  const items: DisclosureItem[] = [];

  for (const [key, value] of Object.entries(source as Record<string, unknown>)) {
    const path = prefix ? `${prefix}.${key}` : key;

    if (typeof value === "string" && value.trim()) {
      const kind = classify(key);
      if (kind) {
        items.push({ kind, path, label: humanise(prefix ? prefix.split(".").pop()! : key), text: value });
        continue;
      }
    }

    // A flag is disclosure only when it is true — "not mixed" is not worth a line.
    if (value === true && key in FLAG_LABELS) {
      items.push({ kind: "flag", path, label: humanise(key), text: FLAG_LABELS[key] });
      continue;
    }

    // `available: false` always travels with a `reason`, which the string branch picks up.
    if (depth < MAX_DEPTH && value != null && typeof value === "object" && !Array.isArray(value)) {
      items.push(...collectDisclosure(value, path, depth + 1));
    }
  }

  // Warnings first, then flags, then notes and basis labels: severity order, and stable
  // within each group so the panel does not reshuffle between renders.
  const order: Record<DisclosureItem["kind"], number> = { warning: 0, flag: 1, note: 2, basis: 3 };
  return items.sort((a, b) => order[a.kind] - order[b.kind] || a.path.localeCompare(b.path));
}

interface DisclosureProps {
  /** Any tool or API response. Non-objects and nulls render nothing. */
  source: unknown;
  title?: string;
  /** Notes and basis labels start collapsed; warnings are always shown. */
  collapsedByDefault?: boolean;
}

export function Disclosure({
  source,
  title = "What this result assumes",
  collapsedByDefault = true,
}: DisclosureProps) {
  const [expanded, setExpanded] = useState(!collapsedByDefault);
  const items = collectDisclosure(source);
  if (items.length === 0) return null;

  const urgent = items.filter((item) => item.kind === "warning" || item.kind === "flag");
  const secondary = items.filter((item) => item.kind === "note" || item.kind === "basis");

  return (
    <section className="disclosure" aria-label={title}>
      <h4 className="disclosure-title">
        {title}
        {urgent.length > 0 ? (
          <span className="disclosure-count" aria-label={`${urgent.length} to check`}>
            {urgent.length}
          </span>
        ) : null}
      </h4>

      {urgent.map((item) => (
        <p key={item.path} className={`disclosure-item disclosure-${item.kind}`}>
          <strong>{item.label}</strong> {item.text}
        </p>
      ))}

      {secondary.length > 0 ? (
        <>
          <button
            type="button"
            className="disclosure-toggle"
            aria-expanded={expanded}
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded ? "Hide" : "Show"} {secondary.length} methodology note
            {secondary.length === 1 ? "" : "s"}
          </button>
          {expanded
            ? secondary.map((item) => (
                <p key={item.path} className={`disclosure-item disclosure-${item.kind}`}>
                  <strong>{item.label}</strong> {item.text}
                </p>
              ))
            : null}
        </>
      ) : null}
    </section>
  );
}
