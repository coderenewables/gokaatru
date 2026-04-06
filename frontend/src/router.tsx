import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { NavLink, Navigate, Outlet, createBrowserRouter } from "react-router-dom";

import { configApi, healthApi, resultsApi, sessionsApi, uploadsApi } from "./lib/api";
import type {
  ApiHealthResponse,
  SessionSummaryResponse,
  SessionStep,
  SessionSummaryMetric,
} from "./lib/types";
import { useWorkspaceStore } from "./stores/workspaceStore";

type StepDefinition = {
  path: string;
  label: string;
  description: string;
};

const workflowSteps: StepDefinition[] = [
  { path: "/overview", label: "Overview", description: "Session and API state" },
  { path: "/data", label: "Data", description: "Uploads, sensors, and cleaning" },
  { path: "/site", label: "Site", description: "Runconfig and shear setup" },
  { path: "/reanalysis", label: "Reanalysis", description: "ERA5 discovery and interpolation" },
  { path: "/ltc", label: "LTC", description: "Correction, ensemble, uncertainty" },
  { path: "/results", label: "Results", description: "Plots, maps, export contracts" },
];

function useSessionSummaryQuery(sessionId: string | null) {
  return useQuery({
    queryKey: ["session-summary", sessionId],
    queryFn: () => sessionsApi.get(sessionId ?? ""),
    enabled: sessionId !== null,
    staleTime: 15_000,
  });
}

function SectionHeader(props: { title: string; detail: string }) {
  return (
    <header className="section-header">
      <div>
        <h2>{props.title}</h2>
        <p>{props.detail}</p>
      </div>
    </header>
  );
}

function MetricCard(props: { label: string; value: string; tone?: "default" | "accent" }) {
  return (
    <article className={clsx("metric-card", props.tone === "accent" && "metric-card-accent")}>
      <span className="metric-label">{props.label}</span>
      <strong className="metric-value">{props.value}</strong>
    </article>
  );
}

function EmptyState(props: { title: string; detail: string }) {
  return (
    <div className="empty-state">
      <strong>{props.title}</strong>
      <p>{props.detail}</p>
    </div>
  );
}

function StatusBadge(props: { ok: boolean; text: string }) {
  return <span className={clsx("status-badge", props.ok ? "status-ok" : "status-warn")}>{props.text}</span>;
}

function formatValue(value: unknown) {
  if (value === null || value === undefined || value === "") {
    return "Not set";
  }
  if (typeof value === "boolean") {
    return value ? "Yes" : "No";
  }
  if (typeof value === "object") {
    return JSON.stringify(value, null, 2);
  }
  return String(value);
}

function InspectorPanel(props: { health?: ApiHealthResponse; summary?: SessionSummaryResponse }) {
  const completed = props.summary?.completed_steps ?? [];

  return (
    <aside className="inspector-panel">
      <SectionHeader title="Inspector" detail="Live API and session-derived signals from the current scaffold." />
      <div className="inspector-stack">
        <div className="content-card">
          <span className="eyebrow">API health</span>
          <StatusBadge ok={props.health?.status === "ok"} text={props.health?.service ?? "Unavailable"} />
        </div>
        <div className="content-card">
          <span className="eyebrow">Completed steps</span>
          {completed.length > 0 ? (
            <div className="tag-row">
              {completed.map((step) => (
                <span key={step} className="tag-pill">
                  {step}
                </span>
              ))}
            </div>
          ) : (
            <p className="muted-text">No workflow milestones completed yet.</p>
          )}
        </div>
        <div className="content-card">
          <span className="eyebrow">Runconfig snapshot</span>
          <dl className="definition-list">
            <div>
              <dt>Project</dt>
              <dd>{props.summary?.project_name ?? "Not set"}</dd>
            </div>
            <div>
              <dt>Measurement</dt>
              <dd>{props.summary?.measurement_type ?? "Not set"}</dd>
            </div>
            <div>
              <dt>Hub height</dt>
              <dd>{props.summary?.hub_height_m ? `${props.summary.hub_height_m} m` : "Not set"}</dd>
            </div>
          </dl>
        </div>
      </div>
    </aside>
  );
}

