import { create } from "zustand";
import { persist } from "zustand/middleware";

import type { JsonValue, UncertaintyResponse } from "../lib/types";

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
  latestUncertainty: UncertaintyResponse | null;
  setSessionId: (sessionId: string | null) => void;
  setSelectedSensors: (selectedSensors: string[]) => void;
  setSelectedLtcAlgorithm: (algorithm: string) => void;
  setActiveDateRange: (range: DateRange) => void;
  setUnsavedConfig: (config: Record<string, JsonValue>) => void;
  patchUnsavedConfig: (patch: Record<string, JsonValue>) => void;
  setLatestUncertainty: (result: UncertaintyResponse | null) => void;
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
      latestUncertainty: null,
      setSessionId: (sessionId) => set({ sessionId }),
      setSelectedSensors: (selectedSensors) => set({ selectedSensors }),
      setSelectedLtcAlgorithm: (selectedLtcAlgorithm) => set({ selectedLtcAlgorithm }),
      setActiveDateRange: (activeDateRange) => set({ activeDateRange }),
      setUnsavedConfig: (unsavedConfig) => set({ unsavedConfig }),
      patchUnsavedConfig: (patch) =>
        set((state) => ({
          unsavedConfig: { ...state.unsavedConfig, ...patch },
        })),
      setLatestUncertainty: (latestUncertainty) => set({ latestUncertainty }),
      resetWorkspace: () =>
        set({
          sessionId: null,
          selectedSensors: [],
          selectedLtcAlgorithm: "linear_least_squares",
          activeDateRange: initialDateRange,
          unsavedConfig: {},
          latestUncertainty: null,
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
        latestUncertainty: state.latestUncertainty,
      }),
    },
  ),
);