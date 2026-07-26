# GoKaatru — Workflow-Driven Frontend Specification

> **Scope.** This document is the complete build contract for a **new, workflow-driven frontend** for the GoKaatru wind-resource-assessment app. It targets the Python backend in [`server/`](./server/) (FastAPI + FastMCP). The `frontend/` directory does not currently exist — this spec covers scaffolding from an empty directory through to the full 8-stage app.
>
> **Status of this document.** Implementation-grade and self-contained: every section names the exact backend endpoints, request/response shapes, TypeScript types, store fields, and UI components required. An engineer should be able to build the entire frontend from this document plus the backend source, with no other context.
>
> **Author audience.** A frontend engineer building the UI from scratch against the backend as it exists today.

---

## 0. Executive summary

The frontend must guide a wind-data analyst through an **8-stage analytical pipeline** that turns a measured wind campaign into a long-term-corrected (LTC), hub-height, ensemble-blended dataset ready for an Energy Yield Assessment (EYA):

| Stage | Goal | Primary backend capability |
|---|---|---|
| **1. Data loading** | Load measured data from files **or** import from BrightHub API | `uploads`, `datasets`, `brighthub/import` |
| **2. Reanalysis acquisition** | Download ERA5 + MERRA-2 time series at 4 surrounding nodes and extrapolate/interpolate to the measurement point | `brighthub/reanalysis/*`, `era5/*`, `interpolate` |
| **3. Measured-data exploration** | Understand recovery/availability, diurnal/annual profiles, wind rose, Weibull — to pick shear sensors & LTC strategy | `statistics`, `coverage`, `plots` |
| **4. Vertical extrapolation (measured → hub)** | Shear/interpolate measured sensors to hub height | `shear/*`, `extrapolation/hub` |
| **5. Vertical extrapolation (reanalysis → hub)** | Apply the same shear method to long-term ERA/MERRA nodes at hub height | `extrapolation/hub` (side-effect: extrapolates reanalysis nodes) |
| **6. Long-Term Correction (LTC)** | MCP between measured (short) and reanalysis (long); visualize results | `ltc/{algorithm}`, `plots` (ltc_*), `homogeneity/*` |
| **7. Clipping analysis** | Decide the representative historical window | `clipping`, `homogeneity/apply` |
| **8. Ensemble** | Blend multiple LTC outputs into one authoritative long-term series | `ensemble`, `uncertainty`, `scenarios` |

The backend exposes a **session-based HTTP API** (session id in the `X-GoKaatru-Session` header). The frontend is a single-page React app that: creates a session on first launch, persists its id in `localStorage`, drives the 8 stages in the backend's required dependency order, and offers an expert **React Flow canvas**, a **BYOK AI copilot**, and a **scenario compare** view alongside the stepper.

---

## 1. Backend model the frontend must respect

### 1.1 Session = the unit of work

Every analysis lives in a **session** (`server/state/session.py`). A session has:
- an `id` (UUID hex) and a workspace directory on disk;
- an in-memory `SessionState` holding all intermediate artifacts (parsed frames, shear tables, ERA5 nodes, LTC results, ensemble, etc.);
- a `runconfig` dict that is the **single source of truth** for user decisions and is persisted to `runconfig.json`.

**Frontend implication:** the app is single-session-per-tab. Create one on "Start", persist its id in `localStorage` under key `gokaatru-active-session-id`, and send `X-GoKaatru-Session: <id>` on every `/api/sessions/{id}/...` call. **The API client must inject this header automatically** by extracting the session id from the request path (see §2.4).

### 1.2 Order dependencies (the contract the UI must enforce)

The backend tools are **stateful and ordered**. A later tool raises `ValueError` (→ HTTP 400) if a prerequisite hasn't run. The dependency chain is:

```
parse_timeseries + parse_datamodel      (Stage 1)
        │
        ├──► cleaning (optional)        (between 1 and 3)
        │
        ├──► calculate_shear_timeseries ─► build_shear_table ─► extrapolate_to_hub_height   (Stage 4)
        │        (or roughness equivalents)                              │
        │                                                                 ├──► extrapolates reanalysis nodes too (Stage 5)
        │
        ├──► find_era5_nodes ─► extract_era5_data (×4) ─► compute_era5_wind_speed (×4)       (Stage 2)
        │                          └─► interpolate_era5_to_site ─► era5_interpolated_df
        │                                  └─► (optional) analyze_homogeneity → apply_homogeneity_cutoff
        │
        └──► run_ltc_{algorithm}(short_col=measured hub col, long_col=era5 hub col)         (Stage 6)
                    │   (×N algorithms)
                    └──► run_ensemble(measured_col)   ─► run_clipping_analysis              (Stages 8, 7)
                                 └──► calculate_uncertainty
```

The `completed_steps` array (returned by `/summary` and `/sessions/{id}`) is the canonical progress indicator. The backend emits exactly these step tokens (see `server/api/deps.py::completed_steps`):
`timeseries, datamodel, config, cleaning, shear_timeseries, shear_table, roughness_timeseries, roughness_table, era5_nodes, era5_extract, era5_interpolate, ltc, ensemble, windkit`.

**Frontend implication:** the stepper must disable/lock downstream stages until upstream `completed_steps` are present, and must offer to auto-run prerequisites.

### 1.3 The `runconfig` ↔ `WindAnalysisConfig` mapping

The frontend keeps a richer typed config (`WindAnalysisConfig` in `frontend/src/types/analysis.ts`, a zod schema) and syncs it bidirectionally with the flat backend `runconfig` via `configSync.ts` (`hydrateConfigFromRunconfig` / `serializeConfigToRunconfig`). Backend runconfig keys of interest: `project_name`, `location` `{latitude, longitude, elevation_m}`, `measurement_type`, `hub_height_m`, `sensor_mapping`, `cleaning_log`, `brighthub_uuid`, plus `shear_table_shape`/`roughness_table_shape`. **The frontend config is the editing surface; the backend runconfig is the persisted truth.** Always `saveConfig()` (PUT `/config`) before running an operation that depends on a config value (e.g. hub height).

### 1.4 Plot protocol

All visuals use one envelope (`server/schemas/common.py::PlotResult`):
```ts
{ plotly_json: string, png_base64: string | null, title: string }
```
- `plotly_json` is a JSON-stringified Plotly figure → `JSON.parse` then `Plotly.react` (or `react-plotly.js` `<Plot data={fig.data} layout={fig.layout} />`).
- `png_base64` is a graceful fallback when Kaleido is present.
- Plots are fetched via **`POST /api/sessions/{id}/plots/{plot_name}`** with a `PlotRequest` body (sensor names, algorithm, uncertainty %s). Supported `plot_name` values (24): `windrose, weibull, diurnal, scatter, timeseries, timeseries_preview, cleaning_overlay, coverage_timeline, data_coverage, scenario_comparison, era5_comparison, era5_measured_overlay, shear_table, shear_profile, monthly_means, turbulence_intensity, ltc_comparison, ltc_scatter, ltc_residuals, ltc_monthly, ltc_convergence, annual_means, uncertainty_breakdown, uncertainty_tornado`.

### 1.5 Verified response shapes (build the types from these)

These field names were confirmed by reading the backend routes — the TS interfaces in §8 must match exactly.

