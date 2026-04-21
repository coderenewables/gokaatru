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
  onRunAll: () => void;
  onStep: () => void;
  onPause: () => void;
  onForkBranch: () => void;
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
  canCompare: boolean;
  isComparing: boolean;
  canExecute: boolean;
  isExecutingWorkflow: boolean;
  executionStatusLabel: string;
  isCreating: boolean;
  isResetting: boolean;
  isDeleting: boolean;
};

export function TopBar({
  health,
  summary,
  sessionId,
  onCreateSession,
  onResetSession,
  onDeleteSession,
  onRunAll,
  onStep,
  onPause,
  onForkBranch,
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
  canCompare,
  isComparing,
  canExecute,
  isExecutingWorkflow,
  executionStatusLabel,
  isCreating,
  isResetting,
  isDeleting,
}: TopBarProps) {
  const branches = useWorkflowStore((state) => state.branches);
  const activeBranchId = useWorkflowStore((state) => state.activeBranchId);

  return (
    <header className="workflow-topbar">
      <div className="workflow-topbar-main">
        <div>
          <span className="eyebrow">GoKaatru workflow designer</span>
          <h1>{summary?.project_name?.trim() ? summary.project_name : "Workflow foundation"}</h1>
          <p className="header-copy">
            Phase 1 swaps in the workflow shell, canvas, palette, and inspector while keeping existing route content alive.
          </p>
        </div>
        <div className="workflow-topbar-actions">
          <div className="session-chip">
            <span>Session</span>
            <strong>{sessionId ?? "none"}</strong>
          </div>
          <div className="session-chip">
            <span>API</span>
            <strong>{health?.status ?? "checking"}</strong>
          </div>
          <button className="secondary-button" type="button" onClick={onCreateSession} disabled={isCreating}>
            {sessionId ? "Replace Session" : "Create Session"}
          </button>
          <button className="secondary-button" type="button" onClick={onResetSession} disabled={!sessionId || isResetting}>
            Reset
          </button>
          <button className="ghost-button" type="button" onClick={onDeleteSession} disabled={!sessionId || isDeleting}>
            Delete
          </button>
        </div>
      </div>

      <div className="workflow-toolbar-row">
        <div className="workflow-run-controls">
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
          <button className="secondary-button" type="button" onClick={onApplyTemplate} disabled={templateOptions.length === 0}>
            Apply Template
          </button>
          <input
            aria-label="Workflow snapshot name"
            className="workflow-template-select"
            placeholder="snapshot name"
            value={snapshotName}
            onChange={(event) => onSnapshotNameChange(event.target.value)}
          />
          <button className="secondary-button" type="button" onClick={onSaveSnapshot} disabled={isSavingSnapshot}>
            {isSavingSnapshot ? "Saving..." : "Save"}
          </button>
          <select
            aria-label="Saved workflows"
            className="workflow-template-select"
            value={selectedSnapshotName}
            onChange={(event) => onSelectSnapshot(event.target.value)}
          >
            <option value="">Saved workflows</option>
            {snapshotOptions.map((snapshot) => (
              <option key={snapshot.name} value={snapshot.name}>
                {snapshot.name} ({snapshot.savedAt})
              </option>
            ))}
          </select>
          <button className="secondary-button" type="button" onClick={onLoadSnapshot} disabled={isLoadingSnapshot}>
            {isLoadingSnapshot ? "Loading..." : "Load"}
          </button>
          <button className="primary-button" type="button" disabled={!canExecute || isExecutingWorkflow} onClick={onRunAll}>
            {isExecutingWorkflow ? "Running..." : "Run All"}
          </button>
          <button className="secondary-button" type="button" disabled={!canExecute || isExecutingWorkflow} onClick={onStep}>
            Step
          </button>
          <button className="ghost-button" type="button" disabled={!isExecutingWorkflow} onClick={onPause}>
            Pause
          </button>
          <button className="ghost-button" type="button" disabled={!canUndo} onClick={onUndo}>
            Undo
          </button>
          <button className="ghost-button" type="button" disabled={!canRedo} onClick={onRedo}>
            Redo
          </button>
          <button className="ghost-button" type="button" disabled={!canRetryFailed || isExecutingWorkflow} onClick={onRetryFailed}>
            Retry Failed
          </button>
          <span className="workflow-phase-chip">{executionStatusLabel}</span>
        </div>
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
          <button className="ghost-button" type="button" disabled={!canFork || isForking} onClick={onForkBranch}>
            {isForking ? "Forking..." : "Fork"}
          </button>
          <button className="ghost-button" type="button" disabled={!canCompare || isComparing} onClick={onOpenComparison}>
            {isComparing ? "Comparing..." : "Compare"}
          </button>
        </div>
      </div>

      <nav className="workflow-detail-nav" aria-label="Workflow detail routes">
        {workflowSteps.map((step) => (
          <NavLink
            key={step.path}
            to={step.path}
            className={({ isActive }) => `workflow-detail-link ${isActive ? "workflow-detail-link-active" : ""}`}
          >
            {step.label}
          </NavLink>
        ))}
      </nav>
    </header>
  );
}