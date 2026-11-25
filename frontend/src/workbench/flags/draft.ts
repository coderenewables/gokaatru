import { create } from "zustand";

/** A rule a view proposes and the inspector previews and applies: the rose's selected
 * sectors as a tower-shadow rule on the cup beside its vane (plan §3.3 "Wind rose"). */
export interface RuleDraft {
  rule_type: "tower_shadow";
  sensor: string;
  params: { exclude_sectors: [number, number] };
  /** What the inspector says the rule does. */
  label: string;
}

interface DraftStore {
  draft: RuleDraft | null;
  propose: (draft: RuleDraft) => void;
  clear: () => void;
}

export const useRuleDraft = create<DraftStore>((set) => ({
  draft: null,
  propose: (draft) => set({ draft }),
  clear: () => set({ draft: null }),
}));
