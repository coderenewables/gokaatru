import { useEffect, useState } from "react";

import { fetchOpenApiSpec, getApiHealth, listDatasets } from "../lib/api";
import { loadMcpCatalog } from "../lib/mcpClient";
import { extractWindKitTools } from "../lib/openapi";

type ReadinessState = "loading" | "ready" | "error";

interface HomeViewProps {
  apiBaseUrl: string;
  busyLabel: string | null;
  sessionError: string | null;
  sessionStatus: "idle" | "loading" | "ready" | "error";
  onStart: () => void;
}

interface ReadinessItem {
  label: string;
  value: string;
  detail: string;
  state: ReadinessState;
}

interface HomeReadiness {
  api: ReadinessItem;
  datasets: ReadinessItem;
  windkit: ReadinessItem;
  mcp: ReadinessItem;
}

const projectPoints = [
  "One workspace for ingestion, correction, uncertainty, and comparison.",
  "Standard routes, MCP tools, and WindKit on the same session model.",
  "Open enough to inspect, reproduce, and challenge the analysis.",
] as const;

function createInitialReadiness(): HomeReadiness {
  return {
    api: {
      label: "Web API",
      value: "Checking",
      detail: "Verifying the workflow API before session launch.",
      state: "loading",
    },
    datasets: {
      label: "Shared datasets",
      value: "Checking",
      detail: "Counting reusable uploaded datasets.",
      state: "loading",
    },
    windkit: {
      label: "WindKit routes",
      value: "Checking",
      detail: "Reading the OpenAPI contract exposed by the backend.",
      state: "loading",
    },
    mcp: {
      label: "MCP catalog",
      value: "Checking",
      detail: "Connecting to the configured MCP transport.",
      state: "loading",
    },
  };
}

function withTimeout<T>(promise: Promise<T>, timeoutMs: number, label: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = globalThis.setTimeout(() => reject(new Error(`${label} timed out`)), timeoutMs);
    promise.then(
      (value) => {
        globalThis.clearTimeout(timer);
        resolve(value);
      },
      (error: unknown) => {
        globalThis.clearTimeout(timer);
        reject(error);
      },
    );
  });
}

function asMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message.trim().length > 0) {
    return error.message;
  }
  return fallback;
}

function readinessToneLabel(state: ReadinessState): string {
  if (state === "ready") {
    return "Ready";
  }
  if (state === "error") {
    return "Needs attention";
  }
  return "Checking";
}