function WorkflowLayout() {
  const sessionId = useWorkspaceStore((state) => state.sessionId);
  const setSessionId = useWorkspaceStore((state) => state.setSessionId);
  const resetWorkspace = useWorkspaceStore((state) => state.resetWorkspace);
  const queryClient = useQueryClient();

  const healthQuery = useQuery({
    queryKey: ["api-health"],
    queryFn: healthApi.get,
    staleTime: 30_000,
  });
  const summaryQuery = useSessionSummaryQuery(sessionId);

  const createSessionMutation = useMutation({
    mutationFn: sessionsApi.create,
    onSuccess: (response) => {
      setSessionId(response.session_id);
      void queryClient.invalidateQueries({ queryKey: ["session-summary", response.session_id] });
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
      void queryClient.invalidateQueries({ queryKey: ["session-summary"] });
    },
  });

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <p className="eyebrow">GoKaatru workflow scaffold</p>
          <h1>Browser client over typed /api routes</h1>
          <p className="header-copy">
            This Phase 6.6 shell is intentionally thin: it proves routing, session persistence, and API wiring before the
            page-specific components land.
          </p>
        </div>
        <div className="header-actions">
          <div className="session-chip">
            <span>Session</span>
            <strong>{sessionId ?? "none"}</strong>
          </div>
          <button
            className="primary-button"
            onClick={() => createSessionMutation.mutate()}
            disabled={createSessionMutation.isPending}
            type="button"
          >
            {createSessionMutation.isPending ? "Creating..." : sessionId ? "Replace Session" : "Create Session"}
          </button>
          <button
            className="secondary-button"
            onClick={() => resetSessionMutation.mutate()}
            disabled={sessionId === null || resetSessionMutation.isPending}
            type="button"
          >
            Reset
          </button>
          <button
            className="ghost-button"
            onClick={() => deleteSessionMutation.mutate()}
            disabled={sessionId === null || deleteSessionMutation.isPending}
            type="button"
          >
            Delete
          </button>
        </div>
      </header>

      <div className="layout-grid">
        <nav className="step-nav">
          {workflowSteps.map((step) => {
            const done = summaryQuery.data?.completed_steps.includes(step.label.toLowerCase() as SessionStep) ?? false;
            return (
              <NavLink
                key={step.path}
                className={({ isActive }) => clsx("step-link", isActive && "step-link-active")}
                to={step.path}
              >
                <span className="step-copy">
                  <strong>{step.label}</strong>
                  <small>{step.description}</small>
                </span>
                <StatusBadge ok={done} text={done ? "Ready" : "Pending"} />
              </NavLink>
            );
          })}
        </nav>

        <main className="page-panel">
          <div className="metric-grid">
            <MetricCard label="API" value={healthQuery.data?.status ?? "checking"} tone="accent" />
            <MetricCard label="Project" value={summaryQuery.data?.project_name ?? "Untitled"} />
            <MetricCard label="Hub height" value={summaryQuery.data?.hub_height_m ? `${summaryQuery.data.hub_height_m} m` : "Not set"} />
            <MetricCard label="LTC runs" value={String(summaryQuery.data?.ltc_algorithms.length ?? 0)} />
          </div>
          <Outlet />
        </main>

        <InspectorPanel health={healthQuery.data} summary={summaryQuery.data} />
      </div>
    </div>
  );
}

function OverviewPage() {
  const sessionId = useWorkspaceStore((state) => state.sessionId);
  const summaryQuery = useSessionSummaryQuery(sessionId);

  return (
    <section className="page-section">
      <SectionHeader title="Overview" detail="Health, session summary, and workflow milestones are live from the backend." />
      {sessionId === null ? (
        <EmptyState title="No active session" detail="Create a session from the header to start a browser-scoped workspace." />
      ) : summaryQuery.data ? (
        <div className="content-card stack-gap">
          <p className="muted-text">Workspace directory: {summaryQuery.data.workspace_dir ?? "Unavailable"}</p>
          <div className="tag-row">
            {summaryQuery.data.completed_steps.map((step) => (
              <span key={step} className="tag-pill">
                {step}
              </span>
            ))}
          </div>
        </div>
      ) : (
        <EmptyState title="Session summary loading" detail="The scaffold waits for the backend summary once a session is available." />
      )}
    </section>
  );
}