- **GET `/api/health`** → `{ status: string, service: string }`.
- **GET `/api/sessions/{id}`** (`SessionSummary`) → `session_id, workspace_dir, created_at, updated_at, project_name, measurement_type, hub_height_m, timeseries_loaded, datamodel_loaded, era5_nodes_loaded, era5_interpolated_loaded, ltc_algorithms: string[], completed_steps: string[]`.
- **GET `/api/sessions/{id}/summary`** (`AnalysisSummary`) → `project_name, hub_height_m, timeseries_loaded, sensor_mapping_loaded, sensor_count, avg_coverage_pct, cleaning_rules_applied, shear_table_ready, roughness_table_ready, era5_nodes_loaded, era5_data_sets_loaded, era5_interpolated_ready, ltc_algorithms_run: string[], ensemble_ready, scenario_count, coordinate: {latitude, longitude, elevation_m} | null, completed_steps: string[]`.
- **GET `/api/sessions/{id}/sensors`** → `{ sensors: SensorRow[] }` where each row = `{ name, height_m, sensor_type: "wind_speed"|"wind_direction"|"temperature"|"pressure", data_coverage_pct, record_count }`.
- **GET `/api/sessions/{id}/coverage/{sensor}`** → `{ sensor, total_records, valid_records, coverage_pct, largest_gap_minutes, gaps_over_1_hour }`.
- **GET `/api/sessions/{id}/statistics/{sensor}`** → `{ sensor_name, mean, median, std, min_value, max_value, count, coverage_pct, weibull_k, weibull_A, monthly_means: number[12], diurnal_means: number[24], percentiles: Record<string,number> }`.
- **GET `/api/sessions/{id}/results/ltc`** → `{ results: [{ algorithm, metrics, result_file: string|null, rows }] }`.
- **GET `/api/sessions/{id}/results/ensemble`** → `{ available: boolean, reference_columns: string[] }` and, when `available`, also `{ rows: number, columns: string[] }`.
- **POST `/api/sessions/{id}/clipping`** → `{ optimal_start_year, min_uncertainty, iav, analysis_data: [{ start_year, n_years, mean_speed, iav, lta_ratio, historic_uncertainty, climate_uncertainty, combined_uncertainty }] }`.
- **POST `/api/sessions/{id}/uncertainty`** → `{ total_uncertainty_pct, components: { measurement, vertical_extrapolation, mcp, future_variability }, p_factors: { p50, p75, p90, p99 }, inputs: {…} }`.
- **GET `/api/sessions/{id}/map/site`** → GeoJSON `FeatureCollection`; features are `mast` (properties `{name:"Measurement Mast", type:"mast", "marker-color":"#083434"}`) then `era5_node` (properties `{name:"ERA5 Node n", type:"era5_node", distance_km, bearing}`), geometry `Point [longitude, latitude]`.
- **LTC algorithm path values** (for `/ltc/{algorithm}`): exactly `linear_least_squares | total_least_squares | speedsort | variance_ratio | xgboost`.
- **Errors:** domain `ValueError` → HTTP 400 with `{detail: string}`; upstream failures → HTTP 502; unknown session → 404; missing/mismatched `X-GoKaatru-Session` header → 400.

---

## 2. Project scaffold (build from empty `frontend/`)

### 2.1 Target directory layout

```
frontend/
├── index.html
├── package.json
├── tsconfig.json
├── vite.config.ts
├── public/
└── src/
    ├── main.tsx                  # React 19 root mount
    ├── App.tsx                   # shell: session bootstrap + primary nav
    ├── styles.css                # brand styles (see §2.5)
    ├── vite-env.d.ts             # VITE_API_BASE_URL typing
    ├── types/
    │   └── analysis.ts           # zod config schema + §8 interfaces
    ├── lib/
    │   ├── api.ts                # HTTP client (all endpoints)
    │   ├── defaultConfig.ts      # createDefaultWindAnalysisConfig()
    │   ├── configSync.ts         # runconfig <-> WindAnalysisConfig
    │   ├── stages.ts             # STAGE_ORDER, STAGE_META, computeStageStatuses
    │   ├── workflow.ts           # React Flow graph builder (Phase F)
    │   ├── normalization.ts      # asset normalization (Phase B)
    │   ├── openapi.ts            # OpenAPI spec extraction for WindKit (Phase G)
    │   ├── scenarioCompare.ts    # compare helpers (Phase G)
    │   ├── mcpClient.ts          # MCP SDK client (Phase G)
    │   └── copilotAgent.ts       # BYOK AI agent (Phase G)
    ├── store/
    │   └── useWorkspaceStore.ts  # Zustand global store
    ├── components/
    │   ├── AppHeader.tsx
    │   ├── PhaseTabs.tsx         # primary nav (Stepper/Canvas/WindKit/Copilot/Compare)
    │   ├── HomeView.tsx          # pre-session landing
    │   ├── common/               # PlotFrame, StageHeader, SensorPicker, NodeTable, MiniMap, MetricsCard, RunButton (Phase B)
    │   ├── stages/               # the 8 stage views (Phases D–E)
    │   ├── WorkflowView.tsx      # React Flow canvas (Phase F)
    │   ├── CopilotView.tsx       # BYOK chat (Phase G)
    │   ├── CompareView.tsx       # scenario compare (Phase G)
    │   └── WindKitExplorerView.tsx # advanced tool surface (Phase G)
    └── test/
        └── *.test.ts(x)          # vitest specs
```

### 2.2 Stack & dependencies (`package.json`)

Runtime: `react@^19`, `react-dom@^19`, `zustand`, `@xyflow/react` (React Flow canvas), `plotly.js-dist-min` + `react-plotly.js`, `zod` (config schema + runtime validation), `clsx`, `@modelcontextprotocol/sdk` + `ai` + `@ai-sdk/openai` + `@ai-sdk/anthropic` (BYOK copilot).
Dev: `vite@^6`, `@vitejs/plugin-react`, `typescript@^5`, `vitest@^3`, `@testing-library/react`, `@testing-library/jest-dom`, `jsdom`, `@types/react`, `@types/react-dom`, `@types/plotly.js`.

```jsonc
{
  "name": "gokaatru-frontend",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest"
  }
  /* dependencies + devDependencies per the lists above */
}
```

### 2.3 Build configs

**`vite.config.ts`** — React plugin; `@` path alias → `src`; vitest `environment: "jsdom"`; dev server proxy `/api` → `http://127.0.0.1:8000` (so the browser talks same-origin in dev, matching the backend CORS allow-list).
**`tsconfig.json`** — `strict: true`, `verbatimModuleSyntax`, `moduleResolution: "bundler"`, `jsx: "react-jsx"`, paths `@/* → src/*`, `types: ["vitest/globals"]`.
**`vite-env.d.ts`** — declare `interface ImportMetaEnv { VITE_API_BASE_URL?: string }`.

### 2.4 API client contract (`src/lib/api.ts`) — build in full

A single `requestJson<T>(baseUrl, path, init)` core that:
- sets `Accept: application/json`;
- sets `Content-Type: application/json` for non-FormData bodies;
- **auto-injects `X-GoKaatru-Session: <id>`** by regex-matching `/api/sessions/([^/]+)/` in the path (so callers never set it manually);
- parses errors from `{detail: string}` (HTTP 4xx/5xx) into thrown `Error`s;
- returns `undefined` for HTTP 204.

Export typed wrappers for every endpoint in §9, including: `getDefaultApiBaseUrl()` (`VITE_API_BASE_URL` → `window.location.origin` → `http://127.0.0.1:8000`), `createSession`, `getSessionSummary`, `getAnalysisSummary`, `getSessionConfig`, `updateSessionConfig(id, updates[])`, `getSensors`, `getCoverage`, `getStatistics`, `fetchPlot` (POST `/plots/{name}`), `getSiteMap`, `runLtc(id, algorithm, body)`, `runEnsemble`, `runClipping`, `getClippingColumns`, `runUncertainty`, `listScenarios`/`saveScenario`/`deleteScenario`/`runScenario`, the full `workflow/*` set (`executeWorkflow`, `executeWorkflowStep`, `getWorkflowStatus`, `stopWorkflow`, `getWorkflowCapabilities`, snapshot CRUD, `forkWorkflowBranch`, `compareWorkflowBranches`), BrightHub (`login`/`logout`/`status`/`listLocations`/`getDataModel`/`importLocation`/`fetchReanalysisNodes`/`downloadReanalysis`), ERA5 (`findEra5Nodes`/`extractEra5`/`interpolateEra5`), shear/roughness/extrapolation, homogeneity, results, exports, datasets, uploads, and `chatSession`.

### 2.5 Brand palette (mirror in `src/styles.css`)

Backend plots already use: orange accent `#c86a2a`, teal `#0b7a6f` / dark teal `#083434`, neutral `#5f716a` / cream `#f3efe6`. The frontend uses these for primary actions, headers, locked/done stage states, and chart theming.

### 2.6 Shared components (built in Phase B, referenced throughout)

- `<PlotFrame plotName params />` — fetches a `PlotResult` via `fetchPlot` and renders Plotly (with loading/error/png fallback). Centralizes all chart rendering.
- `<StageHeader stage status />` — title, description, completion badge, lock state.
- `<SensorPicker kind filter />` — select speed/dir sensors from `sensors[]` in store.
- `<NodeTable nodes provider />` — render ERA5/MERRA-2 node list with distance/bearing + a mini map.
- `<MiniMap geojson />` — lightweight SVG/React-Flow minimap fed by `GET /map/site` GeoJSON (add Leaflet only if interactive maps are later required).
- `<MetricsCard metrics />` — render LTC/uncertainty metric dicts as labeled stat tiles.
- `<RunButton label busy onClick />` — standard CTA bound to `busyLabel`.

---

## 3. Global application shell

