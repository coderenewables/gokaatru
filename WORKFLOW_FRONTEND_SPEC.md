# GoKaatru — Workflow-Driven Frontend Specification

> **Scope.** This document specifies a **workflow-driven frontend** for the GoKaatru wind-resource-assessment app, built on top of the existing Python backend in [`server/`](./server/) and the existing React frontend in [`frontend/`](./frontend/). It is an implementation-grade spec: each section names the exact backend endpoints, request/response shapes, state, and UI components required.
>
> **Author audience.** A frontend engineer who will implement (or refactor) the UI against the backend as it exists today.

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

The app already has a session-based backend (`X-GoKaatru-Session` header), a Zustand store, a React-Flow canvas, a BYOK copilot, and a compare view. **This spec reshapes the linear "Setup" view into an explicit 8-stage wizard/stepper** that drives these endpoints in the correct dependency order, while reusing the canvas, copilot, and compare pillars.

---

## 1. Backend model the frontend must respect

### 1.1 Session = the unit of work

Every analysis lives in a **session** (`server/state/session.py`). A session has:
- an `id` (UUID hex) and a workspace directory on disk;
- an in-memory `SessionState` holding all intermediate artifacts (parsed frames, shear tables, ERA5 nodes, LTC results, ensemble, etc.);
- a `runconfig` dict that is the **single source of truth** for user decisions and is persisted to `runconfig.json`.

**Frontend implication:** the app is single-session-per-tab. Create one on "Start", persist its id in `localStorage` (`gokaatru-active-session-id`, already implemented), and send `X-GoKaatru-Session: <id>` on every `/api/sessions/{id}/...` call. The API client in `frontend/src/lib/api.ts` already injects this header automatically from the path — keep that.

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

The `completed_steps` array (returned by `/summary` and `/sessions/{id}`) is the canonical progress indicator:
`timeseries, datamodel, config, cleaning, shear_timeseries, shear_table, roughness_timeseries, roughness_table, era5_nodes, era5_extract, era5_interpolate, ltc, ensemble, windkit`.

**Frontend implication:** the stepper must disable/lock downstream stages until upstream `completed_steps` are present, and must offer to auto-run prerequisites.

### 1.3 The `runconfig` ↔ `WindAnalysisConfig` mapping

The frontend keeps a richer typed config (`WindAnalysisConfig` in `frontend/src/types/analysis.ts`) and syncs it bidirectionally with the flat backend `runconfig` via `configSync.ts` (`hydrateConfigFromRunconfig` / `serializeConfigToRunconfig`). Key backend runconfig keys observed: `project_name`, `location` `{latitude, longitude, elevation_m}`, `measurement_type`, `hub_height_m`, `sensor_mapping`, `cleaning_log`, `brighthub_uuid`, plus `shear_table_shape`/`roughness_table_shape`. **The frontend config is the editing surface; the backend runconfig is the persisted truth.** Always `saveConfig()` (PUT `/config`) before running an operation that depends on a config value (e.g. hub height).

### 1.4 Plot protocol

All visuals use one envelope (`server/schemas/common.py::PlotResult`):
```ts
{ plotly_json: string, png_base64: string | null, title: string }
```
- `plotly_json` is a JSON-stringified Plotly figure → `JSON.parse` then `Plotly.react` (or `react-plotly.js` `<Plot data={fig.data} layout={fig.layout} />`).
- `png_base64` is a graceful fallback when Kaleido is present.
- Plots are fetched via **`POST /api/sessions/{id}/plots/{plot_name}`** with a `PlotRequest` body (sensor names, algorithm, uncertainty %s). Supported `plot_name` values (27): `windrose, weibull, diurnal, scatter, timeseries, timeseries_preview, cleaning_overlay, coverage_timeline, data_coverage, scenario_comparison, era5_comparison, era5_measured_overlay, shear_table, shear_profile, monthly_means, turbulence_intensity, ltc_comparison, ltc_scatter, ltc_residuals, ltc_monthly, ltc_convergence, annual_means, uncertainty_breakdown, uncertainty_tornado`.

---

## 2. Existing frontend — what to keep, what to change

### 2.1 Stack (keep)
- **React 19 + Vite 6 + TypeScript**, Zustand store (`useWorkspaceStore`), `@xyflow/react` (React Flow) canvas, `plotly.js-dist-min` + `react-plotly.js`, `zod` config schema, Vercel **`ai`** SDK + `@modelcontextprotocol/sdk` for the BYOK copilot.
- API client (`lib/api.ts`) is complete and correct — **reuse, do not rewrite**.
- Brand palette already used by backend plots: orange `#c86a2a`, teal `#0b7a6f`/`#083434`, neutral `#5f716a`/`#f3efe6`. Mirror in frontend CSS.

