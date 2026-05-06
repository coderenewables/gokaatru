import { useState } from "react";
import { NavLink } from "react-router-dom";

import type { ApiHealthResponse, SessionSummaryResponse } from "../../lib/types";
import { workflowSteps } from "../../lib/workflow";
import { useWorkflowStore } from "../../stores/workflowStore";

type TopBarProps = {
  health?: ApiHealthResponse;
  summary?: SessionSummaryResponse;
  sessionId: string | null;
  onCreateSession: () => void;
  onResetSession: () => void;
  onDeleteSession: () => void;
  onClearCanvas: () => void;
  onRunAll: () => void;
  onStep: () => void;
  onPause: () => void;
  onForkBranch: () => void;
  onDeleteActiveBranch: () => void;
  onOpenComparison: () => void;
  onSelectBranch: (branchId: string) => void;
  templateOptions: Array<{ id: string; label: string }>;
  selectedTemplateId: string;
  onSelectTemplate: (templateId: string) => void;
  onApplyTemplate: () => void;
  snapshotName: string;
  onSnapshotNameChange: (name: string) => void;
  snapshotOptions: Array<{ name: string; savedAt: string }>;
  selectedSnapshotName: string;
  onSelectSnapshot: (name: string) => void;
  onSaveSnapshot: () => void;
  onLoadSnapshot: () => void;
  isSavingSnapshot: boolean;
  isLoadingSnapshot: boolean;
  onUndo: () => void;
  onRedo: () => void;
  onRetryFailed: () => void;
  canUndo: boolean;
  canRedo: boolean;
  canRetryFailed: boolean;
  canFork: boolean;
  isForking: boolean;
  canDeleteActiveBranch: boolean;
  isDeletingBranch: boolean;
  canCompare: boolean;
  isComparing: boolean;
  canClearCanvas: boolean;
  canExecute: boolean;
  isExecutingWorkflow: boolean;
  executionStatusLabel: string;
  isCreating: boolean;
  isResetting: boolean;
  isDeleting: boolean;
};

function shortId(id: string | null): string {
  if (!id) return "none";
  return id.length > 12 ? `${id.slice(0, 8)}…` : id;
}

const NAV_LABELS: Record<string, string> = {
  "/site": "V. Extrapolation",
  "/ltc": "LTC (MCP)",
};

function navLabel(step: { path: string; label: string }): string {
  return NAV_LABELS[step.path] ?? step.label;
}