### 3.1 Layout
```
┌─ AppHeader (project name, hub height, coordinate, refresh, busy spinner) ─┐
├─ Primary nav:  [Stepper (8 stages)]  [Canvas]  [WindKit]  [Copilot]  [Compare] ─┤
├──────────────────────────────────────────────────────────────────────────────┤
│  Left: active stage panel (form + actions)                                    │
│  Right (collapsible): Results/Assets drawer (plots, metrics, activity log)    │
└──────────────────────────────────────────────────────────────────────────────┘
```
- The **Stepper** is a horizontal progress bar of 8 clickable chips. Clicking a completed stage navigates to it; a locked stage shows a tooltip "Complete *X* first".
- The **Assets drawer** shows normalized assets grouped by stage: datasets, sensor inventory, operation results, plots. Each asset is expandable.

### 3.2 The global store (`src/store/useWorkspaceStore.ts`) — build in full

A single Zustand store is the entire app state. Build it with the complete field set up front (stages populate slices of it; nothing is "added later"):

```ts
type StageStatus = "locked" | "available" | "in_progress" | "done" | "error";
type StageId = "data" | "reanalysis" | "explore" | "shear" | "reanalysis_extrapolation" | "ltc" | "clipping" | "ensemble";

interface WorkspaceStore {
  // session + bootstrap
  apiBaseUrl: string;
  session: SessionSummary | null;
  sessionStatus: "idle" | "loading" | "ready" | "error";
  sessionError: string | null;
  busyLabel: string | null;
  activeTab: "setup" | "workflow" | "windkit" | "copilot" | "compare";

  // config + summary
  config: WindAnalysisConfig;
  serverRunconfig: Record<string, unknown>;
  summary: AnalysisSummary | null;

  // shared data
  sensors: SensorRow[];
  capabilities: WorkflowDispatchCapability[];
  scenarios: ScenarioSnapshot[];

  // stage-derived state
  stageStatuses: Record<StageId, StageStatus>;
  datasets: SharedDatasetSummary[];
  datasetPreview: DatasetPreview | null;
  era5Nodes: EraNode[];
  merraNodes: EraNode[];
  era5InterpolatedSummary: { rows: number; method: string; columns: string[] } | null;
  ltcResults: LtcResultSummary[];
  ensembleSummary: { available: boolean; rows?: number; columns?: string[] };
  homogeneityReport: HomogeneityDataset[] | null;
  clippingReport: ClippingReport | null;
  uncertaintyResult: UncertaintyResult | null;
  activePlot: { plotName: string; params: PlotRequest; result: PlotResult } | null;
  activity: ActivityEntry[];

  // actions
  setActiveTab(tab): void;
  updateConfigValue(path: string, value: unknown): void;
  resetConfig(): void;
  bootstrapSession(): Promise<void>;      // POST /sessions, persist id, refreshWorkspace
  restoreSession(): Promise<void>;        // read localStorage id, GET /sessions/{id}, refreshWorkspace
  refreshWorkspace(): Promise<void>;      // summary+config+sensors+capabilities+scenarios, then computeStageStatuses
  saveConfig(): Promise<void>;            // diff vs serverRunconfig, PUT /config
  fetchPlot(plotName: string, params: PlotRequest): Promise<PlotResult>;
  refreshResults(): Promise<void>;        // GET results/ltc + results/ensemble
  invokeSessionOperation<T>(label, method, path, body?): Promise<T>;  // generic session-route caller = the runStage primitive
  setScenarioCompareSlot / saveScenario / deleteScenario / ...;
}
```

`refreshWorkspace()` fetches summary + runconfig + sensors + capabilities + scenarios in parallel, hydrates `config` from runconfig, then calls `computeStageStatuses(summary.completed_steps)` (see `lib/stages.ts`) to populate `stageStatuses`. All async actions set `busyLabel`, append to `activity[]` on success/error, and re-`refreshWorkspace()` after mutating calls. Persist the active session id in `localStorage` key `gokaatru-active-session-id`; `restoreSession()` reads it on app load.

### 3.3 Stage-status logic (`src/lib/stages.ts`) — build in Phase A

```ts
export const STAGE_ORDER: StageId[] = ["data","reanalysis","explore","shear","reanalysis_extrapolation","ltc","clipping","ensemble"];
export const STAGE_META: Record<StageId, { title: string; requiredSteps: string[] }> = {
  data:                    { title: "Data loading",             requiredSteps: ["timeseries","datamodel","config"] },
  reanalysis:              { title: "Reanalysis acquisition",   requiredSteps: ["era5_nodes","era5_extract","era5_interpolate"] },
  explore:                 { title: "Measured-data exploration",requiredSteps: ["timeseries","datamodel"] },
  shear:                   { title: "Shear → hub (measured)",   requiredSteps: ["shear_table"] },          // or roughness_table
  reanalysis_extrapolation:{ title: "Reanalysis → hub",         requiredSteps: ["era5_interpolate"] },
  ltc:                     { title: "Long-Term Correction",     requiredSteps: ["ltc"] },
  clipping:                { title: "Clipping analysis",        requiredSteps: ["ltc"] },                  // advisory
  ensemble:                { title: "Ensemble & uncertainty",   requiredSteps: ["ensemble"] },
};
export function computeStageStatuses(completedSteps: string[]): Record<StageId, StageStatus>;
// rule: "done" if all requiredSteps present; "locked" if any prerequisite STAGE is not done; else "available".
```

---

## 4. Stage specifications

Each stage below specifies: **Goal · Prerequisites · UI · Endpoint calls · State updates · Decision the analyst makes · Visuals**.

---

### Stage 1 — Data loading (`DataLoadView`)

**Goal.** Populate `session.timeseries_df` + `session.sensor_mapping`. Two entry paths: (a) upload local files, or (b) import a measurement location from BrightHub.

**Prerequisites.** A session exists (created on first launch).

**UI.**
- **Path toggle:** `Upload files` | `BrightHub import` | `Shared dataset pool`.
- **Upload path:** two dropzones — Timeseries (`.csv/.tsv/.txt/.xlsx`) and Data model (IEA Task 43 `.json`). Show parse result inline: rows, columns, start/end, timestep_minutes.
- **BrightHub path:** (i) login form (`client_id`, `client_secret`) if `brighthubStatus.authenticated === false`; (ii) location picker (`brighthubLocations[]` → pick `uuid`); (iii) import-options checkboxes (`apply_cleaning_log`, `apply_cleaning_rules`, `apply_calibration`, `apply_deadband_offset`, `apply_orientation_offset`); (iv) "Import" CTA. Show imported rows/heights.
- **Shared dataset path:** list `datasets[]` with `coverage_pct`, `date_range`, `sensor_count`; preview button → `datasetPreview`; "Load into session" CTA.
- After load: render the **sensor inventory table** (`sensors[]`: name, height_m, sensor_type, data_coverage_pct, record_count) and the **period of record** banner.
- A **"Set site & hub height"** mini-form (project name, lat, lon, elevation, measurement type, hub height) → `saveConfig()`. This sets `completed_steps: config`.

**Endpoint calls.**
| Action | Method · Path | Body |
|---|---|---|
| Upload timeseries | `POST /api/sessions/{id}/uploads/timeseries` | multipart `file` |
| Upload datamodel | `POST /api/sessions/{id}/uploads/datamodel` | multipart `file` |
| BrightHub login | `POST /api/sessions/{id}/brighthub/login` | `{client_id, client_secret}` |
| List locations | `GET /api/sessions/{id}/brighthub/locations` | — |
| Import location | `POST /api/sessions/{id}/brighthub/import` | `BrightHubImportLocationPayload` |
| List shared datasets | `GET /api/datasets` | — |
| Preview dataset | `GET /api/datasets/{dataset_id}/preview?limit=20` | — |
| Load dataset into session | `POST /api/sessions/{id}/datasets/{dataset_id}/load` | — |
| Sensors inventory | `GET /api/sessions/{id}/sensors` | — |
| Coverage per sensor | `GET /api/sessions/{id}/coverage/{sensor_name}` | — |
| Save site config | `PUT /api/sessions/{id}/config` | `{updates:[{key,value}]}` |

**State updates.** `timeseries_loaded`, `datamodel_loaded` become true; `sensors[]` populated; `completed_steps` includes `timeseries`, `datamodel`, `config`.

**Analyst decision.** Confirm the dataset is sane (coverage acceptable, period of record sufficient). Note which heights are anemometers (for Stage 4) and which is the tallest/best-covered speed sensor (default LTC short column).

**Visuals.** Sensor inventory table; optional `data_coverage` plot and `timeseries_preview` plot (call `POST /plots/data_coverage`, `POST /plots/timeseries_preview`).

**Stage unlocks:** Stage 2, Stage 3, Stage 4.

---

### Stage 2 — Reanalysis acquisition (ERA5 + MERRA-2) (`ReanalysisView`)

**Goal.** Obtain long-term reference wind series at the site from **two independent sources** (ERA5 and MERRA-2), each derived from the **4 nearest grid nodes** and spatially interpolated to the measurement coordinate.

**Prerequisites.** `config` set (lat/lon) — needed for node search and interpolation anchor.