### 2.2 Current tab structure (`App.tsx` + `PhaseTabs`)
`setup | workflow | windkit | copilot | compare`

### 2.3 Required changes
1. **Replace the single `SetupView` with an 8-stage Stepper** (`DataLoadView` → `ReanalysisView` → `ExploreView` → `ShearExtrapolationView` → `ReanalysisExtrapolationView` → `LtcView` → `ClippingView` → `EnsembleView`). This is the core deliverable. The Stepper must read `completed_steps` to mark stages done/locked.
2. Keep **`WorkflowView`** (React Flow canvas) as the "expert/bird's-eye" surface that mirrors the stepper state into nodes — but extend `createWorkflowGraph` (in `lib/workflow.ts`) from 6 nodes to the **full 8-stage graph** with the homogeneity/clipping/ensemble nodes currently missing.
3. Keep **`CopilotView`** and **`CompareView`** as-is (they already target the right endpoints), but ensure the copilot's workspace context includes the new stage statuses.
4. Keep **`WindKitExplorerView`** as an advanced/optional tool surface.

### 2.4 New shared components to build
- `<PlotFrame plotName params />` — fetches a PlotResult and renders Plotly (with loading/error/png fallback). Centralizes all chart rendering.
- `<StageHeader stage status />` — title, description, completion badge, lock state.
- `<SensorPicker kind filter />` — select speed/dir sensors from `sensors[]` in store.
- `<NodeTable nodes provider />` — render ERA5/MERRA-2 node list with distance/bearing + a mini map.
- `<MiniMap geojson />` — Leaflet-free lightweight map (or reuse `GET /map/site` GeoJSON on a simple SVG/React-Flow minimap; add Leaflet only if needed).
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
- The **Assets drawer** shows `assets[]` (already normalized in store) grouped by stage: datasets, sensor inventory, operation results, plots. Each asset is expandable.

### 3.2 Store additions (`useWorkspaceStore`)
Add to the existing store (keep all current fields/actions):
```ts
// new state
stageStatuses: Record<StageId, "locked"|"available"|"in_progress"|"done"|"error">;
era5Nodes: EraNode[];                 // from find_era5_nodes / brighthub reanalysis nodes
merraNodes: EraNode[];
era5InterpolatedSummary: { rows: number; method: string; columns: string[] } | null;
ltcResults: LtcResultSummary[];       // from GET /results/ltc
ensembleSummary: { available: boolean; rows?: number; columns?: string[] };
homogeneityReport: HomogeneityDataset[] | null;
clippingReport: ClippingReport | null;
uncertaintyResult: UncertaintyResult | null;
activePlot: { plotName: string; params: PlotRequest } | null;

// new actions
runStage(stage: StageId): Promise<void>;       // orchestrates a whole stage end-to-end
fetchPlot(plotName: string, params: PlotRequest): Promise<PlotResult>;
refreshResults(): Promise<void>;               // calls results/ltc, results/ensemble, clipping columns, etc.
```
`refreshWorkspace()` already pulls summary/config/sensors/capabilities; extend it to also compute `stageStatuses` from `summary.completed_steps`.

`StageId = "data" | "reanalysis" | "explore" | "shear" | "reanalysis_extrapolation" | "ltc" | "clipping" | "ensemble"`.

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

## 5. Canvas view (`WorkflowView`) — extend to 8 stages

Update `lib/workflow.ts::createWorkflowGraph` to emit the full pipeline as a DAG so the expert user can see and re-run any node. Proposed nodes (left→right, top→bottom):

```
dataset ─► cleaning ─► explore(stats) ─► shear ─► extrapolate_hub ─► ltc ─► ensemble ─► uncertainty
   │                         │
   └─► era5_nodes ─► era5_extract ─► era5_interpolate ─► homogeneity ─┐
   └─► merra_download ─────────────────────────────────────────────────┤
                                                                       ▼
                                                                 clipping ◄── ensemble
```

Each node's `templateId` must match a backend capability (from `GET /workflow/capabilities`) or `"select-dataset"`. Each node's `paramsJson` is built from the corresponding config slice. The existing `executeWorkflow(mode)` / `executeWorkflowStep()` actions already POST the graph to `/workflow/execute[/step]` and stream events — keep this. For long runs, prefer the **SSE stream** endpoint `POST /workflow/execute/stream` (currently unused by the frontend) for live node-status updates on the canvas.