export function HomeView({ apiBaseUrl, busyLabel, sessionError, sessionStatus, onStart }: HomeViewProps) {
  const [readiness, setReadiness] = useState<HomeReadiness>(() => createInitialReadiness());

  useEffect(() => {
    let cancelled = false;

    async function loadReadiness() {
      setReadiness(createInitialReadiness());

      const [apiResult, datasetsResult, openApiResult, mcpResult] = await Promise.allSettled([
        withTimeout(getApiHealth(apiBaseUrl), 4000, "API health check"),
        withTimeout(listDatasets(apiBaseUrl), 4000, "Dataset catalog"),
        withTimeout(fetchOpenApiSpec(apiBaseUrl), 5000, "WindKit route discovery"),
        withTimeout(loadMcpCatalog(), 5000, "MCP catalog"),
      ]);

      if (cancelled) {
        return;
      }

      setReadiness({
        api:
          apiResult.status === "fulfilled"
            ? {
                label: "Web API",
                value: apiResult.value.service,
                detail: apiResult.value.status === "ok" ? "Workflow API is reachable from the browser." : apiResult.value.status,
                state: apiResult.value.status === "ok" ? "ready" : "error",
              }
            : {
                label: "Web API",
                value: "Unavailable",
                detail: asMessage(apiResult.reason, "Workflow API is not reachable."),
                state: "error",
              },
        datasets:
          datasetsResult.status === "fulfilled"
            ? {
                label: "Shared datasets",
                value: `${datasetsResult.value.datasets.length}`,
                detail:
                  datasetsResult.value.datasets.length > 0
                    ? "Reusable uploaded datasets are ready for quick starts."
                    : "No shared datasets are available yet, but direct uploads are ready.",
                state: "ready",
              }
            : {
                label: "Shared datasets",
                value: "Unavailable",
                detail: asMessage(datasetsResult.reason, "Dataset catalog could not be loaded."),
                state: "error",
              },
        windkit:
          openApiResult.status === "fulfilled"
            ? {
                label: "WindKit routes",
                value: `${extractWindKitTools(openApiResult.value as never).length}`,
                detail: "WindKit-backed operations were discovered from the live OpenAPI contract.",
                state: "ready",
              }
            : {
                label: "WindKit routes",
                value: "Unavailable",
                detail: asMessage(openApiResult.reason, "WindKit routes could not be discovered."),
                state: "error",
              },
        mcp:
          mcpResult.status === "fulfilled"
            ? {
                label: "MCP catalog",
                value: `${mcpResult.value.tools.length}`,
                detail: `${mcpResult.value.serverName} ${mcpResult.value.serverVersion}`,
                state: "ready",
              }
            : {
                label: "MCP catalog",
                value: "Unavailable",
                detail: asMessage(mcpResult.reason, "Configured MCP transport is not reachable."),
                state: "error",
              },
      });
    }

    void loadReadiness();
    return () => {
      cancelled = true;
    };
  }, [apiBaseUrl]);

  const readinessItems = Object.values(readiness);
  const readyCount = readinessItems.filter((item) => item.state === "ready").length;
  const primaryLabel = sessionStatus === "loading" ? busyLabel ?? "Preparing workspace..." : "Start analysis workspace";

  return (
    <main className="app-shell launch-shell">
      <section className="hero-panel hero-panel-large home-stage">
        <div className="home-stage-copy">
          <p className="eyebrow">Open-source attempt</p>
          <h1>A more transparent workspace for wind resource assessment.</h1>
          <p className="lede">
            GoKaatru brings wind assessment into one browser workspace so data, configuration, tools, and results stay connected.
          </p>

          <div className="button-row home-stage-actions">
            <button className="primary-button" disabled={sessionStatus === "loading"} onClick={onStart} type="button">
              {primaryLabel}
            </button>
            <a className="secondary-button button-link" href="#home-status">
              View live stack
            </a>
          </div>

          {sessionError ? (
            <p className="error-text home-inline-error" role="alert">
              {sessionError}
            </p>
          ) : null}

        </div>

        <aside className="home-stage-aside">
          <div className="home-stage-glow" aria-hidden="true">
            <span className="home-stage-glow-ring home-stage-glow-ring-large" />
            <span className="home-stage-glow-ring home-stage-glow-ring-small" />
          </div>
          <p className="panel-kicker">What this project is trying to do</p>
          <h2>Less fragmented tooling. More inspectable analysis.</h2>
          <p className="muted-text">
            Keep the workflow readable while standard tools, MCP, and WindKit operate on the same session data.
          </p>
          <div className="home-stage-facts">
            <article className="home-stage-fact">
              <span>Scope</span>
              <strong>Ingest to compare</strong>
            </article>
            <article className="home-stage-fact">
              <span>Interface</span>
              <strong>MCP + API + WindKit</strong>
            </article>
            <article className="home-stage-fact">
              <span>Mode</span>
              <strong>Built in the open</strong>
            </article>
          </div>
        </aside>
      </section>

      <section className="home-story-grid">
        <article className="panel home-story-panel">
          <p className="panel-kicker">What it is trying to achieve</p>
          <ul className="home-goal-list">
            {projectPoints.map((attempt) => (
              <li key={attempt}>{attempt}</li>
            ))}
          </ul>
        </article>

        <article className="panel home-story-panel home-story-panel-compact">
          <p className="panel-kicker">Why it stays open</p>
          <h2>Visible state over hidden steps.</h2>
          <p>Uploads, config, tool outputs, and scenario results stay in one workspace instead of being scattered across scripts and closed workflows.</p>
        </article>
      </section>

      <section className="panel home-status-band" id="home-status" aria-label="Live stack status">
        <div className="home-status-band-header">
          <div>
            <p className="panel-kicker">Live stack status</p>
            <h2>What is online right now</h2>
          </div>
          <p className="home-status-summary">{readyCount}/4 checks responded from this browser session.</p>
        </div>
        <div className="home-status-inline-list">
          {readinessItems.map((item) => (
            <article className={`home-status-inline-card home-status-inline-card-${item.state}`} key={item.label}>
              <div className="home-status-inline-top">
                <p className="home-status-label">{item.label}</p>
                <span className={`home-status-pill home-status-pill-${item.state}`}>{readinessToneLabel(item.state)}</span>
              </div>
              <strong>{item.value}</strong>
              <p>{item.detail}</p>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}