import { useEffect, useMemo, useRef, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Outlet } from "react-router-dom";

import { useWorkflowExecution } from "../../hooks/useWorkflowExecution";
import { ApiError, healthApi, sessionsApi, workflowApi } from "../../lib/api";
import { workflowTemplates } from "../../lib/workflowTemplates";
import { useWorkflowStore } from "../../stores/workflowStore";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import { Canvas } from "./Canvas";
import { DatasetPool } from "./DatasetPool";
import { NodeInspector } from "./NodeInspector";
import { NodePalette } from "./NodePalette";
import { TopBar } from "./TopBar";
import { ComparisonDashboard } from "../comparison/ComparisonDashboard";
import type { WorkflowSnapshot } from "../../stores/workflowStore";
import type { JsonValue } from "../../lib/types";

const WORKFLOW_AUTOSAVE_KEY = "gokaatru.workflow.autosave.v1";

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  const tagName = target.tagName.toLowerCase();
  return target.isContentEditable || tagName === "input" || tagName === "textarea" || tagName === "select";
}

function toErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Comparison request failed";
}

export function WorkflowDesigner() {
  const [comparisonOpen, setComparisonOpen] = useState(false);
  const [selectedCompareBranchIds, setSelectedCompareBranchIds] = useState<string[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>(workflowTemplates[0]?.id ?? "");
  const [snapshotName, setSnapshotName] = useState("phase6-main");
  const [selectedSnapshotName, setSelectedSnapshotName] = useState("");
  const hasHydratedRef = useRef(false);

  const sessionId = useWorkspaceStore((state) => state.sessionId);
  const resetWorkspace = useWorkspaceStore((state) => state.resetWorkspace);
  const setSessionId = useWorkspaceStore((state) => state.setSessionId);
  const setMainBranchSession = useWorkflowStore((state) => state.setMainBranchSession);
  const switchBranch = useWorkflowStore((state) => state.switchBranch);
  const forkBranch = useWorkflowStore((state) => state.forkBranch);
  const branches = useWorkflowStore((state) => state.branches);
  const activeBranchId = useWorkflowStore((state) => state.activeBranchId);
  const getForkCandidateNodeId = useWorkflowStore((state) => state.getForkCandidateNodeId);
  const setExecutionError = useWorkflowStore((state) => state.setExecutionError);
  const applyWorkflowTemplate = useWorkflowStore((state) => state.applyWorkflowTemplate);
  const removeSelectedNode = useWorkflowStore((state) => state.removeSelectedNode);
  const hasDeletableSelection = useWorkflowStore((state) => {
    const selectedNodeId = state.selectedNodeId;
    if (!selectedNodeId) {
      return false;
    }
    const branchState = state.branchStates[state.activeBranchId];
    const selectedNode = branchState.nodes.find((node) => node.id === selectedNodeId);
    return Boolean(selectedNode && selectedNode.data.kind !== "group");
  });
  const undo = useWorkflowStore((state) => state.undo);
  const redo = useWorkflowStore((state) => state.redo);
  const historyPastDepth = useWorkflowStore((state) => state.historyPast[state.activeBranchId]?.length ?? 0);
  const historyFutureDepth = useWorkflowStore((state) => state.historyFuture[state.activeBranchId]?.length ?? 0);
  const serializeSnapshot = useWorkflowStore((state) => state.serializeSnapshot);
  const hydrateSnapshot = useWorkflowStore((state) => state.hydrateSnapshot);
  const branchStates = useWorkflowStore((state) => state.branchStates);
  const datasets = useWorkflowStore((state) => state.datasets);
  const queryClient = useQueryClient();

  const activeBranch = branches.find((branch) => branch.id === activeBranchId) ?? null;
  const activeBranchSessionId = activeBranch?.sessionId ?? null;
  const mainBranchSessionId = branches.find((branch) => branch.id === "main")?.sessionId ?? null;
  const canFork = branches.length < 4 && activeBranchSessionId !== null;
  const comparableBranches = useMemo(() => branches.filter((branch) => branch.sessionId !== null), [branches]);
  const canCompare = comparableBranches.length >= 2;
  const canUndo = historyPastDepth > 0;
  const canRedo = historyFutureDepth > 0;
  const hasFailedNodes = Boolean(
    branchStates[activeBranchId]?.nodes.some(
      (node) => (node.data.kind === "operation" || node.data.kind === "dataset") && node.data.status === "error",
    ),
  );
  const execution = useWorkflowExecution();

  useEffect(() => {
    if (activeBranchId !== "main") {
      return;
    }
    if (sessionId === mainBranchSessionId) {
      return;
    }
    setMainBranchSession(sessionId);
  }, [activeBranchId, mainBranchSessionId, sessionId, setMainBranchSession]);

  useEffect(() => {
    const availableIds = comparableBranches.map((branch) => branch.id);
    setSelectedCompareBranchIds((previous) => {
      const filtered = previous.filter((branchId) => availableIds.includes(branchId));
      if (filtered.length > 0) {
        return filtered;
      }
      return availableIds;
    });
  }, [comparableBranches]);

  useEffect(() => {
    if (hasHydratedRef.current) {
      return;
    }
    hasHydratedRef.current = true;

    try {
      const raw = window.localStorage.getItem(WORKFLOW_AUTOSAVE_KEY);
      if (!raw) {
        return;
      }
      const parsed = JSON.parse(raw) as WorkflowSnapshot;
      hydrateSnapshot(parsed);
    } catch {
      // Ignore invalid persisted snapshots and continue with clean workflow state.
    }
  }, [hydrateSnapshot]);

  useEffect(() => {
    const snapshot = serializeSnapshot();
    window.localStorage.setItem(WORKFLOW_AUTOSAVE_KEY, JSON.stringify(snapshot));
  }, [activeBranchId, branchStates, branches, datasets, serializeSnapshot]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (comparisonOpen) {
        return;
      }

      const withModifier = event.ctrlKey || event.metaKey;
      const key = event.key.toLowerCase();

      if (withModifier && key === "z") {
        event.preventDefault();
        if (event.shiftKey) {
          redo();
          return;
        }
        undo();
        return;
      }

      if (withModifier && key === "y") {
        event.preventDefault();
        redo();
        return;
      }

      if (isTypingTarget(event.target)) {
        return;
      }

      if (event.key === "Delete" || event.key === "Backspace") {
        if (hasDeletableSelection) {
          event.preventDefault();
          removeSelectedNode();
        }
        return;
      }

      if (event.code === "Space") {
        event.preventDefault();
        if (execution.isExecuting) {
          void execution.pause();
          return;
        }
        void execution.runAll();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [comparisonOpen, execution, hasDeletableSelection, redo, removeSelectedNode, undo]);

  const healthQuery = useQuery({
    queryKey: ["api-health"],
    queryFn: healthApi.get,
    staleTime: 30_000,
  });

  const summaryQuery = useQuery({
    queryKey: ["session-summary", sessionId],
    queryFn: () => sessionsApi.get(sessionId ?? ""),
    enabled: sessionId !== null,
    staleTime: 10_000,
  });

  const snapshotsQuery = useQuery({
    queryKey: ["workflow-snapshots", sessionId],
    queryFn: () => workflowApi.listSnapshots(sessionId ?? ""),
    enabled: sessionId !== null,
    staleTime: 10_000,
  });

  useEffect(() => {
    const snapshots = snapshotsQuery.data?.snapshots ?? [];
    if (snapshots.length === 0) {
      setSelectedSnapshotName("");
      return;
    }

    setSelectedSnapshotName((current) => {
      if (current && snapshots.some((snapshot) => snapshot.name === current)) {
        return current;
      }
      return snapshots[0].name;
    });
  }, [snapshotsQuery.data]);

  const createSessionMutation = useMutation({
    mutationFn: sessionsApi.create,
    onSuccess: (response) => {
      setSessionId(response.session_id);
      void queryClient.invalidateQueries({ queryKey: ["session-summary"] });
    },
  });

  const resetSessionMutation = useMutation({
    mutationFn: () => sessionsApi.reset(sessionId ?? ""),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["session-summary", sessionId] });
    },
  });

  const deleteSessionMutation = useMutation({
    mutationFn: () => sessionsApi.remove(sessionId ?? ""),
    onSuccess: () => {
      resetWorkspace();
      setMainBranchSession(null);
      void queryClient.invalidateQueries({ queryKey: ["session-summary"] });
    },
  });

  const forkBranchMutation = useMutation({
    mutationFn: async (forkNodeId?: string) => {
      if (!activeBranchSessionId) {
        throw new Error("Create or select a branch session before forking");
      }
      const resolvedForkNodeId = forkNodeId ?? getForkCandidateNodeId();
      const suggestedName = `branch-${branches.length}`;
      return workflowApi.forkBranch(activeBranchSessionId, {
        name: suggestedName,
        from_node_id: resolvedForkNodeId ?? undefined,
      });
    },
    onSuccess: (response) => {
      const created = forkBranch({
        name: response.branch_name,
        forkNodeId: response.from_node_id,
        sessionId: response.branch_session_id,
      });
      if (created) {
        setSessionId(created.sessionId);
        setExecutionError(null);
      }
    },
    onError: (error) => {
      if (error instanceof ApiError) {
        setExecutionError(error.message);
        return;
      }
      if (error instanceof Error) {
        setExecutionError(error.message);
        return;
      }
      setExecutionError("Unable to fork branch");
    },
  });

  const compareBranchesMutation = useMutation({
    mutationFn: async (branchIds: string[]) => {
      if (!sessionId) {
        throw new Error("Create a session before comparing branches");
      }

      const branchSessionIds = branchIds
        .map((branchId) => branches.find((branch) => branch.id === branchId)?.sessionId)
        .filter((candidate): candidate is string => candidate !== null);

      return workflowApi.compare(sessionId, {
        branch_session_ids: branchSessionIds.filter((candidate) => candidate !== sessionId),
      });
    },
  });

  const saveSnapshotMutation = useMutation({
    mutationFn: async () => {
      const targetSessionId = sessionId;
      if (!targetSessionId) {
        throw new Error("Create a session before saving workflow snapshots");
      }

      const name = snapshotName.trim();
      if (!name) {
        throw new Error("Enter a snapshot name before saving");
      }

      return workflowApi.saveSnapshot(targetSessionId, name, serializeSnapshot() as unknown as JsonValue);
    },
    onSuccess: (response) => {
      setSelectedSnapshotName(response.name);
      setExecutionError(null);
      void queryClient.invalidateQueries({ queryKey: ["workflow-snapshots", sessionId] });
    },
    onError: (error) => {
      setExecutionError(toErrorMessage(error));
    },
  });

  const loadSnapshotMutation = useMutation({
    mutationFn: async () => {
      const targetSessionId = sessionId;
      if (!targetSessionId) {
        throw new Error("Create a session before loading workflow snapshots");
      }

      const selectedName = selectedSnapshotName || snapshotName;
      const name = selectedName.trim();
      if (!name) {
        throw new Error("Select or enter a snapshot name before loading");
      }

      return workflowApi.loadSnapshot(targetSessionId, name);
    },
    onSuccess: (response) => {
      const snapshot = response.snapshot;
      if (typeof snapshot !== "object" || snapshot === null || Array.isArray(snapshot)) {
        setExecutionError("Loaded snapshot payload has an invalid format");
        return;
      }

      hydrateSnapshot(snapshot as unknown as WorkflowSnapshot);
      setSelectedSnapshotName(response.name);
      setSnapshotName(response.name);
      setExecutionError(null);
    },
    onError: (error) => {
      setExecutionError(toErrorMessage(error));
    },
  });

  return (
    <div className="workflow-designer">
      <TopBar
        health={healthQuery.data}
        summary={summaryQuery.data}
        sessionId={sessionId}
        onCreateSession={() => createSessionMutation.mutate()}
        onResetSession={() => resetSessionMutation.mutate()}
        onDeleteSession={() => deleteSessionMutation.mutate()}
        onRunAll={execution.runAll}
        onStep={execution.step}
        onPause={execution.pause}
        onForkBranch={() => forkBranchMutation.mutate(undefined)}
        onOpenComparison={() => {
          const branchIds = selectedCompareBranchIds.length > 0 ? selectedCompareBranchIds : comparableBranches.map((branch) => branch.id);
          setSelectedCompareBranchIds(branchIds);
          setComparisonOpen(true);
          if (branchIds.length > 0) {
            compareBranchesMutation.mutate(branchIds);
          }
        }}
        onSelectBranch={(branchId) => {
          const branch = branches.find((candidate) => candidate.id === branchId);
          switchBranch(branchId);
          setSessionId(branch?.sessionId ?? null);
        }}
        templateOptions={workflowTemplates.map((template) => ({ id: template.id, label: template.label }))}
        selectedTemplateId={selectedTemplateId}
        onSelectTemplate={setSelectedTemplateId}
        onApplyTemplate={() => {
          if (!selectedTemplateId) {
            return;
          }
          applyWorkflowTemplate(selectedTemplateId);
          setExecutionError(null);
        }}
        snapshotName={snapshotName}
        onSnapshotNameChange={setSnapshotName}
        snapshotOptions={(snapshotsQuery.data?.snapshots ?? []).map((snapshot) => ({
          name: snapshot.name,
          savedAt: new Date(snapshot.saved_at).toLocaleString(),
        }))}
        selectedSnapshotName={selectedSnapshotName}
        onSelectSnapshot={(name) => {
          setSelectedSnapshotName(name);
          if (name) {
            setSnapshotName(name);
          }
        }}
        onSaveSnapshot={() => saveSnapshotMutation.mutate()}
        onLoadSnapshot={() => loadSnapshotMutation.mutate()}
        isSavingSnapshot={saveSnapshotMutation.isPending}
        isLoadingSnapshot={loadSnapshotMutation.isPending}
        onUndo={undo}
        onRedo={redo}
        onRetryFailed={execution.retryFailed}
        canUndo={canUndo}
        canRedo={canRedo}
        canRetryFailed={hasFailedNodes}
        canFork={canFork}
        isForking={forkBranchMutation.isPending}
        canCompare={canCompare}
        isComparing={compareBranchesMutation.isPending}
        canExecute={execution.canExecute}
        isExecutingWorkflow={execution.isExecuting}
        executionStatusLabel={execution.statusLabel}
        isCreating={createSessionMutation.isPending}
        isResetting={resetSessionMutation.isPending}
        isDeleting={deleteSessionMutation.isPending}
      />

      <div className="workflow-layout-grid">
        <aside className="workflow-sidebar">
          <NodePalette />
          <DatasetPool />
        </aside>

        <main className="workflow-canvas-panel">
          <Canvas
            canFork={canFork}
            isForking={forkBranchMutation.isPending}
            onForkFromNode={(nodeId) => forkBranchMutation.mutate(nodeId)}
          />
          <section className="workflow-route-outlet">
            <Outlet />
          </section>
        </main>
      </div>

      <NodeInspector />

      <ComparisonDashboard
        open={comparisonOpen}
        branches={comparableBranches}
        selectedBranchIds={selectedCompareBranchIds}
        onSelectionChange={setSelectedCompareBranchIds}
        onRefresh={() => compareBranchesMutation.mutate(selectedCompareBranchIds)}
        onClose={() => setComparisonOpen(false)}
        isRefreshing={compareBranchesMutation.isPending}
        comparison={compareBranchesMutation.data ?? null}
        errorMessage={compareBranchesMutation.error ? toErrorMessage(compareBranchesMutation.error) : null}
      />
    </div>
  );
}