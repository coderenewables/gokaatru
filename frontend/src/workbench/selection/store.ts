import { create } from "zustand";

// The shared selection, as a crossfilter (decisions/0014.5): each view holds one term, and
// the selection every view and statistic uses is their intersection. The terms are the
// bounds the analyst drew, in the server's selection shape (server/core/selection.py); the
// server resolves them to records (decisions/0011), so no chart library's count is used.

export interface TimeRange {
  kind: "time_range";
  start?: string;
  end?: string;
}
export interface Sector {
  kind: "sector";
  channel: string;
  from_deg: number;
  to_deg: number;
}
export interface Band {
  kind: "band";
  channel: string;
  min?: number;
  max?: number;
}
export interface Polygon {
  kind: "polygon";
  x_channel: string;
  y_channel: string;
  vertices: [number, number][];
}
export interface Combined {
  kind: "union" | "intersection";
  of: Definition[];
}
export type Definition = TimeRange | Sector | Band | Polygon | Combined;

/** The views that contribute a term, in the order their terms are combined and listed. */
export const VIEWS = ["timeline", "scatter", "rose"] as const;
export type ViewId = (typeof VIEWS)[number];

export const VIEW_LABELS: Record<ViewId, string> = { timeline: "Period", scatter: "Scatter", rose: "Direction" };

/** Two terms of one view joined: Shift adds to a view's own term rather than replacing it. */
export function unionOf(first: Definition, second: Definition): Definition {
  const parts = (definition: Definition) => (definition.kind === "union" ? definition.of : [definition]);
  return { kind: "union", of: [...parts(first), ...parts(second)] };
}

/** The selection the views share: the intersection of every term, or null when none is drawn. */
export function crossfilter(terms: Partial<Record<ViewId, Definition>>): Definition | null {
  const present = VIEWS.map((view) => terms[view]).filter((term): term is Definition => term !== undefined);
  if (present.length === 0) return null;
  return present.length === 1 ? present[0] : { kind: "intersection", of: present };
}

/** The selection as the ``selection`` argument a selectable operation takes inline. */
export function inlineSelection(definition: Definition | null): string {
  return definition === null ? "" : JSON.stringify(definition);
}

interface SelectionStore {
  terms: Partial<Record<ViewId, Definition>>;
  /** Replace a view's term, or with ``extend`` add to it. */
  draw: (view: ViewId, term: Definition, extend?: boolean) => void;
  clear: (view: ViewId) => void;
  clearAll: () => void;
}

export const useSelection = create<SelectionStore>((set) => ({
  terms: {},
  draw: (view, term, extend = false) =>
    set((state) => {
      const current = state.terms[view];
      return { terms: { ...state.terms, [view]: extend && current ? unionOf(current, term) : term } };
    }),
  clear: (view) =>
    set((state) => {
      const terms = { ...state.terms };
      delete terms[view];
      return { terms };
    }),
  clearAll: () => set({ terms: {} }),
}));

/** The shared selection, inline, for queries; "" with nothing drawn. */
export function useSharedSelection(): string {
  return useSelection((state) => inlineSelection(crossfilter(state.terms)));
}