> **Two implementation paths exist in the backend; the UI should offer both and default to the one with credentials.**
> - **BrightHub path** (`/brighthub/reanalysis/nodes` + `/brighthub/reanalysis/download`): returns **both** ERA5 and MERRA-2 nodes, downloads per-node series, supports `source: "brighthub" | "earthdatahub"`. *This is the only path that yields MERRA-2.*
> - **Direct ERA5 path** (`/era5/nodes` + `/era5/extract` + `/era5/interpolate`): pulls ERA5 from the EarthDataHub Zarr store using a PAT (`EARTHDATAHUB_PAT`). *ERA5 only, no MERRA-2.*

**UI.**
- Show site coordinate (read-only, from config).
- **Provider selector:** "BrightHub (ERA5 + MERRA-2)" vs "Direct ERA5 (EarthDataHub)". If BrightHub not authenticated, prompt to login (link back to Stage 1 BrightHub login) or enter EarthDataHub PAT in a settings field.
- **"Find surrounding nodes"** button → renders two node tables (ERA5: 4 rows, MERRA-2: 4 rows) with `distance_km`, `bearing`, and a **mini site map** (`GET /api/sessions/{id}/map/site` returns GeoJSON with the mast + ERA5 nodes). Render Mast marker `#083434` and node markers labelled "ERA5 Node 1..4".
- **Date range** inputs (default `2000-01-01 → today`, or the measured period extended to full ERA5 history). Warn if range > ~25 years (performance).
- **"Download all nodes"** button → downloads all ERA5 nodes (and MERRA-2 nodes on the BrightHub path). Show per-node progress (`rows` returned per item). This is a long operation — show a non-blocking progress list.
- **"Compute wind speed + interpolate to site"** button → for ERA5: runs `compute_era5_wind_speed` per node then `interpolate_era5_to_site`. On the BrightHub path, wind-speed derivation + column normalization happens during download; interpolation must still be triggered (`/era5/interpolate`) to produce `era5_interpolated_df`. Show resulting `rows`, interpolation `method` (`linear`/`idw`), and columns.
- **Homogeneity gate (optional but recommended):** "Run Pettitt homogeneity test" → `POST /homogeneity/analyze` with `method: "annual"|"monthly"`. Render per-node `recommended_start_year`, `pettitt_p_value`, `trend_per_year`. If any node recommends trimming, show an "Apply cutoff year" control → `POST /homogeneity/apply {cutoff_year}` which trims `era5_interpolated_df`.

**Endpoint calls.**
| Action | Method · Path | Body |
|---|---|---|
| BrightHub find nodes | `POST /api/sessions/{id}/brighthub/reanalysis/nodes` | `{latitude, longitude}` |
| BrightHub download | `POST /api/sessions/{id}/brighthub/reanalysis/download` | `{dataset:"ERA5"|"MERRA-2", source, nodes}` |
| Direct ERA5 find nodes | `POST /api/sessions/{id}/era5/nodes` | `{latitude, longitude}` |
| Direct ERA5 extract (×4) | `POST /api/sessions/{id}/era5/extract` | `{latitude, longitude, start_date, end_date}` |
| ERA5 interpolate to site | `POST /api/sessions/{id}/era5/interpolate` | — |
| Site map GeoJSON | `GET /api/sessions/{id}/map/site` | — |
| Homogeneity analyze | `POST /api/sessions/{id}/homogeneity/analyze` | `{method}` |
| Homogeneity apply | `POST /api/sessions/{id}/homogeneity/apply` | `{cutoff_year}` |

**Backend notes to honor in UI.**
- ERA5 extract has retry logic and can raise `Era5UpstreamError` (→ 502) on transient failures — surface a **"Retry"** button, and suggest narrowing the date range.
- ERA5 wind speed is `Spd_100m = sqrt(u100²+v100²)`, direction meteorological. MERRA-2 columns are renamed via `_BH_MERRA_COLUMN_MAP`. Both must be present before LTC.
- `interpolate_era5_to_site` requires **4 nodes each having `Spd_100m`/`Dir_100m`**; direction is interpolated in vector space (u/v) to handle the wrap-around correctly.

**State updates.** `era5_nodes_loaded`, `era5_extract`, `era5_interpolate` added to `completed_steps`. Store `era5Nodes`, `merraNodes`, `era5InterpolatedSummary`.

**Analyst decision.** Which reference source(s) to carry forward to LTC (ERA5 only, MERRA-2 only, or both → compare). Whether to apply a homogeneity cutoff.

**Visuals.** `era5_comparison` (node-vs-node or node-vs-site), `era5_measured_overlay` (reference vs measured concurrent period). Mini site map.

**Stage unlocks:** Stage 5, Stage 6.

---

### Stage 3 — Measured-data exploration (`ExploreView`)

**Goal.** Let the analyst understand the measured dataset deeply enough to **choose shear sensors, decide hub-height strategy, and pick the LTC short column.** This is the analytics dashboard stage — predominantly visuals + stats, light on state mutation.

**Prerequisites.** `timeseries` + `datamodel` loaded.

**UI — a grid of analyst-facing panels.** Provide a global **sensor selector** (default = best-covered speed sensor). Then render:

1. **Data quality panel**
   - **Recovery rate / availability:** per-sensor `data_coverage_pct` from `sensors[]`; call `GET /coverage/{sensor}` for gap stats (`largest_gap_minutes`, `gaps_over_1_hour`).
   - **Coverage timeline** plot (`POST /plots/coverage_timeline`) and **cleaning overlay** (`POST /plots/cleaning_overlay {sensor_name}`) if cleaning was applied in Stage 1/interim.

2. **Frequency distribution**
   - **Weibull fit:** `GET /statistics/{sensor}` returns `weibull_k`, `weibull_A`, mean, median, std, percentiles, monthly_means[12], diurnal_means[24]. Plot via `POST /plots/weibull {sensor_name}`.

3. **Directional**
   - **Wind rose:** `POST /plots/windrose {speed_sensor, direction_sensor}` (16 sectors, stacked by speed bins 0-5/5-10/10-15/15-20/20+).

4. **Temporal profiles**
   - **Diurnal:** `POST /plots/diurnal {sensor_names}` (hour-of-day means).
   - **Monthly/annual:** `POST /plots/monthly_means {sensor_names}`.

5. **Shear-relevant panels (informs Stage 4)**
   - **Shear profile** plot (`POST /plots/shear_profile`) — speed vs height across all anemometers, to visualize whether hub height sits between sensors (→ interpolation) or beyond the top sensor (→ extrapolation).
   - **Turbulence Intensity** (`POST /plots/turbulence_intensity {sensor_a: speed, sensor_b: sd}`) — IEC representative TI; relevant for turbine selection and for trusting anemometers.

6. **Scatter / correlation** (optional)
   - `POST /plots/scatter {sensor_a, sensor_b}` + `compute_scatter_stats` metrics (R², RMSE, slope) — useful to compare redundant anemometers.

**Endpoint calls.**
| Action | Method · Path | Body |
|---|---|---|
| Sensor statistics | `GET /api/sessions/{id}/statistics/{sensor_name}` | — |
| Coverage detail | `GET /api/sessions/{id}/coverage/{sensor_name}` | — |
| Any visual | `POST /api/sessions/{id}/plots/{plot_name}` | `PlotRequest` |

**State updates.** None mandatory (read-only stage). But the analyst's choices here should write into config: `shear.speedSensorPair`, `shear.directionSensor`, `ltc.shortColumn`. Provide a **"Lock choices"** action that calls `saveConfig()` and marks the stage done.

**Analyst decision (explicit capture in UI):**
- Which **≥2 anemometers** to use for shear (must have `_Nm` suffixes or be mapped heights).
- Whether hub height is **between sensors** (interpolation) or **above the top sensor** (extrapolation) — the backend auto-decides per-timestamp, but surface `method_counts` later so the analyst can sanity-check.
- The **primary measured speed column** for LTC (usually the hub-height column produced in Stage 4, or the tallest good anemometer pre-extrapolation).

**Stage unlocks:** reinforces Stage 4 readiness.

---

### Stage 4 — Vertical extrapolation: measured → hub (`ShearExtrapolationView`)

**Goal.** Produce `Spd_<hub>m_hub` — the measured wind speed extrapolated/interpolated to hub height — using either the **power-law (α)** or **log-law (roughness z₀)** method.

**Prerequisites.** `timeseries`/`datamodel`; shear sensors chosen (Stage 3); hub height set (Stage 1).