**Capability → template_id reference** (resolved at runtime; the executor binds the session and dispatches by function name):
`select-dataset`, `parse_timeseries`, `parse_datamodel`, `list_sensors`, `apply_cleaning_rule`, `undo_cleaning_rule`, `calculate_shear_timeseries`, `build_shear_table`, `calculate_roughness_timeseries`, `build_roughness_table`, `extrapolate_to_hub_height`, `extrapolate_reanalysis_to_hub`, `find_era5_nodes`, `extract_era5_data`, `compute_era5_wind_speed`, `interpolate_era5_to_site`, `analyze_homogeneity`, `apply_homogeneity_cutoff`, `run_ltc_linear_least_squares`, `run_ltc_total_least_squares`, `run_ltc_speedsort`, `run_ltc_variance_ratio`, `run_ltc_xgboost`, `run_ensemble`, `run_clipping_analysis`, `calculate_uncertainty`, `brighthub_*`, `windkit_*`, plus all `plot_*`/visualization helpers.

> **Parameter coercion caveat:** the executor's `_build_kwargs` resolves params by name **or alias** (e.g. `file_path`←`path`, `height_sensors`←`sensors`, `sensor_name`←`sensor`, `nodes_json`←`nodes`) and JSON-serializes dict/list values for `str` params. So when building `paramsJson` for the canvas, use either the canonical param name or a known alias, and serialize complex params as the backend tool expects (e.g. `height_sensors` as a JSON string, `params` for cleaning as a JSON string).

---

## 6. Copilot integration (`CopilotView`)

Already functional via `POST /api/sessions/{id}/chat` (BYOK, OpenAI-compatible, server-side tool execution against the same MCP tool registry, up to 12 tool rounds). **No structural change needed**, but:
- Enrich the workspace context handed to the agent with `stageStatuses`, `ltcResults`, `clippingReport`, `uncertaintyResult` so it can answer "which stages are done?" and "what's my P90?".
- Surface the streamed `tool_calls_executed` as inline chips ("Running speedsort…") — already supported by `CopilotToolEvent`.

---

## 7. Compare view (`CompareView`)

Already targets `POST /api/sessions/{id}/workflow/compare` and `POST /workflow/branches/fork`. Keep. Ensure the **scenario slots** (`baseline/run2/run3`) map to saved scenarios (Stage 8) so analysts can diff two LTC/ensemble strategies. The compare response includes metrics (LT mean, P50/75/90/99, uncertainties), config diffs, and Plotly figures (weibull, windrose[], ltc_scatter, uncertainty_tornado) — render via `<PlotFrame>`.

---

## 8. Data model additions (`types/analysis.ts`)

Add these TypeScript interfaces to mirror backend responses (keep the existing `WindAnalysisConfig` schema):

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

## 10. Implementation phases (suggested)

1. **Phase A — Types & store.** Add the §8 interfaces; extend `useWorkspaceStore` with `stageStatuses`, result summaries, `runStage`, `fetchPlot`. Extend `refreshWorkspace` to compute stage statuses from `completed_steps`.
2. **Phase B — Shared components.** `<PlotFrame>`, `<StageHeader>`, `<SensorPicker>`, `<NodeTable>`, `<MiniMap>`, `<MetricsCard>`.
3. **Phase C — Stepper shell.** Replace `SetupView` with the 8-stage router; wire stage lock/unlock to `stageStatuses`.
4. **Phase D — Stages 1–5** (data, reanalysis, explore, shear, reanalysis-extrapolation). These are the data-acquisition backbone.
5. **Phase E — Stages 6–8** (LTC, clipping, ensemble/uncertainty/scenarios). The analytical payoff.
6. **Phase F — Canvas upgrade.** Extend `createWorkflowGraph` to the full 8-stage DAG; wire SSE streaming for live execution.
7. **Phase G — Copilot context & Compare polish.**

---

## 11. Definition of done (per stage)

A stage is "done" when:
- its primary `completed_steps` flag(s) are present in `/summary`, **and**
- the analyst's decision is captured in config (saved via `PUT /config`) or in a result artifact (LTC result / ensemble / scenario), **and**
- the stage's key visual(s) render without error in `<PlotFrame>`.

The whole workflow is "done" when a scenario is saved (Stage 8) with an ensemble + uncertainty attached.
