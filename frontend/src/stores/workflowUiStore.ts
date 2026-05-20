import { create } from "zustand";

import { workflowTemplates } from "../lib/workflowTemplates";

type WorkflowUiState = {
  comparisonOpen: boolean;
  selectedCompareBranchIds: string[];
  selectedTemplateId: string;
  snapshotName: string;
  selectedSnapshotName: string;
  activeBranchId: string;
  selectedNodeId: string | null;
  setComparisonOpen: (open: boolean) => void;
  setSelectedCompareBranchIds: (branchIds: string[]) => void;
  syncSelectedCompareBranchIds: (availableIds: string[]) => void;
  setSelectedTemplateId: (templateId: string) => void;
  setSnapshotName: (name: string) => void;
  setSelectedSnapshotName: (name: string) => void;
  setActiveBranchId: (branchId: string) => void;
  setSelectedNodeId: (nodeId: string | null) => void;
  syncAvailableBranches: (branchIds: string[]) => void;
  resetWorkflowUi: () => void;
};

export const useWorkflowUiStore = create<WorkflowUiState>((set) => ({
  comparisonOpen: false,
  selectedCompareBranchIds: [],
  selectedTemplateId: workflowTemplates[0]?.id ?? "",
  snapshotName: "",
  selectedSnapshotName: "",
  activeBranchId: "main",
  selectedNodeId: null,
  setComparisonOpen: (comparisonOpen) => set({ comparisonOpen }),
  setSelectedCompareBranchIds: (selectedCompareBranchIds) => set({ selectedCompareBranchIds }),
  syncSelectedCompareBranchIds: (availableIds) =>
    set((state) => {
      const filtered = state.selectedCompareBranchIds.filter((branchId) => availableIds.includes(branchId));
      return {
        selectedCompareBranchIds: filtered.length > 0 ? filtered : availableIds,
      };
    }),
  setSelectedTemplateId: (selectedTemplateId) => set({ selectedTemplateId }),
  setSnapshotName: (snapshotName) => set({ snapshotName }),
  setSelectedSnapshotName: (selectedSnapshotName) => set({ selectedSnapshotName }),
  setActiveBranchId: (activeBranchId) => set({ activeBranchId, selectedNodeId: null }),
  setSelectedNodeId: (selectedNodeId) => set({ selectedNodeId }),
  syncAvailableBranches: (branchIds) =>
    set((state) => {
      const nextActiveBranchId = branchIds.includes(state.activeBranchId) ? state.activeBranchId : (branchIds[0] ?? "main");
      if (nextActiveBranchId === state.activeBranchId) {
        return {};
      }
      return {
        activeBranchId: nextActiveBranchId,
        selectedNodeId: null,
      };
    }),
  resetWorkflowUi: () =>
    set({
      comparisonOpen: false,
      selectedCompareBranchIds: [],
      selectedTemplateId: workflowTemplates[0]?.id ?? "",
      snapshotName: "",
      selectedSnapshotName: "",
      activeBranchId: "main",
      selectedNodeId: null,
    }),
}));