**UI.**
- **Method toggle:** `Power law (shear α)` | `Log law (roughness z₀)`. 
- **Sensor picker** for the **≥2 height sensors** (prefilled from `shear.speedSensorPair`). Show the height list ascending. Backend accepts `height_sensors` as a JSON string: either `{"80":"Spd_80m","120":"Spd_120m"}` or `["Spd_80m","Spd_120m"]`.
- **Aggregation** selector: `mean | median | momm` (MoMM = Mean of Monthly Means, Windographer-style).
- **Direction sensor** (optional) for **sector shear tables** (`build_sector_shear_tables`) — useful when shear is strongly directional.
- **Hub height** input (prefilled from config; default 120 m).
- **"Compute shear timeseries"** → then **"Build lookup table"** (12×24 month×hour). Render the table as a heatmap (`POST /plots/shear_table {table_type:"shear"|"roughness"}`).
- **"Extrapolate to hub height"** → calls `/extrapolation/hub {hub_height_m, shear_model}`. Display the returned `method_counts: {direct, interpolated, extrapolated}` prominently — this tells the analyst how much of the series was measured vs inferred. The new column `Spd_<hub>m_hub` is appended to `timeseries_df` and appears in the sensor inventory.
- **Side effect to highlight:** the same call also extrapolates **all ERA5/MERRA-2/interpolated reanalysis nodes** to hub height (`_extrapolate_all_reanalysis_nodes`), returning `reanalysis: {extrapolated_nodes, skipped_nodes, ...}`. This means **Stage 5 is largely completed as a by-product of Stage 4.** Surface that result here and mark Stage 5 ready.

**Endpoint calls.**
| Action | Method · Path | Body |
|---|---|---|
| Shear timeseries | `POST /api/sessions/{id}/shear/calculate` | `{height_sensors}` |
| Shear table | `POST /api/sessions/{id}/shear/table` | `{aggregation}` |
| Roughness timeseries | `POST /api/sessions/{id}/roughness/calculate` | `{height_sensors}` |
| Roughness table | `POST /api/sessions/{id}/roughness/table` | `{aggregation}` |
| Extrapolate to hub (measured + reanalysis) | `POST /api/sessions/{id}/extrapolation/hub` | `{hub_height_m, shear_model}` |
| Shear table plot | `POST /api/sessions/{id}/plots/shear_table` | `{table_type}` |
| Shear profile plot | `POST /api/sessions/{id}/plots/shear_profile` | — |

**Backend notes.**
- `shear_model` must be `"power_law"` (needs `shear_table`) or `"log_law"` (needs `roughness_table`).
- Extrapolation logic per timestamp: **direct** if hub==a measured height; **interpolated** (log-linear in ln(z)) if hub is between two measured heights; **extrapolated** via the 12×24 lookup using the nearest measured height as reference.
- Reanalysis extrapolation is power-law only, using `Spd_100m` as the reference column (default `reference_height_m=100`).

**State updates.** `shear_timeseries`, `shear_table` (or `roughness_*`) added to `completed_steps`. `config.shear.*` updated. New hub column available.

**Analyst decision.** Confirm `method_counts` is acceptable (e.g. not >50% extrapolated for a bankable EYA — flag in UI if so). Confirm the hub column to use downstream.

**Stage unlocks:** Stage 5 (often auto-done), Stage 6.

---

### Stage 5 — Vertical extrapolation: reanalysis → hub (`ReanalysisExtrapolationView`)

**Goal.** Ensure the long-term ERA5/MERRA-2 reference series exist at **hub height**, using the **same shear method chosen in Stage 4** (consistency requirement for LTC).

**Prerequisites.** Stages 2 & 4.

**UI.**
- This stage is mostly **confirmation + visualization** because Stage 4's `/extrapolation/hub` call already extrapolated all reanalysis nodes. Show the side-effect result: which nodes were extrapolated vs skipped.
- If reanalysis nodes were added/changed since Stage 4 (e.g. MERRA-2 downloaded later), provide an explicit **"Re-extrapolate reanalysis to hub"** action. The backend has a dedicated tool `extrapolate_reanalysis_to_hub(hub_height_m, reference_height_m=100)` that adds the hub column to `era5_interpolated_df` (power-law only).
- Show a table: each reanalysis source (ERA5-interpolated, each ERA5 node, each MERRA-2 node) → hub column name, rows, mean speed.
- Visual: overlay measured-hub vs ERA5-hub on the concurrent period (`POST /plots/era5_measured_overlay`).

**Endpoint calls.**
| Action | Method · Path | Body |
|---|---|---|
| Re-extrapolate interpolated ERA5 to hub | `POST /api/sessions/{id}/extrapolation/hub` (re-run) | `{hub_height_m, shear_model}` |
| ERA5 vs measured overlay plot | `POST /api/sessions/{id}/plots/era5_measured_overlay` | `PlotRequest` |
| ERA5 comparison plot | `POST /api/sessions/{id}/plots/era5_comparison` | `PlotRequest` |

**State updates.** `era5_interpolate` confirmed; reanalysis hub columns present in `era5_interpolated_df` and node frames.

**Analyst decision.** Confirm the reference column to use as the LTC **long column** (usually `Spd_<hub>m_hub` on the interpolated ERA5 series, or `Spd_100m` if not extrapolated). For MERRA-2, the analogous column.

**Stage unlocks:** Stage 6.

---

### Stage 6 — Long-Term Correction (`LtcView`)

**Goal.** Run Measure-Correlate-Predict (MCP) between the **measured hub-height series (short)** and the **long-term reanalysis hub-height series (long)**, for one or more algorithms, and visualize the fits.

**Prerequisites.** Stages 4 & 5 (both hub columns exist).

**Algorithms available** (`POST /api/sessions/{id}/ltc/{algorithm}`):
| `algorithm` | Method | Needs direction? | Min concurrent |
|---|---|---|---|
| `linear_least_squares` | Robust Huber IRLS | no | 10 |
| `total_least_squares` | Orthogonal regression | no | 10 |
| `speedsort` | TLS above threshold + dog-leg below | no | 10 |
| `variance_ratio` | Mean + std-scaling | no | 10 |
| `xgboost` | Gradient-boosted trees w/ directional+temporal features | **yes** (`long_dir_col`, optionally `short_dir_col`) | **100** |

**UI.**
- **Short column** picker (default = `Spd_<hub>m_hub`).
- **Long column** picker (default = ERA5 hub column from Stage 5).
- **Direction columns** (for xgboost): `short_dir_col`, `long_dir_col` pickers.
- **Algorithm multi-select** with chips; each chip shows a one-line description. Default selection: `speedsort` + `total_least_squares` (good baseline pair for ensembling).
- **"Run selected LTC algorithms"** → fires one `POST /ltc/{algorithm}` per selection (parallelizable). Each returns `metrics` and writes a `corrected_wind_speed` long-term series to `state.ltc_results[algorithm]`.
- **Results table/cards:** per algorithm show `r_squared`, `rmse`, `mae`, `mbe`, `concurrent_points`, `total_corrected_points` (and algorithm-specific: slope/intercept, threshold/dog_leg_slope, variance_ratio, feature_importance for xgboost). Color-code R² (green ≥0.8, amber 0.6–0.8, red <0.6).
- **Visuals (per algorithm & comparative):**
  - `POST /plots/ltc_comparison` — all algorithms' long-term means side by side.
  - `POST /plots/ltc_scatter {algorithm}` — short vs long with fit line.
  - `POST /plots/ltc_residuals {algorithm}` — residual diagnostics.
  - `POST /plots/ltc_monthly {algorithm}` — monthly measured vs corrected.
  - `POST /plots/ltc_convergence {algorithm}` — rolling long-term mean convergence (does the correction stabilize?).
  - `POST /plots/annual_means` — annual means of corrected series.

**Endpoint calls.**
| Action | Method · Path | Body |
|---|---|---|
| Run one LTC | `POST /api/sessions/{id}/ltc/{algorithm}` | `{short_col, long_col, short_dir_col, long_dir_col}` |
| List LTC results | `GET /api/sessions/{id}/results/ltc` | — |
| LTC plots | `POST /api/sessions/{id}/plots/{ltc_*}` | `{algorithm, sensor_a, sensor_b}` |
| Export one LTC | `GET /api/sessions/{id}/exports/ltc/{algorithm}` | — (CSV download) |

**Backend notes.**
- All deterministic algorithms share response shape `{status, algorithm, metrics, result_file}`; xgboost adds `feature_importance`, `train_error`, `val_error`, `best_iteration`.
- Measured data is resampled to hourly (≥50% coverage/hour) before fitting; the concurrent join requires ≥10 points (≥100 for xgboost).
- `corrected_wind_speed` is clipped at 0.

**State updates.** `ltc` added to `completed_steps`; `ltcResults[]` populated; `config.ltc.algorithms/shortColumn/longColumn` set.

