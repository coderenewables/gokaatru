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
  selectedLtcSource: string;
  activeDateRange: DateRange;
  formDrafts: Record<string, JsonValue>;
  unsavedConfig: Record<string, JsonValue>;
  latestUncertainty: UncertaintyResponse | null;
  setSessionId: (sessionId: string | null) => void;
  setSelectedSensors: (selectedSensors: string[]) => void;
  setSelectedLtcAlgorithm: (algorithm: string) => void;
  setSelectedLtcSource: (source: string) => void;
  setActiveDateRange: (range: DateRange) => void;
  setFormDraft: (section: string, value: JsonValue) => void;
  patchFormDraft: (section: string, patch: Record<string, JsonValue>) => void;
  setUnsavedConfig: (config: Record<string, JsonValue>) => void;
  patchUnsavedConfig: (patch: Record<string, JsonValue>) => void;
  setLatestUncertainty: (result: UncertaintyResponse | null) => void;
  resetWorkspace: () => void;
};

function mergeDraftSection(current: JsonValue | undefined, patch: Record<string, JsonValue>) {
  const base = typeof current === "object" && current !== null && !Array.isArray(current) ? current : {};
  return { ...base, ...patch };
}

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
      selectedLtcSource: "ensemble",
      activeDateRange: initialDateRange,
      formDrafts: {},
      unsavedConfig: {},
      latestUncertainty: null,
      setSessionId: (sessionId) => set({ sessionId }),
      setSelectedSensors: (selectedSensors) => set({ selectedSensors }),
      setSelectedLtcAlgorithm: (selectedLtcAlgorithm) => set({ selectedLtcAlgorithm }),
      setSelectedLtcSource: (selectedLtcSource) => set({ selectedLtcSource }),
      setActiveDateRange: (activeDateRange) => set({ activeDateRange }),
      setFormDraft: (section, value) =>
        set((state) => ({
          formDrafts: {
            ...state.formDrafts,
            [section]: value,
          },
        })),
      patchFormDraft: (section, patch) =>
        set((state) => ({
          formDrafts: {
            ...state.formDrafts,
            [section]: mergeDraftSection(state.formDrafts[section], patch),
          },
        })),
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
          selectedLtcSource: "ensemble",
          activeDateRange: initialDateRange,
          formDrafts: {},
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
        selectedLtcSource: state.selectedLtcSource,
        activeDateRange: state.activeDateRange,
        formDrafts: state.formDrafts,
        unsavedConfig: state.unsavedConfig,
        latestUncertainty: state.latestUncertainty,
      }),
    },
  ),
);