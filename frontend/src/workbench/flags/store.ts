import { create } from "zustand";

import type { Schemas } from "../../api/client";

/** One run of flagged records as get_flag_intervals returns it (server/tools/flags.py). */
export type FlagInterval = Schemas["FlagInterval"];

export interface FocusedFlag {
  sensor: string;
  interval: FlagInterval;
}

interface FlagFocusStore {
  /** The flag band the analyst clicked; the inspector shows who, when and why (P2-18). */
  focused: FocusedFlag | null;
  focus: (flag: FocusedFlag) => void;
  clear: () => void;
}

export const useFlagFocus = create<FlagFocusStore>((set) => ({
  focused: null,
  focus: (flag) => set({ focused: flag }),
  clear: () => set({ focused: null }),
}));