**Analyst decision.** Which algorithms produced trustworthy fits (R², low bias, stable convergence) → these feed Stage 8's ensemble. Discard outliers from the ensemble.

**Stage unlocks:** Stage 7, Stage 8.

---

### Stage 7 — Clipping analysis (`ClippingView`)

**Goal.** Decide the **representative historical window** (start year → present) that minimizes the combined historic + climate uncertainty, and apply it to the long-term series used for energy estimation.

**Prerequisites.** At least one LTC result (or the ensemble) exists — clipping reads a corrected long-term series.

> **Note on ordering.** Clipping can run on a single LTC result or on the ensemble. The user's flow places it at Stage 7 (before ensemble at Stage 8). Practically, run clipping on the best single LTC result (or, if the ensemble is already computed in Stage 8, re-run clipping on it). The UI should allow choosing the `source` (`ensemble` or any LTC algorithm key) and the `speed_col`.

**UI.**
- **Source** selector: `ensemble` (if available) or an LTC algorithm; then **speed column** from `GET /clipping/columns?source=...` (returns numeric columns excluding `Timestamp` — e.g. `corrected_wind_speed`, `Ensemble_Speed`).
- **"Run clipping analysis"** → `POST /clipping {speed_col, source}`. Requires **>5 annual means**.
- **Results:**
  - Headline: `optimal_start_year`, `min_uncertainty`, full-series `iav`.
  - **U-curve chart:** plot `analysis_data[]` (per candidate start year) — `historic_uncertainty`, `climate_uncertainty`, `combined_uncertainty` vs `start_year`. The minimum marks the recommended start.
  - Table: `start_year, n_years, mean_speed, iav, lta_ratio, *_uncertainty`.
- **Decision capture:** an editable "Use start year" field (defaults to `optimal_start_year`) → this trims the long-term series conceptually for the EYA. (Trimming ERA5 homogeneity is a separate, already-applied action in Stage 2; here the "representative period" is an EYA reporting choice.)
- Optionally tie back to **homogeneity** (Stage 2): if a Pettitt change-point was found, recommend the later of the homogeneity cutoff and the clipping optimum.

**Endpoint calls.**
| Action | Method · Path | Body |
|---|---|---|
| Clipping columns | `GET /api/sessions/{id}/clipping/columns?source=` | — |
| Run clipping | `POST /api/sessions/{id}/clipping` | `{speed_col, source}` |

**Backend notes.**
- Clipping is **advisory** — it does not mutate session state. The "representative years" = `[optimal_start_year → end of record]`.
- Methodology minimizes `sqrt(historic² + climate²)` where historic uncertainty shrinks with more years and climate uncertainty grows when the sub-period mean deviates from the long-term mean.

**State updates.** `clippingReport` stored; no `completed_steps` change (advisory).

**Analyst decision.** The representative start year for the EYA, balancing uncertainty minimization against data availability.

**Stage unlocks:** informs Stage 8 reporting.

---

### Stage 8 — Ensemble & uncertainty (`EnsembleView`)

**Goal.** Blend the trusted LTC algorithm outputs into one authoritative long-term series, compute the total EYA uncertainty and P-factors, and **save a named scenario** for comparison.

**Prerequisites.** ≥2 LTC results in `state.ltc_results`.

**UI.**
- **Measured column** picker (`measured_col`) — used for overlap scoring/bias correction (default = hub column).
- **"Run ensemble"** → `POST /ensemble {measured_col}`. Methodology: inverse-RMSE weighting with per-component bias correction; output `Ensemble_Speed` plus all component columns.
- **Weights visualization:** bar/pie of `weights[algorithm]`. 
- **Fit metrics:** ensemble `rmse`, `r2`, `bias` vs measured.
- **Long-term series plot:** overlay all component `corrected_wind_speed` + `Ensemble_Speed` (`POST /plots/annual_means`, `POST /plots/timeseries`).
- **Uncertainty calculator** (collapsible form, prefilled from config):
  - `measurement_uncertainty_pct`, `measurement_height_m`, `hub_height_m`, `shear_method` (`calculate_shear` | `simple_power_law` | other), `mcp_r_squared` (from the primary LTC), `concurrent_hours`, `algorithm` (default `speedsort`), `iav_pct` (default 6), `shear_std`, `is_interpolation` (true if hub height was interpolated, not extrapolated).
  - **"Calculate uncertainty"** → `POST /uncertainty`. Show components (measurement / vertical_extrapolation / mcp / future_variability), `total_uncertainty_pct`, and **P-factors** (`p50=1.0`, `p75`, `p90`, `p99`) as a tornado chart (`POST /plots/uncertainty_tornado`) and breakdown bar (`POST /plots/uncertainty_breakdown`).
- **Scenario management:**
  - **"Save scenario"** → `POST /scenarios {name}` (captures current config + outputs; requires uncertainty already run).
  - **One-shot:** `POST /scenarios/run {name, runconfig, ltc_algorithms, uncertainty}` imports overrides → runs LTC → ensemble → uncertainty → saves snapshot. Use this for "what-if" branches.
  - List saved scenarios (`GET /scenarios`); delete (`DELETE /scenarios/{index}`).
- **Exports:** buttons for `GET /exports/timeseries`, `/exports/ensemble`, `/exports/runconfig`.

**Endpoint calls.**
| Action | Method · Path | Body |
|---|---|---|
| Run ensemble | `POST /api/sessions/{id}/ensemble` | `{measured_col}` |
| Ensemble summary | `GET /api/sessions/{id}/results/ensemble` | — |
| Uncertainty | `POST /api/sessions/{id}/uncertainty` | `CalculateUncertaintyRequest` |
| Save scenario | `POST /api/sessions/{id}/scenarios` | `{name}` |
| Run scenario | `POST /api/sessions/{id}/scenarios/run` | `RunScenarioRequest` |
| List/delete scenarios | `GET` / `DELETE /api/sessions/{id}/scenarios[/{index}]` | — |
| Export ensemble | `GET /api/sessions/{id}/exports/ensemble` | — (CSV) |
| Export runconfig | `GET /api/sessions/{id}/exports/runconfig` | — (JSON) |
| Uncertainty plots | `POST /api/sessions/{id}/plots/{uncertainty_*}` | pct fields |

**Backend notes.**
- Ensemble requires ≥2 LTC results; weights = `1/rmse` normalized; zero-RMSE components get weight 0.
- Uncertainty total = `sqrt(u_meas² + u_vert² + u_mcp² + u_future²)`; `u_future = iav_pct/sqrt(20)`. P-factors are multiplicative energy exceedance factors.
- `saveScenario` requires `latest_uncertainty` to be set (run uncertainty first).

**State updates.** `ensemble` added to `completed_steps`; `ensembleSummary`, `uncertaintyResult`, `scenarios[]` updated.

**Analyst decision.** Final long-term mean (from ensemble), total uncertainty, P90/P75 energy factors. This is the headline EYA result.

---

## 5. Canvas view (`WorkflowView`)

Build `lib/workflow.ts::createWorkflowGraph` to emit the full pipeline as a DAG so the expert user can see and re-run any node. Proposed nodes (left→right, top→bottom):

```
dataset ─► cleaning ─► explore(stats) ─► shear ─► extrapolate_hub ─► ltc ─► ensemble ─► uncertainty
   │                         │
   └─► era5_nodes ─► era5_extract ─► era5_interpolate ─► homogeneity ─┐
   └─► merra_download ─────────────────────────────────────────────────┤
                                                                       ▼
                                                                 clipping ◄── ensemble
```

Each node's `templateId` must match a backend capability (from `GET /workflow/capabilities`) or `"select-dataset"`. Each node's `paramsJson` is built from the corresponding config slice. Wire the canvas to the store's `executeWorkflow(mode)` / `executeWorkflowStep()` actions, which POST the graph to `/workflow/execute[/step]`. For long runs, use the **SSE stream** endpoint `POST /workflow/execute/stream` for live node-status updates on the canvas.

**Capability → template_id reference** (resolved at runtime; the executor binds the session and dispatches by function name):
`select-dataset`, `parse_timeseries`, `parse_datamodel`, `list_sensors`, `apply_cleaning_rule`, `undo_cleaning_rule`, `calculate_shear_timeseries`, `build_shear_table`, `calculate_roughness_timeseries`, `build_roughness_table`, `extrapolate_to_hub_height`, `extrapolate_reanalysis_to_hub`, `find_era5_nodes`, `extract_era5_data`, `compute_era5_wind_speed`, `interpolate_era5_to_site`, `analyze_homogeneity`, `apply_homogeneity_cutoff`, `run_ltc_linear_least_squares`, `run_ltc_total_least_squares`, `run_ltc_speedsort`, `run_ltc_variance_ratio`, `run_ltc_xgboost`, `run_ensemble`, `run_clipping_analysis`, `calculate_uncertainty`, `brighthub_*`, `windkit_*`, plus all `plot_*`/visualization helpers.

