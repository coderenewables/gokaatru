import { create } from "zustand";

import { type PhaseId, phaseFromAddress } from "./layout";

interface PhaseStore {
  phase: PhaseId;
  /** Open another phase and name it in the address, as the phase bar does; a panel calls it
   * to carry its work on (a scenario loaded into Model, a pipeline swept in Run). */
  goTo: (phase: PhaseId) => void;
}

export const usePhase = create<PhaseStore>((set) => ({
  phase: phaseFromAddress(window.location.search),
  goTo: (phase) => {
    const params = new URLSearchParams(window.location.search);
    if (phase === "prepare") params.delete("phase");
    else params.set("phase", phase);
    window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
    set({ phase });
  },
}));