function DataPage() {
  const sessionId = useWorkspaceStore((state) => state.sessionId);
  const summaryQuery = useSessionSummaryQuery(sessionId);
  const sensorsQuery = useQuery({
    queryKey: ["sensors", sessionId],
    queryFn: () => uploadsApi.getSensors(sessionId ?? ""),
    enabled: sessionId !== null && summaryQuery.data?.datamodel_loaded === true,
    staleTime: 15_000,
  });

  return (
    <section className="page-section">
      <SectionHeader title="Data" detail="The API client is ready for upload, sensor inventory, coverage, and cleaning flows." />
      {sessionId === null ? (
        <EmptyState title="Session required" detail="Uploads and cleaning calls are session-scoped and need a workspace id." />
      ) : (
        <div className="panel-grid">
          <article className="content-card">
            <span className="eyebrow">Upload endpoints</span>
            <ul className="flat-list">
              <li>POST /api/sessions/:id/uploads/timeseries</li>
              <li>POST /api/sessions/:id/uploads/datamodel</li>
              <li>GET /api/sessions/:id/sensors</li>
              <li>GET /api/sessions/:id/coverage/:sensor</li>
            </ul>
          </article>
          <article className="content-card">
            <span className="eyebrow">Loaded sensors</span>
            {sensorsQuery.data ? (
              <ul className="flat-list">
                {sensorsQuery.data.sensors.slice(0, 6).map((sensor) => (
                  <li key={`${sensor.name}-${sensor.height_m}`}>
                    {sensor.name} at {sensor.height_m} m ({sensor.data_coverage_pct.toFixed(1)}%)
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted-text">Sensors will appear here after timeseries and datamodel uploads.</p>
            )}
          </article>
        </div>
      )}
    </section>
  );
}

function SitePage() {
  const sessionId = useWorkspaceStore((state) => state.sessionId);
  const summaryQuery = useQuery({
    queryKey: ["analysis-summary", sessionId],
    queryFn: () => configApi.getSummary(sessionId ?? ""),
    enabled: sessionId !== null,
    staleTime: 15_000,
  });

  return (
    <section className="page-section">
      <SectionHeader title="Site" detail="Runconfig, shear, roughness, and hub-height contracts are ready for the next UI layer." />
      {summaryQuery.data ? (
        <div className="content-card">
          <dl className="definition-list">
            {Object.entries(summaryQuery.data as Record<string, SessionSummaryMetric>).map(([key, value]) => (
              <div key={key}>
                <dt>{key}</dt>
                <dd>{formatValue(value)}</dd>
              </div>
            ))}
          </dl>
        </div>
      ) : (
        <EmptyState title="Summary not available" detail="Create a session to start viewing site configuration state." />
      )}
    </section>
  );
}

function ReanalysisPage() {
  const sessionId = useWorkspaceStore((state) => state.sessionId);
  const summaryQuery = useSessionSummaryQuery(sessionId);
  const mapQuery = useQuery({
    queryKey: ["site-map", sessionId],
    queryFn: () => resultsApi.getSiteMap(sessionId ?? ""),
    enabled: sessionId !== null && summaryQuery.data?.era5_nodes_loaded === true,
    retry: false,
  });

  return (
    <section className="page-section">
      <SectionHeader title="Reanalysis" detail="ERA5 node discovery, extraction, and interpolation endpoints are wired into the client." />
      {mapQuery.data ? (
        <div className="content-card stack-gap">
          <p className="muted-text">GeoJSON features returned: {mapQuery.data.features.length}</p>
          <pre className="code-block">{JSON.stringify(mapQuery.data.features[0], null, 2)}</pre>
        </div>
      ) : (
        <EmptyState title="No node map yet" detail="The map endpoint becomes available after ERA5 node discovery completes." />
      )}
    </section>
  );
}

function LtcPage() {
  const sessionId = useWorkspaceStore((state) => state.sessionId);
  const ltcQuery = useQuery({
    queryKey: ["ltc-results", sessionId],
    queryFn: () => resultsApi.getLtcResults(sessionId ?? ""),
    enabled: sessionId !== null,
    staleTime: 15_000,
  });

  return (
    <section className="page-section">
      <SectionHeader title="LTC" detail="Deterministic LTC, XGBoost, ensemble, clipping, homogeneity, and uncertainty routes are all available." />
      {ltcQuery.data && ltcQuery.data.results.length > 0 ? (
        <div className="panel-grid">
          {ltcQuery.data.results.map((result) => (
            <article key={result.algorithm} className="content-card">
              <span className="eyebrow">{result.algorithm}</span>
              <p className="muted-text">Rows: {result.rows}</p>
            </article>
          ))}
        </div>
      ) : (
        <EmptyState title="No LTC runs yet" detail="Once the workflow executes a correction algorithm, summaries will appear here." />
      )}
    </section>
  );
}

function ResultsPage() {
  const sessionId = useWorkspaceStore((state) => state.sessionId);
  const ensembleQuery = useQuery({
    queryKey: ["ensemble-results", sessionId],
    queryFn: () => resultsApi.getEnsembleResults(sessionId ?? ""),
    enabled: sessionId !== null,
    staleTime: 15_000,
  });

  return (
    <section className="page-section">
      <SectionHeader title="Results" detail="Plots, map payloads, and runconfig export are wired into the scaffolded client library." />
      <div className="panel-grid">
        <article className="content-card">
          <span className="eyebrow">Plot endpoints</span>
          <ul className="flat-list">
            <li>POST /plots/weibull</li>
            <li>POST /plots/windrose</li>
            <li>POST /plots/ltc_comparison</li>
            <li>POST /plots/annual_means</li>
          </ul>
        </article>
        <article className="content-card">
          <span className="eyebrow">Ensemble summary</span>
          <p className="muted-text">
            {ensembleQuery.data?.available ? `Rows available: ${ensembleQuery.data.rows}` : "No ensemble output available yet."}
          </p>
        </article>
      </div>
    </section>
  );
}

export const appRouter = createBrowserRouter([
  {
    path: "/",
    element: <WorkflowLayout />,
    children: [
      { index: true, element: <Navigate replace to="/overview" /> },
      { path: "overview", element: <OverviewPage /> },
      { path: "data", element: <DataPage /> },
      { path: "site", element: <SitePage /> },
      { path: "reanalysis", element: <ReanalysisPage /> },
      { path: "ltc", element: <LtcPage /> },
      { path: "results", element: <ResultsPage /> },
    ],
  },
]);