> **Parameter coercion caveat:** the executor's `_build_kwargs` resolves params by name **or alias** (e.g. `file_path`←`path`, `height_sensors`←`sensors`, `sensor_name`←`sensor`, `nodes_json`←`nodes`) and JSON-serializes dict/list values for `str` params. So when building `paramsJson` for the canvas, use either the canonical param name or a known alias, and serialize complex params as the backend tool expects (e.g. `height_sensors` as a JSON string, `params` for cleaning as a JSON string).

---

## 6. Copilot integration (`CopilotView`)

The backend `POST /api/sessions/{id}/chat` endpoint is BYOK, OpenAI-compatible, and runs server-side tool execution against the same MCP tool registry (up to 12 tool rounds). Build the copilot to drive it, and:
- Feed the workspace context (`stageStatuses`, `ltcResults`, `clippingReport`, `uncertaintyResult`) to the agent so it can answer "which stages are done?" and "what's my P90?".
- Surface the streamed `tool_calls_executed` as inline chips ("Running speedsort…").

---

## 7. Compare view (`CompareView`)

Target `POST /api/sessions/{id}/workflow/compare` and `POST /workflow/branches/fork`. Ensure the **scenario slots** (`baseline/run2/run3`) map to saved scenarios (Stage 8) so analysts can diff two LTC/ensemble strategies. The compare response includes metrics (LT mean, P50/75/90/99, uncertainties), config diffs, and Plotly figures (weibull, windrose[], ltc_scatter, uncertainty_tornado) — render via `<PlotFrame>`.

---

## 8. Data model additions (`types/analysis.ts`)

Define the `WindAnalysisConfig` zod schema (the typed editing surface) plus these interfaces mirroring backend responses (field names from §1.5):

```ts
export type StageId = "data"|"reanalysis"|"explore"|"shear"|"reanalysis_extrapolation"|"ltc"|"clipping"|"ensemble";

export interface SensorRow { name: string; height_m: number; sensor_type: string; data_coverage_pct: number; record_count: number; }

export interface CoverageDetail { sensor: string; total_records: number; valid_records: number; coverage_pct: number; largest_gap_minutes: number; gaps_over_1_hour: number; }

export interface SensorStatistics { sensor_name: string; mean: number; median: number; std: number; min_value: number; max_value: number; count: number; coverage_pct: number; weibull_k: number; weibull_A: number; monthly_means: number[]; diurnal_means: number[]; percentiles: Record<string, number>; }

export interface EraNode { latitude: number; longitude: number; distance_km?: number; bearing?: string; }

export interface HomogeneityDataset { name: string; recommended_start_year: number; pettitt_p_value: number; trend_per_year: number; }

export interface LtcMetrics { algorithm: string; r_squared?: number; rmse?: number; mae?: number; mbe?: number; slope?: number; intercept?: number; threshold?: number; dog_leg_slope?: number; variance_ratio?: number; correlation?: number; concurrent_points?: number; total_corrected_points?: number; feature_importance?: Record<string, number>; [k: string]: unknown; }
export interface LtcResultSummary { algorithm: string; metrics: LtcMetrics; result_file: string | null; rows: number; }

export interface ClippingRow { start_year: number; n_years: number; mean_speed: number; iav: number; lta_ratio: number; historic_uncertainty: number; climate_uncertainty: number; combined_uncertainty: number; }
export interface ClippingReport { optimal_start_year: number; min_uncertainty: number; iav: number; analysis_data: ClippingRow[]; }

export interface UncertaintyResult { total_uncertainty_pct: number; components: { measurement: number; vertical_extrapolation: number; mcp: number; future_variability: number }; p_factors: { p50: number; p75: number; p90: number; p99: number }; inputs: Record<string, unknown>; }

export interface PlotResult { plotly_json: string; png_base64: string | null; title: string; }
export type PlotName = "windrose"|"weibull"|"diurnal"|"scatter"|"timeseries"|"timeseries_preview"|"cleaning_overlay"|"coverage_timeline"|"data_coverage"|"scenario_comparison"|"era5_comparison"|"era5_measured_overlay"|"shear_table"|"shear_profile"|"monthly_means"|"turbulence_intensity"|"ltc_comparison"|"ltc_scatter"|"ltc_residuals"|"ltc_monthly"|"ltc_convergence"|"annual_means"|"uncertainty_breakdown"|"uncertainty_tornado";
export interface PlotRequest { speed_sensor?: string; sensor_name?: string; sensor_names?: string; direction_sensor?: string; sensor_a?: string; sensor_b?: string; algorithm?: string; table_type?: string; total_pct?: number; measurement_pct?: number; vertical_pct?: number; mcp_pct?: number; future_pct?: number; }
```

---

## 9. Endpoint reference (consolidated)

All session-scoped routes require header `X-GoKaatru-Session: <session_id>` matching the path id. Errors: `ValueError`→400, upstream→502.

### Sessions & config
- `POST /api/sessions` → create
- `GET /api/sessions/{id}` / `POST /api/sessions/{id}/reset` / `DELETE /api/sessions/{id}`
- `GET|PUT /api/sessions/{id}/config` (PUT body `{updates:[{key,value}]}`)
- `GET /api/sessions/{id}/summary` (analysis summary + `completed_steps`)

### Data (Stage 1)
- `POST /api/sessions/{id}/uploads/{timeseries|datamodel}` (multipart `file`)
- `GET /api/sessions/{id}/sensors` · `GET /api/sessions/{id}/coverage/{sensor_name}`
- `GET /api/datasets` · `GET /api/datasets/{id}/preview?limit=` · `POST /api/datasets` (multipart) · `POST /api/sessions/{id}/datasets/{id}/load`

### BrightHub (Stage 1 & 2)
- `POST .../brighthub/login {client_id, client_secret}` · `POST .../brighthub/logout` · `GET .../brighthub/status`
- `GET .../brighthub/locations` · `GET .../brighthub/locations/{uuid}/datamodel`
- `POST .../brighthub/import {uuid, name?, latitude_ddeg?, longitude_ddeg?, apply_*}`
- `POST .../brighthub/reanalysis/nodes {latitude, longitude}` → `{era5_nodes[], merra2_nodes[]}`
- `POST .../brighthub/reanalysis/download {dataset:"ERA5"|"MERRA-2", source:"brighthub"|"earthdatahub", nodes[]}`

### Direct ERA5 (Stage 2)
- `POST .../era5/nodes {latitude, longitude}` · `POST .../era5/extract {latitude, longitude, start_date, end_date}` · `POST .../era5/interpolate`

### Shear & extrapolation (Stages 4 & 5)
- `POST .../shear/calculate {height_sensors}` · `POST .../shear/table {aggregation}`
- `POST .../roughness/calculate {height_sensors}` · `POST .../roughness/table {aggregation}`
- `POST .../extrapolation/hub {hub_height_m, shear_model}` (measured + all reanalysis nodes)

### Statistics & plots (Stages 3, 6, 8)
- `GET .../statistics/{sensor_name}`
- `POST .../plots/{plot_name}` body `PlotRequest` → `PlotResult`
- `GET .../map/site` (GeoJSON)

### Homogeneity (Stage 2)
- `POST .../homogeneity/analyze {method:"annual"|"monthly"}` · `POST .../homogeneity/apply {cutoff_year}`

### LTC, ensemble, clipping, uncertainty (Stages 6–8)
- `POST .../ltc/{algorithm} {short_col, long_col, short_dir_col, long_dir_col}`
- `POST .../ensemble {measured_col}`
- `POST .../clipping {speed_col, source}` · `GET .../clipping/columns?source=`
- `POST .../uncertainty` (`CalculateUncertaintyRequest`)
- `GET .../results/ltc` · `GET .../results/ensemble`

### Scenarios, workflow, exports
- `POST .../scenarios {name}` · `POST .../scenarios/run {name, runconfig, ltc_algorithms, uncertainty}` · `GET .../scenarios` · `DELETE .../scenarios/{index}`
- `POST .../workflow/execute[/step|/stream]` · `GET .../workflow/status` · `POST .../workflow/stop` · `GET .../workflow/capabilities`
- snapshots: `GET .../workflow/snapshots` · `PUT/GET .../workflow/snapshots/{name}`
- `POST .../workflow/branches/fork {name?, from_node_id?}` · `POST .../workflow/compare {branch_session_ids[]}`
- exports: `GET .../exports/{timeseries|ensemble|runconfig|ltc/{algorithm}}`

---

## 10. Implementation phases (file-level build plan)

