import { create } from "zustand";
import { persist } from "zustand/middleware";

import type { JsonValue } from "../lib/types";

type DateRange = {
  startDate: string;
  endDate: string;
};

type WorkspaceState = {
  sessionId: string | null;
  selectedSensors: string[];
  selectedLtcAlgorithm: string;
  activeDateRange: DateRange;
  unsavedConfig: Record<string, JsonValue>;
  setSessionId: (sessionId: string | null) => void;
  setSelectedSensors: (selectedSensors: string[]) => void;
  setSelectedLtcAlgorithm: (algorithm: string) => void;
  setActiveDateRange: (range: DateRange) => void;
  setUnsavedConfig: (config: Record<string, JsonValue>) => void;
  patchUnsavedConfig: (patch: Record<string, JsonValue>) => void;
  resetWorkspace: () => void;
};

const initialDateRange: DateRange = {
  startDate: "2000-01-01",
  endDate: "2025-12-31",
};

export const useWorkspaceStore = create<WorkspaceState>()(
  persist(
    (set) => ({
      sessionId: null,
      selectedSensors: [],
      selectedLtcAlgorithm: "linear_least_squares",
      activeDateRange: initialDateRange,
      unsavedConfig: {},
      setSessionId: (sessionId) => set({ sessionId }),
      setSelectedSensors: (selectedSensors) => set({ selectedSensors }),
      setSelectedLtcAlgorithm: (selectedLtcAlgorithm) => set({ selectedLtcAlgorithm }),
      setActiveDateRange: (activeDateRange) => set({ activeDateRange }),
      setUnsavedConfig: (unsavedConfig) => set({ unsavedConfig }),
      patchUnsavedConfig: (patch) =>
        set((state) => ({
          unsavedConfig: { ...state.unsavedConfig, ...patch },
        })),
      resetWorkspace: () =>
        set({
          sessionId: null,
          selectedSensors: [],
          selectedLtcAlgorithm: "linear_least_squares",
          activeDateRange: initialDateRange,
          unsavedConfig: {},
        }),
    }),
    {
      name: "gokaatru-workspace",
      partialize: (state) => ({
        sessionId: state.sessionId,
        selectedSensors: state.selectedSensors,
        selectedLtcAlgorithm: state.selectedLtcAlgorithm,
        activeDateRange: state.activeDateRange,
        unsavedConfig: state.unsavedConfig,
      }),
    },
  ),
);