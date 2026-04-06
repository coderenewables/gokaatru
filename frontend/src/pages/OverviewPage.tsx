import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { healthApi, sessionsApi } from "../lib/api";
import { findNextIncompletePath, workflowSteps, isWorkflowStepComplete } from "../lib/workflow";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { EmptyState } from "../components/common/EmptyState";
import { MetricCard } from "../components/common/MetricCard";
import { PageHeader } from "../components/common/PageHeader";
import { StatusBadge } from "../components/common/StatusBadge";

export function OverviewPage() {
  const navigate = useNavigate();
  const sessionId = useWorkspaceStore((state) => state.sessionId);

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

  if (!sessionId) {
    return (
      <section className="page-section">
        <PageHeader title="Overview" detail="Health, workflow status, and next-step navigation for the current browser session." />
        <EmptyState title="No active session" detail="Create a session from the header to start the workflow." />
      </section>
    );
  }

  const summary = summaryQuery.data;

  return (
    <section className="page-section">
      <PageHeader
        title="Overview"
        detail="Use this page to check API reachability, session state, and jump directly to the next incomplete workflow page."
        actions={
          <button className="primary-button" type="button" onClick={() => navigate(findNextIncompletePath(summary))}>
            Go To Next Step
          </button>
        }
      />

      <div className="metric-grid">
        <MetricCard label="API status" value={healthQuery.data?.status ?? "checking"} tone="accent" />
        <MetricCard label="Project" value={summary?.project_name ?? "Untitled"} />
        <MetricCard label="Completed" value={String(summary?.completed_steps.length ?? 0)} />
        <MetricCard label="Workspace" value={summary?.workspace_dir ?? "Unavailable"} detail={sessionId} />
      </div>

      {summary ? (
        <div className="panel-grid panel-grid-two">
          <article className="content-card stack-gap">
            <span className="eyebrow">Session summary</span>
            <dl className="definition-list">
              <div>
                <dt>Measurement type</dt>
                <dd>{summary.measurement_type ?? "Not set"}</dd>
              </div>
              <div>
                <dt>Hub height</dt>
                <dd>{summary.hub_height_m ? `${summary.hub_height_m} m` : "Not set"}</dd>
              </div>
              <div>
                <dt>ERA5 interpolated</dt>
                <dd>{summary.era5_interpolated_loaded ? "Ready" : "Pending"}</dd>
              </div>
              <div>
                <dt>LTC algorithms</dt>
                <dd>{summary.ltc_algorithms.length ? summary.ltc_algorithms.join(", ") : "None"}</dd>
              </div>
            </dl>
          </article>

          <article className="content-card stack-gap">
            <span className="eyebrow">Workflow steps</span>
            <div className="step-overview-list">
              {workflowSteps.map((step) => {
                const complete = isWorkflowStepComplete(summary, step);
                return (
                  <button key={step.path} className="step-overview-item" type="button" onClick={() => navigate(step.path)}>
                    <span>
                      <strong>{step.label}</strong>
                      <small>{step.description}</small>
                    </span>
                    <StatusBadge tone={complete ? "ok" : "idle"} text={complete ? "Ready" : "Pending"} />
                  </button>
                );
              })}
            </div>
          </article>
        </div>
      ) : (
        <EmptyState title="Loading session" detail="The workflow summary will appear once the session metadata is loaded." />
      )}
    </section>
  );
}