Each phase lists the files to create, a one-line scope per file, and a verification gate. Phases are cumulative; later phases import from earlier ones.

### Phase A — Runnable foundation (types, API client, store)
- `package.json`, `vite.config.ts`, `tsconfig.json`, `index.html`, `src/vite-env.d.ts`, `src/main.tsx` — scaffold a bootable Vite+React 19+TS app (§2.2–2.3).
- `src/types/analysis.ts` — the `WindAnalysisConfig` zod schema **+ all §8 interfaces** (`StageId`, `SensorRow`, `CoverageDetail`, `SensorStatistics`, `EraNode`, `HomogeneityDataset`, `LtcMetrics`, `LtcResultSummary`, `ClippingRow`, `ClippingReport`, `UncertaintyResult`, `PlotResult`, `PlotName`, `PlotRequest`). Field names from §1.5.
- `src/lib/api.ts` — full HTTP client per §2.4: `requestJson` core with auto `X-GoKaatru-Session` header injection, `getDefaultApiBaseUrl`, and a typed wrapper for every endpoint in §9.
- `src/lib/defaultConfig.ts` — `createDefaultWindAnalysisConfig()` (zod-parsed defaults; mirror §8's config schema).
- `src/lib/configSync.ts` — `hydrateConfigFromRunconfig`, `serializeConfigToRunconfig`, `setConfigValue` (dotted-path), `buildRunconfigUpdates` (diff against server runconfig).
- `src/lib/stages.ts` — `STAGE_ORDER`, `STAGE_META`, `computeStageStatuses` (per §3.3).
- `src/store/useWorkspaceStore.ts` — the complete Zustand store (§3.2): all state fields + actions (`bootstrapSession`, `restoreSession`, `refreshWorkspace`, `saveConfig`, `fetchPlot`, `refreshResults`, `invokeSessionOperation`, scenario/workflow actions, `localStorage` persistence of session id).
- `src/App.tsx` — minimal bootable shell: if no session → "Start workspace" button (`bootstrapSession`); else header (project name, hub height, completed steps) + activity log. **No stage views yet.**
- `src/styles.css` — base layout + brand palette (§2.5).
- `src/test/stages.test.ts` — vitest: `computeStageStatuses` correctness (locked/available/done transitions across the dependency chain) + default-config validation.
- **Gate:** `npm install` ✓ · `npm run test` green ✓ · `npm run build` (`tsc --noEmit && vite build`) green ✓ · `npm run dev` against a running backend creates a session and renders summary/completed_steps (manual smoke).

### Phase B — Shared components
- `src/components/common/PlotFrame.tsx` — fetches `PlotResult` via `store.fetchPlot`, renders Plotly (`react-plotly.js`), loading/error/png fallback.
- `src/components/common/StageHeader.tsx`, `SensorPicker.tsx`, `NodeTable.tsx`, `MiniMap.tsx`, `MetricsCard.tsx`, `RunButton.tsx` — per §2.6.
- `src/lib/normalization.ts` — `NormalizedAsset` type + `upsertAssets` + builders (`buildConfigAsset`, `buildSummaryAsset`, `buildSensorInventoryAsset`, `buildOperationResultAsset`, `buildDatasetPreviewAsset`) for the Assets drawer.
- `src/components/AssetsDrawer.tsx` — collapsible right drawer grouping assets by stage.
- **Gate:** `npm run build` ✓ · a `PlotFrame` unit test rendering a stub Plotly figure ✓.

### Phase C — Stepper shell
- `src/components/PhaseTabs.tsx` — primary nav (Stepper / Canvas / WindKit / Copilot / Compare); Stepper renders 8 chips from `STAGE_META`, colored by `stageStatuses`, locked chips show a tooltip.
- `src/components/AppHeader.tsx` — project name, hub height, coordinate, refresh button, `busyLabel` spinner.
- `src/components/HomeView.tsx` — pre-session landing (Start button, error display).
- `src/components/stages/StageShell.tsx` — shared layout each stage view uses (header + action area + results area); route-like switching on `activeTab`/selected stage.
- Update `src/App.tsx` — wire `HomeView` vs shell, lazy-load tab surfaces.
- **Gate:** `npm run build` ✓ · stepper locks/unlocks correctly when `completed_steps` changes (unit test) ✓.

### Phase D — Stages 1–5 (data-acquisition backbone)
- `src/components/stages/DataLoadView.tsx` — Stage 1 (uploads + BrightHub import + shared datasets + site/hub config).
- `src/components/stages/ReanalysisView.tsx` — Stage 2 (BrightHub + direct ERA5 paths, node table, mini map, homogeneity).
- `src/components/stages/ExploreView.tsx` — Stage 3 (sensor statistics, coverage, wind rose, Weibull, diurnal/monthly, shear profile, TI — all via `PlotFrame`).
- `src/components/stages/ShearExtrapolationView.tsx` — Stage 4 (shear/roughness calc + table + extrapolate-to-hub, `method_counts` display).
- `src/components/stages/ReanalysisExtrapolationView.tsx` — Stage 5 (reanalysis hub confirmation + re-extrapolate + overlay plots).
- Each view calls `store.invokeSessionOperation` / dedicated store actions and reads `stageStatuses`.
- **Gate:** `npm run build` ✓ · each stage runs against the backend for a sample dataset (manual smoke per stage) ✓.

### Phase E — Stages 6–8 (analytical payoff)
- `src/components/stages/LtcView.tsx` — Stage 6 (algorithm multi-select, LTC runs, metrics cards, `ltc_*` plots).
- `src/components/stages/ClippingView.tsx` — Stage 7 (source/col picker, U-curve chart from `analysis_data`, representative-year capture).
- `src/components/stages/EnsembleView.tsx` — Stage 8 (ensemble run + weights viz, uncertainty calculator, P-factors tornado, scenario save/run, exports).
- **Gate:** `npm run build` ✓ · end-to-end: load → reanalysis → shear → LTC → ensemble → save scenario (manual smoke) ✓.

### Phase F — Canvas (React Flow)
- `src/lib/workflow.ts` — `createWorkflowGraph(config, capabilities)` emitting the full 8-stage DAG (§5); `toExecutionRequest` node/edge serializer; canvas node/edge types.
- `src/components/WorkflowView.tsx` — React Flow surface; node click opens a params fly-out; "Run auto/step" wired to `executeWorkflow`/`executeWorkflowStep`; live status via the `/workflow/execute/stream` SSE endpoint; snapshot save/load UI.
- **Gate:** `npm run build` ✓ · canvas executes a 3-node graph against `/workflow/execute` and streams status ✓.

### Phase G — Copilot, Compare, WindKit
- `src/lib/copilotAgent.ts` — BYOK streaming agent (Vercel `ai` SDK) with `updateRunconfigField` / `callSessionRoute` / `callWindKitRoute` / `listScenarios` handlers; workspace context includes `stageStatuses`, `ltcResults`, `clippingReport`, `uncertaintyResult`.
- `src/lib/mcpClient.ts`, `src/lib/openapi.ts` (WindKit tool extraction from `/openapi.json`), `src/lib/scenarioCompare.ts`.
- `src/components/CopilotView.tsx` — chat UI with streamed `tool_calls_executed` chips; BYOK settings drawer (provider/model/apiKey in `localStorage`).
- `src/components/CompareView.tsx` — scenario-slot picker (`baseline/run2/run3`) → `POST /workflow/compare`; render metrics table, config diff, and `PlotFrame`-backed comparison plots (weibull, windrose[], ltc_scatter, uncertainty_tornado).
- `src/components/WindKitExplorerView.tsx` — advanced tool surface over `/api/windkit/*` (categories from `openapi.ts`).
- **Gate:** `npm run build` ✓ · copilot executes one tool call end-to-end ✓ · compare renders for two saved scenarios ✓.

### Cross-phase conventions (apply throughout)
- All async UI state flows through `store.busyLabel` + `store.activity`; never ad-hoc `useState` loading flags for global operations.
- Every mutating store action calls `refreshWorkspace()` (or `refreshResults()` for LTC/ensemble) afterwards so `stageStatuses` and summaries stay correct.
- Serialize complex params the way the backend expects (e.g. `height_sensors` and cleaning `params` as JSON strings — see §5 parameter-coercion caveat).
- Render every plot through `<PlotFrame>`; never call `POST /plots/{name}` directly from a view.

---

## 11. Definition of done (per stage)

A stage is "done" when:
- its primary `completed_steps` flag(s) are present in `/summary`, **and**
- the analyst's decision is captured in config (saved via `PUT /config`) or in a result artifact (LTC result / ensemble / scenario), **and**
- the stage's key visual(s) render without error in `<PlotFrame>`.

The whole workflow is "done" when a scenario is saved (Stage 8) with an ensemble + uncertainty attached.
