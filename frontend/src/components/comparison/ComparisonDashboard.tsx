import { ConfigDiff } from "./ConfigDiff";
import { ExportComparison } from "./ExportComparison";
import { MetricsTable } from "./MetricsTable";
import { OverlayPlots } from "./OverlayPlots";

import type { WorkflowCompareResponse } from "../../lib/types";

type BranchOption = {
  id: string;
  name: string;
  color: string;
  sessionId: string | null;
};

type ComparisonDashboardProps = {
  open: boolean;
  branches: BranchOption[];
  selectedBranchIds: string[];
  onSelectionChange: (branchIds: string[]) => void;
  onRefresh: () => void;
  onClose: () => void;
  isRefreshing: boolean;
  comparison: WorkflowCompareResponse | null;
  errorMessage: string | null;
};

export function ComparisonDashboard({
  open,
  branches,
  selectedBranchIds,
  onSelectionChange,
  onRefresh,
  onClose,
  isRefreshing,
  comparison,
  errorMessage,
}: ComparisonDashboardProps) {
  if (!open) {
    return null;
  }

  const selectableBranches = branches.filter((branch) => branch.sessionId !== null);

  const sessionLabels: Record<string, string> = {};
  for (const branch of selectableBranches) {
    if (!branch.sessionId) {
      continue;
    }
    sessionLabels[branch.sessionId] = branch.name;
  }

  const orderedSessions = comparison?.session_ids ?? selectableBranches.map((branch) => branch.sessionId ?? "").filter((value) => value !== "");

  return (
    <div className="workflow-compare-overlay" role="dialog" aria-modal="true" aria-label="Branch comparison dashboard">
      <div className="workflow-compare-modal">
        <header className="workflow-compare-header">
          <div>
            <span className="eyebrow">Phase 5</span>
            <h2>Comparison Dashboard</h2>
          </div>
          <div className="workflow-compare-actions">
            <button className="secondary-button" type="button" onClick={onRefresh} disabled={isRefreshing || selectedBranchIds.length === 0}>
              {isRefreshing ? "Refreshing..." : "Refresh"}
            </button>
            <button className="ghost-button" type="button" onClick={onClose}>
              Close
            </button>
          </div>
        </header>

        <section className="workflow-compare-branch-selector">
          {selectableBranches.map((branch) => {
            const checked = selectedBranchIds.includes(branch.id);
            return (
              <label key={branch.id} className="workflow-compare-branch-option">
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={(event) => {
                    if (event.target.checked) {
                      onSelectionChange([...selectedBranchIds, branch.id]);
                      return;
                    }
                    onSelectionChange(selectedBranchIds.filter((branchId) => branchId !== branch.id));
                  }}
                />
                <span className="workflow-compare-branch-dot" />
                <span>{branch.name}</span>
              </label>
            );
          })}
        </section>

        {errorMessage ? <p className="workflow-error-text">{errorMessage}</p> : null}

        {!comparison ? <p className="muted-text">Run a comparison to see metric deltas, config diffs, and overlays.</p> : null}

        {comparison ? (
          <>
            <section className="workflow-panel-card">
              <div className="workflow-panel-header">
                <h2>Metrics</h2>
              </div>
              <MetricsTable metrics={comparison.metrics} sessionOrder={orderedSessions} sessionLabels={sessionLabels} />
            </section>

            <section className="workflow-panel-card">
              <div className="workflow-panel-header">
                <h2>Config Diff</h2>
              </div>
              <ConfigDiff configDiff={comparison.config_diff} />
            </section>

            <section className="workflow-panel-card">
              <div className="workflow-panel-header">
                <h2>Overlay Plots</h2>
              </div>
              <OverlayPlots plots={comparison.plots} />
            </section>

            <section className="workflow-panel-card">
              <div className="workflow-panel-header">
                <h2>Export</h2>
              </div>
              <ExportComparison comparison={comparison} sessionLabels={sessionLabels} />
            </section>
          </>
        ) : null}
      </div>
    </div>
  );
}