export function TopBar({
  health,
  summary,
  sessionId,
  onCreateSession,
  onResetSession,
  onDeleteSession,
  onClearCanvas,
  onRunAll,
  onStep,
  onPause,
  onForkBranch,
  onDeleteActiveBranch,
  onOpenComparison,
  onSelectBranch,
  templateOptions,
  selectedTemplateId,
  onSelectTemplate,
  onApplyTemplate,
  snapshotName,
  onSnapshotNameChange,
  snapshotOptions,
  selectedSnapshotName,
  onSelectSnapshot,
  onSaveSnapshot,
  onLoadSnapshot,
  isSavingSnapshot,
  isLoadingSnapshot,
  onUndo,
  onRedo,
  onRetryFailed,
  canUndo,
  canRedo,
  canRetryFailed,
  canFork,
  isForking,
  canDeleteActiveBranch,
  isDeletingBranch,
  canCompare,
  isComparing,
  canClearCanvas,
  canExecute,
  isExecutingWorkflow,
  executionStatusLabel,
  isCreating,
  isResetting,
  isDeleting,
}: TopBarProps) {
  const branches = useWorkflowStore((state) => state.branches);
  const activeBranchId = useWorkflowStore((state) => state.activeBranchId);

  const [pendingAction, setPendingAction] = useState<"reset" | "delete" | "template" | "clearCanvas" | "deleteFork" | null>(null);

  const noSessionReason = "Create a session first";

  function confirmReset() {
    setPendingAction(null);
    onResetSession();
  }

  function confirmDelete() {
    setPendingAction(null);
    onDeleteSession();
  }

  function confirmTemplate() {
    setPendingAction(null);
    onApplyTemplate();
  }

  function confirmClearCanvas() {
    setPendingAction(null);
    onClearCanvas();
  }

  function confirmDeleteFork() {
    setPendingAction(null);
    onDeleteActiveBranch();
  }

  return (
    <>
      {/* ── Confirmation dialog ── */}
      {pendingAction !== null && (
        <div className="workflow-modal-overlay" role="dialog" aria-modal="true">
          <div className="workflow-modal">
            <div className="workflow-modal-header">
              <h3>
                {pendingAction === "reset" && "Reset session?"}
                {pendingAction === "delete" && "Delete session?"}
                {pendingAction === "template" && "Apply template?"}
                {pendingAction === "clearCanvas" && "Clear canvas?"}
                {pendingAction === "deleteFork" && "Delete fork branch?"}
              </h3>
            </div>
            <div className="workflow-modal-body">
              {pendingAction === "reset" && (
                <p>This will clear all results and restart the session. This cannot be undone.</p>
              )}
              {pendingAction === "delete" && (
                <p>This will permanently delete the session and all its data. This cannot be undone.</p>
              )}
              {pendingAction === "template" && (
                <p>Applying a template will replace the current canvas layout. Unsaved node changes will be lost.</p>
              )}
              {pendingAction === "clearCanvas" && (
                <p>This will remove all workflow nodes on the current branch and keep only the baseline lanes.</p>
              )}
              {pendingAction === "deleteFork" && (
                <p>This will delete the active fork branch and its branch session. This cannot be undone.</p>
              )}
            </div>
            <div className="workflow-modal-actions">
              <button className="ghost-button" type="button" onClick={() => setPendingAction(null)}>
                Cancel
              </button>
              <button
                className={pendingAction === "template" ? "secondary-button" : "topbar-danger-button"}
                type="button"
                onClick={
                  pendingAction === "reset"
                    ? confirmReset
                    : pendingAction === "delete"
                      ? confirmDelete
                      : pendingAction === "clearCanvas"
                        ? confirmClearCanvas
                        : pendingAction === "deleteFork"
                          ? confirmDeleteFork
                          : confirmTemplate
                }
              >
                {pendingAction === "reset" && "Reset"}
                {pendingAction === "delete" && "Delete"}
                {pendingAction === "template" && "Apply"}
                {pendingAction === "clearCanvas" && "Clear"}
                {pendingAction === "deleteFork" && "Delete Fork"}
              </button>
            </div>
          </div>
        </div>
      )}

      <header className="workflow-topbar">
        {/* ── Row 1: identity + session controls ── */}
        <div className="workflow-topbar-main">
          <div className="workflow-topbar-identity">
            <span className="eyebrow">GoKaatru</span>
            <h1>{summary?.project_name?.trim() ? summary.project_name : "Wind Resource Analysis"}</h1>
          </div>
          <div className="workflow-topbar-actions">
            <div className="session-chip" title={sessionId ?? undefined}>
              <span>Session</span>
              <strong className="session-chip-id">{shortId(sessionId)}</strong>
            </div>
            <div className={`session-chip session-api-chip ${health?.status === "ok" ? "session-api-ok" : ""}`}>
              <span>API</span>
              <strong>{health?.status ?? "checking"}</strong>
            </div>
            {!sessionId ? (
              <button className="primary-button" type="button" onClick={onCreateSession} disabled={isCreating}>
                {isCreating ? "Creating…" : "Create Session"}
              </button>
            ) : (
              <>
                <button
                  className="secondary-button"
                  type="button"
                  onClick={() => setPendingAction("reset")}
                  disabled={isResetting}
                  title="Clear results and restart this session"
                >
                  {isResetting ? "Resetting…" : "Reset"}
                </button>
                <button
                  className="topbar-danger-button"
                  type="button"
                  onClick={() => setPendingAction("delete")}
                  disabled={isDeleting}
                  title="Permanently delete this session"
                >
                  {isDeleting ? "Deleting…" : "Delete"}
                </button>
              </>
            )}
          </div>
        </div>

        {/* ── Row 2: template | snapshot | execution ── */}
        <div className="workflow-toolbar-row">
          <div className="workflow-run-controls">
            {/* Template group */}
            <div className="toolbar-group" aria-label="Workflow template">
              <select
                aria-label="Workflow template"
                className="workflow-template-select"
                value={selectedTemplateId}
                onChange={(event) => onSelectTemplate(event.target.value)}
              >
                {templateOptions.map((template) => (
                  <option key={template.id} value={template.id}>
                    {template.label}
                  </option>
                ))}
              </select>
              <button
                className="secondary-button"
                type="button"
                onClick={() => setPendingAction("template")}
                disabled={templateOptions.length === 0}
                title="Load this template onto the canvas"
              >
                Apply Template
              </button>
            </div>

            <div className="toolbar-divider" aria-hidden="true" />

            {/* Snapshot group */}
            <div className="toolbar-group" aria-label="Workflow snapshots">
              <input
                aria-label="Workflow snapshot name"
                className="workflow-template-select"
                placeholder="snapshot name"
                value={snapshotName}
                onChange={(event) => onSnapshotNameChange(event.target.value)}
              />
              <button
                className="secondary-button"
                type="button"
                onClick={onSaveSnapshot}
                disabled={isSavingSnapshot}
                title="Save the current canvas as a named snapshot"
              >
                {isSavingSnapshot ? "Saving…" : "Save"}
              </button>
              <select
                aria-label="Saved workflows"
                className="workflow-template-select"
                value={selectedSnapshotName}
                onChange={(event) => onSelectSnapshot(event.target.value)}
              >
                <option value="">Saved snapshots</option>
                {snapshotOptions.map((snapshot) => (
                  <option key={snapshot.name} value={snapshot.name}>
                    {snapshot.name} ({snapshot.savedAt})
                  </option>
                ))}
              </select>
              <button
                className="secondary-button"
                type="button"
                onClick={onLoadSnapshot}
                disabled={isLoadingSnapshot}
                title="Restore the selected snapshot onto the canvas"
              >
                {isLoadingSnapshot ? "Loading…" : "Load"}
              </button>
            </div>

            <div className="toolbar-divider" aria-hidden="true" />

            {/* Execution group */}
            <div className="toolbar-group" aria-label="Workflow execution">
              <button
                className="primary-button"
                type="button"
                disabled={!canExecute || isExecutingWorkflow}
                onClick={onRunAll}
                title={!canExecute ? noSessionReason : "Run all nodes in sequence"}
              >
                {isExecutingWorkflow ? "Running…" : "Run All"}
              </button>
              <button
                className="secondary-button"
                type="button"
                disabled={!canExecute || isExecutingWorkflow}
                onClick={onStep}
                title={!canExecute ? noSessionReason : "Run one step at a time"}
              >
                Step
              </button>
              <button
                className="ghost-button"
                type="button"
                disabled={!isExecutingWorkflow}
                onClick={onPause}
                title="Pause execution"
              >
                Pause
              </button>
              <button
                className="secondary-button"
                type="button"
                disabled={!canUndo}
                onClick={onUndo}
                title={!canUndo ? "Nothing to undo" : "Undo last canvas change (Ctrl+Z)"}
              >
                Undo
              </button>
              <button
                className="secondary-button"
                type="button"
                disabled={!canRedo}
                onClick={onRedo}
                title={!canRedo ? "Nothing to redo" : "Redo last canvas change (Ctrl+Y)"}
              >
                Redo
              </button>
              <button
                className="secondary-button"
                type="button"
                disabled={!canRetryFailed || isExecutingWorkflow}
                onClick={onRetryFailed}
                title={!canRetryFailed ? "No failed nodes to retry" : "Re-run all nodes that errored"}
              >
                Retry Failed
              </button>
              <button
                className="topbar-danger-button"
                type="button"
                disabled={!canClearCanvas}
                onClick={() => setPendingAction("clearCanvas")}
                title={!canClearCanvas ? "Canvas is already clear" : "Remove all nodes from the active branch"}
              >
                Clear Canvas
              </button>
              {executionStatusLabel && (
                <span className="workflow-phase-chip">{executionStatusLabel}</span>
              )}
            </div>
          </div>

          {/* Branch strip */}
          <div className="workflow-branch-strip">
            {branches.map((branch) => (
              <button
                key={branch.id}
                type="button"
                className={`workflow-branch-chip ${branch.id === activeBranchId ? "workflow-branch-chip-active" : ""}`}
                onClick={() => onSelectBranch(branch.id)}
              >
                {branch.name}
              </button>
            ))}
            <button
              className="ghost-button"
              type="button"
              disabled={!canFork || isForking}
              onClick={onForkBranch}
              title={!canFork ? (branches.length >= 4 ? "Maximum of 4 branches reached" : noSessionReason) : "Fork a new branch from the current state"}
            >
              {isForking ? "Forking…" : "Fork"}
            </button>
            <button
              className="topbar-danger-button"
              type="button"
              disabled={!canDeleteActiveBranch || isDeletingBranch}
              onClick={() => setPendingAction("deleteFork")}
              title={!canDeleteActiveBranch ? "Main branch cannot be deleted" : "Delete the selected fork branch"}
            >
              {isDeletingBranch ? "Deleting Fork…" : "Delete Fork"}
            </button>
            <button
              className="ghost-button"
              type="button"
              disabled={!canCompare || isComparing}
              onClick={onOpenComparison}
              title={!canCompare ? "Need at least 2 branches with sessions to compare" : "Compare branches side-by-side"}
            >
              {isComparing ? "Comparing…" : "Compare"}
            </button>
          </div>
        </div>

        {/* ── Row 3: page navigation ── */}
        <nav className="workflow-detail-nav" aria-label="Workflow detail routes">
          {workflowSteps.map((step) => (
            <NavLink
              key={step.path}
              to={step.path}
              title={step.description}
              className={({ isActive }) => `workflow-detail-link ${isActive ? "workflow-detail-link-active" : ""}`}
            >
              {navLabel(step)}
            </NavLink>
          ))}
        </nav>
      </header>
    </>
  );
}