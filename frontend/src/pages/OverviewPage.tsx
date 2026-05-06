import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { configApi, healthApi, sessionsApi } from "../lib/api";
import { usePageTitle } from "../hooks/usePageTitle";
import { findNextIncompletePath, workflowSteps, isWorkflowStepComplete } from "../lib/workflow";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { EmptyState } from "../components/common/EmptyState";
import { ErrorBanner } from "../components/common/ErrorBanner";
import { MetricCard } from "../components/common/MetricCard";
import { PageHeader } from "../components/common/PageHeader";
import { StatusBadge } from "../components/common/StatusBadge";

function summaryValue(value: unknown) {
  if (value === null || value === undefined) {
    return "Not set";
  }
  if (typeof value === "boolean") {
    return value ? "Yes" : "No";
  }
  if (Array.isArray(value)) {
    return value.length ? value.join(", ") : "None";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

export function OverviewPage() {
  usePageTitle("Overview");
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

  const projectSummaryQuery = useQuery({
    queryKey: ["analysis-summary", sessionId],
    queryFn: () => configApi.getSummary(sessionId ?? ""),
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
  const projectSummary = projectSummaryQuery.data;
  const latestError = healthQuery.error ?? summaryQuery.error ?? projectSummaryQuery.error;

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
        <MetricCard label="Project" value={projectSummary?.project_name ? String(projectSummary.project_name) : summary?.project_name ?? "Untitled"} />
        <MetricCard label="Completed" value={String(summary?.completed_steps.length ?? 0)} />
        <MetricCard label="Workspace" value={summary?.workspace_dir ?? "Unavailable"} detail={sessionId} />
      </div>

      {latestError ? <ErrorBanner error={latestError} /> : null}

      {projectSummary?.timeseries_loaded ? (
        <article className="content-card stack-gap">
          <span className="eyebrow">Data quality scorecard</span>
          <div className="metric-grid">
            <MetricCard label="Sensors" value={String(projectSummary.sensor_count ?? 0)} />
            <MetricCard
              label="Average coverage"
              value={typeof projectSummary.avg_coverage_pct === "number" ? `${projectSummary.avg_coverage_pct.toFixed(1)}%` : "—"}
              tone={typeof projectSummary.avg_coverage_pct === "number" && projectSummary.avg_coverage_pct > 90 ? "accent" : "default"}
            />
            <MetricCard label="Cleaning rules" value={String(projectSummary.cleaning_rules_applied ?? 0)} />
            <MetricCard label="LTC algorithms" value={String((projectSummary.ltc_algorithms_run as unknown[] | undefined)?.length ?? 0)} />
          </div>
        </article>
      ) : null}

      {summary && projectSummary ? (
        <div className="panel-grid panel-grid-two">
          <article className="content-card stack-gap">
            <span className="eyebrow">Project summary (/summary)</span>
            <dl className="definition-list">
              <div>
                <dt>Timeseries loaded</dt>
                <dd>{summaryValue(projectSummary.timeseries_loaded)}</dd>
              </div>
              <div>
                <dt>Sensor mapping</dt>
                <dd>{summaryValue(projectSummary.sensor_mapping_loaded)}</dd>
              </div>
              <div>
                <dt>Cleaning rules</dt>
                <dd>{summaryValue(projectSummary.cleaning_rules_applied)}</dd>
              </div>
              <div>
                <dt>ERA5 datasets</dt>
                <dd>{summaryValue(projectSummary.era5_data_sets_loaded)}</dd>
              </div>
              <div>
                <dt>Coordinate</dt>
                <dd>{summaryValue(projectSummary.coordinate)}</dd>
              </div>
              <div>
                <dt>LTC algorithms</dt>
                <dd>{summaryValue(projectSummary.ltc_algorithms_run)}</dd>
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
        <EmptyState title="Loading session" detail="The workflow and analysis summary will appear once the current session metadata is loaded." />
      )}
    </section>
  );
}