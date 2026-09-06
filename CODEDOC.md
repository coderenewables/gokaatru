# GoKaatru — Code Documentation (`CODEDOC.md`)

A detailed, navigational reference to the entire GoKaatru repository: what each part is,
how the pieces fit together, and where to look when you need to change something. It
complements the two other top-level documents:

- **`README.md`** — the closest thing to a functional spec: the full tool/endpoint
  inventory and every disclosed default with its magnitude.
- **`CLAUDE.md`** — the conventions the codebase enforces and the current project state.

This file is about the *code*: structure, module responsibilities, data flow, and the
mechanisms that wire it all together.

> Scope note: `docs/` is gitignored (local working notes, audit ledgers, design docs). A
> fresh clone will not have it. This document is committed and self-contained.

---

## 1. What GoKaatru is

GoKaatru ("Wind" in Tamil) is an **open-source Wind Resource Assessment (WRA) platform**.
It turns a measured wind campaign into a long-term-corrected, hub-height, ensemble-blended
wind-resource characterization suitable for feeding an Energy Yield Assessment, following
IEC 61400-12-1 / 61400-12-2 conventions and built for **bankable rigor**.

It ships as two cooperating parts over one logic core:

- **`server/`** — a Python backend that exposes the same analysis logic through **two
  interfaces**: a **FastMCP** server (MCP tools, stdio) and a **FastAPI** web API (HTTP).
- **`frontend/`** — a **React 19 + Vite + TypeScript** app: data import, an editable
  React-Flow Canvas, a guided Stepper, a read-only Results report, a Sensor Overview
  dashboard, a BYOK AI Copilot, scenario Compare, and the Analysis Engine (scenario sweep).

**Deployment model:** single trusted user, local deployment. There is no auth layer; the
session id is the only credential. Do not discuss multi-user hosting without reading the
README's "Deployment model" section first.

### Size at a glance

| Area | Figure |
|------|--------|
| Backend Python | ~25.6k LOC across 85 files |
| Frontend TS/TSX | ~17.6k LOC |
| MCP tools registered | **226** (84 native GoKaatru + 142 WindKit pass-throughs) |
| FastAPI endpoints | ~200 across 14 route files |
| Backend tests | 74 pytest files (incl. an independent oracle harness) |
| Frontend tests | 19 vitest files |

---

## 2. Core architectural principle: dual-interface, single logic

**MCP tools and FastAPI routes call identical business logic** in `server/tools/` and
`server/core/`. The interface layers are thin:

```
                 ┌──────────────────────┐
   MCP client ──▶│ server/main.py (MCP)  │──┐
                 └──────────────────────┘  │
                                           ├──▶  server/tools/  ──▶  server/core/
                 ┌──────────────────────┐  │        (analytics)        (pure math +
   Browser  ────▶│ server/api/ (FastAPI) │──┘                           orchestration)
                 └──────────────────────┘
                                           against  server/state/  (per-session working data)
```

Rules that follow from this (enforced by reviewers and `tests/test_runconfig_contract.py`):

- New analytics go into `server/tools/` (or `server/core/` for pure math) **first**, then
  get exposed through **both** `server/main.py` (MCP) and `server/api/routes/` (HTTP).
- Never write UI-specific logic in the MCP layer.
- Never add a capability to one interface without the other.

---

## 3. Repository layout (top level)

```
.
├── CLAUDE.md            # conventions + current project state (read before changing code)
├── CODEDOC.md           # this file
├── README.md            # functional spec: tool/endpoint inventory + disclosed defaults
├── pyproject.toml       # Python package + deps + ruff/pytest config
├── startup.ps1          # Windows one-shot dev launcher
├── scripts/             # helper scripts
├── server/              # Python backend (MCP + FastAPI over one logic core)
├── frontend/            # React 19 + Vite + TypeScript app
├── tests/               # backend pytest suite (+ tests/oracles.py reference harness)
└── docs/                # LOCAL ONLY, gitignored: audit ledgers + design docs
```

---

## 4. Backend (`server/`)

```
server/
├── main.py              # FastMCP server + tool registration entry point
├── api/                 # FastAPI web app
│   ├── main.py          # FastAPI entry point; registers 14 routers under /api
│   ├── deps.py          # shared FastAPI dependencies (session resolution, etc.)
│   ├── mcp.py           # session-aware MCP transport mounted into the FastAPI app
│   ├── schemas.py       # thin request/response Pydantic models for the web layer
│   ├── windkit_schemas.py # Pydantic models for the WindKit HTTP routes
│   └── routes/          # 14 route files (~200 endpoints)
├── core/                # pure math + orchestration (no interface code)
├── tools/               # ~20 analytics modules + windkit/ (~180 wrappers)
├── state/               # per-session working data (SessionState, SessionManager, pool)
└── schemas/             # shared Pydantic contracts
```

### 4.1 Entry points

- **`server/main.py`** — constructs the singleton `mcp = FastMCP("GoKaatru", ...)`. Tools
  register themselves via the `@mcp.tool()` decorator; the file then **imports every tool
  module for its side effect** (`import server.tools.xxx  # noqa: F401`). Importing a tool
  module runs its decorators, which is what puts the tool on `mcp`. A subtle but important
  line — `sys.modules.setdefault("server.main", sys.modules[__name__])` — lets tool modules
  do `from server.main import mcp` without an import cycle.
  Run: `python -m server.main` (MCP over stdio).

- **`server/api/main.py`** — the FastAPI app. `create_app()` includes 14 routers, all under
  the `/api` prefix, in a fixed order (health, mcp, sessions, datasets, workflow_execution,
  uploads, config, analysis, brighthub, results, sweep, exports, chat, windkit).
  Run: `python -m uvicorn server.api.main:app --host 127.0.0.1 --port 8000`.

### 4.2 `server/core/` — pure math + orchestration

The interface-free heart. Nothing here imports FastAPI or FastMCP.

| Module | Responsibility |
|--------|----------------|
| `formulas.py` | IEC and extrapolation formula helpers (power/log law, shear/roughness from two heights). |
| `regression.py` | Robust and orthogonal regression helpers (OLS, TLS, confidence intervals). |
| `momm.py` | Mean-of-Monthly-Means utilities. |
| `spatial.py` | Spatial interpolation and great-circle distance helpers. |
| `powercurve.py` | Generic turbine power curves + wind-speed→energy sensitivity factor `S`. |
| `reanalysis.py` | Per-source descriptors for the long-term reference datasets (ERA5, MERRA-2). |
| `validators.py` | Shared Phase-1 validation + the timebase helpers `to_utc_index`, `detect_timestep_minutes`, `SENSOR_FIELDS`, and the timestamp-label convention (F-07). |
| `runconfig.py` | **The canonical/mirror runconfig contract (D20)** — the single source of truth for site metadata; frontend convenience fields are derived mirrors. |
| `executor.py` | Phase-3 workflow-execution orchestration: runs the Canvas DAG node by node. |
| `brighthub.py` | BrightHub API auth + data-access client (used by both the MCP tool and the HTTP route layer). |
| `admissibility.py` | Decides whether a scenario's result may enter the reported sweep spread (the sweep gates). |
| `sweep.py` | Expands a scenario space, runs each leaf (grouped by prefix to reuse expensive upstream stages), and persists every scenario's record. |
| `scenario_context.py` | Runs one scenario without disturbing the session it came from (ContextVar-bound isolation). |
| `scenario_pipeline.py` | One scenario expressed as composable stages, from shear to uncertainty. |
| `scenario_result.py` | One flat, hashable record per scenario (the sweep table row shape). |
| `sensor_selection.py` | Resolves a sensor-selection *policy* (e.g. `availability_90`, `widest_lever`) to concrete sensors. |
| `uncertainty_inputs.py` | Derives a scenario's uncertainty inputs from its own results. |

### 4.3 `server/tools/` — analytics (the MCP tool surface)

Each module owns one analysis area and exposes a handful of `@mcp.tool()` functions plus the
private helpers behind them. The GoKaatru-native tools total **81**; the WindKit
pass-throughs add **142**.

| Module | Tools | Area |
|--------|:----:|------|
| `data_io.py` | 5 | Phase-1 timeseries + datamodel loading, sensor inventory, coverage. |
| `config.py` | 5 | Run-configuration management (get/update/save/load/summary). |
| `cleaning.py` | 4 | Rule-based timeseries cleaning (list/apply/log/undo). |
| `statistics.py` | 9 | Weibull, wind climate, turbulence, windrose, diurnal/monthly, MoMM, scatter. |
| `shear.py` | 7 | Shear/roughness time series and 12×24 lookup tables, sector + aggregated-MoMM tables. |
| `extrapolation.py` | 2 | Hub-height extrapolation of measured masts and reanalysis. |
| `air_density.py` | 2 | IEC moist-air density (point + time series). |
| `atmosphere.py` | 1 | Measured atmospheric-condition summaries (Sensor Overview). |
| `era5.py` | 7 | ERA5 node discovery, extraction, wind-speed compute, interpolation to site, plus the session-scoped EarthDataHub credential (`earthdatahub_set_credential`/`_clear_credential`/`_status`). |
| `homogeneity.py` | 2 | Pettitt homogeneity screening of reanalysis + cutoff application. |
| `ltc.py` | 4 | Deterministic long-term correction: linear LS, total LS, SpeedSort, variance ratio. |
| `ltc_ml.py` | 1 | XGBoost long-term correction (with truncation disclosure). |
| `ensemble.py` | 1 | Multi-algorithm LTC blending. |
| `clipping.py` | 1 | Long-term clipping vs. historic-climate-uncertainty tradeoff. |
| `uncertainty.py` | 2 | Total uncertainty (RSS) + exceedance factors and energy sensitivity. |
| `diagnostics.py` | 4 | Sensor comparison, mast effects, QC diagnostics, MCP readiness. |
| `advanced_analysis.py` | 4 | Energy metrics, extreme winds, ramps, persistence (Sensor Overview). |
| `overview_summary.py` | — | Consolidated bankable Sensor Overview summary table. |
| `map.py` | 3 | GeoJSON site + ERA5-node map overlays. |
| `visualization/` | 11 | Plotly figure tools (see §4.4 — this is a package, not a single file). |
| `brighthub.py` | 9 | BrightHub auth, dataset browsing, and data import. |

#### `server/tools/windkit/` — the WindKit surface (~142 tools)

Thin pass-through wrappers around the [`windkit`](https://pypi.org/project/windkit/) PyPI
package (pinned `>=2.0,<2.1`). Grouped by concern:

| Module | Tools | Area |
|--------|:----:|------|
| `spatial.py` | 31 | Spatial operations. |
| `climate.py` | 29 | Wind climates (TSWC, BWC, WWC, GWC, GeoWC). |
| `topography.py` | 19 | Landcover, elevation, raster/vector maps. |
| `windfarm.py` | 18 | Turbines, WTG, losses/uncertainty. |
| `other.py` | 14 | Weibull, WAsP, coordinates, ERA5 utilities. |
| `wind.py` | 13 | Wind functions. |
| `plotting.py` | 9 | WindKit plotting. |
| `climate_stats.py` | 7 | Wind-climate statistics. |
| `ltc.py` | 2 | WindKit long-term correction (linreg / variance-ratio MCP). |
| `_serializers.py` | — | Shared xarray/geopandas/plotly serialization helpers used by all wrappers. |

### 4.4 `server/tools/visualization/` (Plotly figures)

Originally a single 1,856-line module; now a **themed package** with the same public import
surface. All 47 figure builders are mutually independent — they share only helpers in
`_common` — which is what made the split mechanical rather than behavioural.

```
visualization/
├── __init__.py     # wires the 11 @mcp.tool() wrappers; re-exports every builder so
│                   #   `server.tools.visualization._plot_*` keeps resolving unchanged
├── _common.py      # shared frame/series helpers, COMPASS_16 / MONTH_LABELS constants,
│                   #   and _plot_result (the result-envelope wrapper every builder calls)
├── _measured.py    # measured-mast climatology, distribution and QC builders (largest group)
├── _reanalysis.py  # measured-vs-ERA5 comparison builders
├── _shear.py       # vertical-profile builders (shear/roughness tables, alpha, air density)
└── _ltc.py         # LTC results, uncertainty and scenario-comparison builders
```

The `_plot_*` builders are imported directly by `api/routes/results.py`,
`api/routes/chat.py`, and several test modules; `__init__.py` re-exports all of them (and
the `_common` helpers such as `_sample_for_boxplot`) via an explicit `__all__`, so those
import paths are unchanged by the split.

### 4.5 `server/api/` — the HTTP layer

Route handlers are thin: they resolve the session, call the same `server/tools`/`server/core`
logic as the MCP tools, and shape the response with the Pydantic models in `schemas.py`.

| Route file | Endpoints | Area |
|------------|:--------:|------|
| `windkit.py` | 142 | HTTP mirror of the entire WindKit tool surface. |
| `analysis.py` | 37 | Workflow analysis (statistics, shear, extrapolation, ERA5, ensemble, clipping, homogeneity, uncertainty, scenarios). |
| `workflow_execution.py` | 14 | Phase-3 Canvas DAG execution, snapshots, run comparison, branching. |
| `brighthub.py` | 8 | BrightHub login/logout/status, location browsing, reanalysis, import. |
| `sweep.py` | 7 | Scenario-sweep engine surface (axes, estimate, run, **run/stream** SSE, list, get, runconfig). |
| `datasets.py` | 6 | Shared dataset-pool CRUD + load-into-session. |
| `uploads.py` | 5 | Timeseries/datamodel upload, sensor inventory + coverage, delete. |
| `results.py` | 5 | LTC/ensemble results, plots, site map, runconfig export. |
| `sessions.py` | 4 | Session lifecycle. |
| `exports.py` | 4 | File downloads (timeseries CSV, LTC CSV, ensemble CSV, runconfig JSON). |
| `config.py` | 3 | Runconfig get/update + workflow summary. |
| `mcp.py` | 1 | MCP catalog endpoint. |
| `health.py` | 1 | Health check. |
| `chat.py` | 1 | OpenAI-compatible LLM chat proxy with MCP tool execution (drives the BYOK Copilot). |

`api/mcp.py` additionally mounts a **session-aware MCP transport** into the FastAPI app, so a
browser session and an MCP client can share the same live session state.

### 4.6 `server/state/` — per-session working data

| Module | Responsibility |
|--------|----------------|
| `session.py` | `SessionState` — the mutating singleton holding all working data for one analysis (loaded frames, derived tables, LTC results, runconfig). Bound per-session through a `ContextVar` (`session`). Carries `data_version` stamps: `stamp_derived()` / `staleness_report()` implement the **no-silent-recomputation** rule (derived artifacts are marked stale, never auto-recomputed). |
| `manager.py` | `SessionManager` — the registry of browser workspaces (create / get / fork / delete). |
| `dataset_pool.py` | Shared dataset-pool storage and metadata, so an ingested dataset can be reused across sessions. |

### 4.7 `server/schemas/`

Shared Pydantic v2 contracts (`common.py`) re-exported from the package root for use by both
tools and routes.

---

## 5. The analysis pipeline (data flow)

A campaign flows through these stages; each is exposed as both MCP tools and HTTP endpoints,
and rendered as a node on the frontend Canvas and a step in the Stepper:

```
ingest ─▶ clean ─▶ statistics ─▶ shear / vertical profile ─▶ hub extrapolation
   │                                                                  │
   └────────────▶ reanalysis (ERA5 / MERRA-2) ─▶ homogeneity screen ──┤
                                                                       ▼
        long-term correction (5 algorithms) ─▶ ensemble blend ─▶ clipping
                                                                       ▼
                                        uncertainty (RSS) ─▶ results / visualization
```

Two structural rules shape this flow:

- **Refuse rather than guess.** Sub-six-month LTC, ambiguous DD/MM dates, undeclared
  timezone, degenerate TLS etc. raise instead of returning a number.
- **No silent recomputation.** Derived artifacts (shear tables, hub series, LTC results)
  carry a `data_version` stamp; changing upstream data marks them stale rather than
  silently recomputing.

---

## 6. The Analysis Engine (scenario sweep)

A distinct feature layered on the pipeline: cross a set of methodology choices (sensor
selection, shear-fit set, shear model, extrapolation reference, LTC algorithm, …) into a
scenario space, run every leaf, and report the **spread** of the outcome across all
defensible choices.

- **`core/sweep.py`** expands the space and groups leaves by prefix so the expensive upstream
  stages (shear table, hub series) are computed once per group, not once per leaf.
- **`core/scenario_pipeline.py`** + **`core/scenario_context.py`** run each leaf in
  ContextVar-isolated state; **`core/scenario_result.py`** flattens each to one table row.
- **`core/admissibility.py`** gates which results may enter the reported spread; nothing is
  silently dropped — a scenario that cannot run becomes a `status="failed"` row naming the
  stage that refused.
- **`api/routes/sweep.py`** serves it, including `POST /run/stream`, a Server-Sent-Events
  endpoint that emits one event per scenario as it finishes (its own asyncio-queue +
  `asyncio.to_thread(run_sweep, on_progress=…)` implementation).
- Frontend: `components/sweep/` (Sweep Designer → Run Monitor → Spread Explorer →
  Sensitivity → Spread Summary) over `store/useSweepStore.ts` and `lib/sweepApi.ts` /
  `lib/sweepAnalysis.ts`.

---

## 7. Frontend (`frontend/src/`)

React 19 + Vite + TypeScript. `npm run dev` serves on `:5173` and proxies `/api` → `:8000`.

```
frontend/src/
├── App.tsx              # thin shell; gates on session existence, switches primary views
├── main.tsx             # React entry
├── components/
│   ├── PhaseTabs.tsx     # primary nav: Data import / Cleaning / Analysis Engine / Canvas /
│   │                     #   Stepper / Results / Copilot / Sensor Overview / Compare / How To
│   ├── AppHeader.tsx, HomeView.tsx, HowToView.tsx, AssetsDrawer.tsx
│   ├── WorkflowView.tsx  # the editable React-Flow Canvas (run the pipeline as a DAG)
│   ├── Stepper.tsx       # guided linear per-stage review
│   ├── SensorReviewView.tsx  # Sensor Overview validation dashboard
│   ├── CopilotView.tsx   # BYOK AI Copilot
│   ├── CompareView.tsx   # manual 2–4 run comparison (flagged for subsumption into Spread Explorer)
│   ├── common/           # shared widgets: PlotFrame, MetricsCard, NodeTable, SensorPicker,
│   │                     #   Disclosure, MiniMap, RunButton, StageHeader
│   ├── stages/           # one view per pipeline stage (DataLoad, Cleaning, Shear/Extrap,
│   │                     #   Reanalysis, LTC, Ensemble, Clipping, Explore)
│   ├── results/          # read-only Results report, split into per-section components
│   └── sweep/            # Analysis Engine views (Designer, Monitor, Spread/Sensitivity/Summary)
├── store/
│   ├── useWorkspaceStore.ts  # single Zustand store = entire app state (~2,000 LOC)
│   └── useSweepStore.ts      # separate sweep store (kept apart from the large workspace store)
├── lib/
│   ├── api.ts            # Axios/fetch HTTP client; auto-injects X-GoKaatru-Session header
│   ├── sweepApi.ts       # HTTP client for the sweep engine (kept apart from api.ts)
│   ├── workflow.ts       # React-Flow DAG builder for the 8-stage workflow
│   ├── defaultWorkflowPlan.ts, defaultConfig.ts  # default DAG + config
│   ├── stages.ts         # maps backend completed_steps → 8-stage status
│   ├── configSync.ts     # bidirectional sync: typed WindAnalysisConfig ⇄ flat backend runconfig
│   ├── normalization.ts  # reshape backend responses into uniform NormalizedAsset for the drawer
│   ├── scenarioCompare.ts, sweepAnalysis.ts       # client-side comparison/analysis helpers
│   └── copilotAgent.ts   # BYOK copilot agent over the OpenAI-compatible /chat endpoint
└── types/
    ├── analysis.ts       # canonical config schema + backend response interfaces
    └── sweep.ts          # sweep result-row schema, mirroring the backend
```

Two design points worth knowing:

- The **Canvas** (React-Flow DAG, editable, live execution) and the **Stepper** (guided
  linear review) are **not competing models** — they are separate tabs, Canvas = run the
  pipeline, Stepper = inspect one stage in depth.
- `configSync.ts` is the load-bearing bridge: the backend's single source of truth is the
  flat `runconfig` dict (mirrored from `core/runconfig.py`); the typed `WindAnalysisConfig`
  the UI edits is kept in sync with it in both directions.

---

## 8. Data & disclosure conventions (why the code looks the way it does)

These are enforced by review and by tests, not by style tooling. Match them when editing.

1. **Refuse rather than guess** — don't add silent fallbacks for cases the code currently
   refuses.
2. **Every default/clamp/assumption that changes a number is disclosed** — add (a) a *named
   constant* (never an inline literal), (b) a response field reporting whether/how it fired,
   and (c) a row in the README's "Defaults that affect results" / "Disclosure fields" table.
   There are ~30 existing examples to match; the `disclosure-check` skill formalizes this.
3. **No silent recomputation** — derived artifacts carry `data_version` stamps
   (`stamp_derived` / `staleness_report()` in `state/session.py`).
4. **Methodology choices get measured, not asserted** — when a finding is "which is more
   correct," the fix measures the magnitude on real/synthetic data and reports it.
5. **New physics/statistics code needs an oracle-backed test** — `tests/oracles.py`
   deliberately imports nothing from `server/`; it is an independent reference
   implementation used to verify fixes.
6. **No `TODO`/`FIXME`/`HACK` markers** anywhere in the tree — enforced by convention.
7. **Comments only for non-obvious WHY**, never restating what the code does.

---

## 9. Testing

### Backend (`tests/`, pytest — 74 files)

- `tests/oracles.py` is an **independent-implementation oracle harness**: it imports nothing
  from `server/`, so a passing oracle test is real corroboration, not a tautology.
- Coverage spans ingest/timebase, cleaning, statistics, shear, extrapolation, reanalysis,
  LTC (incl. ML), ensemble, clipping, uncertainty, the sweep/Analysis Engine, the WindKit
  surface, the runconfig contract, path-confinement, and the Sensor Overview.
- Some tests depend on **large, gitignored data fixtures** under `data/uploads/` (e.g. the
  Boxkite and WB-ESMAP campaign CSVs). On a fresh clone without those files, the tests that
  use the `uploaded_timeseries_path` fixture **error at setup** (missing file) — this is an
  environment condition, not a code failure. The rest of the suite runs green.

Run:
```bash
python -m ruff check server/ tests/
python -m pytest tests/ -v
python -c "import asyncio; from server.main import mcp; print(len(asyncio.run(mcp.list_tools())), 'tools')"
```

### Frontend (`frontend/src/test/`, vitest — 19 files)

Covers the stores, the workflow/DAG builder, stage-status logic, the sweep lifecycle and
analysis, disclosure rendering, and the stage/results views.

Run:
```bash
cd frontend && npm run test     # vitest
cd frontend && npm run build    # tsc --noEmit && vite build
```

---

## 10. Running the whole thing

```bash
# Backend (conda env recommended)
conda activate gokaatru
pip install -e ".[ml,dev]"
python -m server.main                                                  # MCP server (stdio)
python -m uvicorn server.api.main:app --host 127.0.0.1 --port 8000     # web API

# Frontend
cd frontend && npm install && npm run dev                              # :5173, proxies /api → :8000
```

Environment: no `.env` file needed — BrightHub and EarthDataHub credentials are entered per
browser session through the UI. For headless deployments, set `WINDKIT_NAME`,
`WINDKIT_EMAIL`, `WINDKIT_INSTITUTION` to avoid WindKit's interactive first-run prompts.
`startup.ps1` is a Windows convenience launcher.

---

## 11. Known limitations (by design, not bugs)

- No AEP/energy yield for the main (non-sweep) pipeline; only the sweep's Analysis Engine
  publishes an indicative gross AEP off a generic 3 MW curve.
- No outlier/spike detection (removed deliberately after measuring it deleted ~1,350 good
  records per campaign to catch a handful of real spikes).
- No atmospheric-stability model — neutral profile only, with the 12×24 shear table as the
  empirical stability proxy.
- Confidence intervals are AR(1)-corrected but still an approximation.

See the README's "Known limitations" section for the full list and rationale.

---

## 12. Maintenance notes & refactor candidates

**Cleanup applied in this pass**

- Removed verified-dead code (functions with zero references across `server/` and `tests/`,
  none exposed through an MCP tool or HTTP route): three `validate_*` helpers in
  `core/validators.py`, `_ensure_json` in `tools/windkit/_serializers.py`, `iter_progress`
  in `core/sweep.py` (superseded by `api/routes/sweep.py::stream_sweep`'s own async
  implementation), `get_measurement_location` in `core/brighthub.py`, and the unused public
  methods `SessionManager.list_sessions` and `SessionState.set_power_curve_name`.
- Split the 1,856-line `tools/visualization.py` into the themed package described in §4.4,
  preserving every existing import path.

**2026-09-06 — EarthDataHub Zarr v3 migration + credential rework**

- EarthDataHub migrated its ERA5 Zarr stores to the Zarr v3 spec (URL unchanged, migrated in
  place). `pyproject.toml` bumped `zarr>=2.14` → `zarr>=3.0` (2.x cannot open a v3 store at
  all) and added explicit `dask`/`aiohttp` dependencies per EarthDataHub's own install docs.
- The EarthDataHub PAT moved from an environment variable / custom `.netrc` parser to
  session-scoped state (`SessionState.earthdatahub_pat`), mirroring BrightHub's
  login/logout/status shape exactly: `earthdatahub_set_credential` / `_clear_credential` /
  `_status` (3 new MCP tools, `server/tools/era5.py`) and `POST|DELETE /era5/credential`,
  `GET /era5/credential/status` (`server/api/routes/analysis.py`). `_open_era5_dataset`,
  `_era5_dataset_url`, `_download_era5_frame_with_retry` and `_find_era5_nodes` now take the
  session explicitly rather than reading a module-level env-var resolver. The speculative
  header-based auth path (`EARTHDATAHUB_API_KEY` / `EARTHDATAHUB_BEARER_TOKEN` / a custom
  header) was removed — it never matched EarthDataHub's actual documented mechanism
  (URL-embedded credential or `.netrc`), confirmed against their live docs before removal.
  Tool count: 223 → 226.

**Candidates for a future pass** (larger modules with a plausible seam, left intact here
because the risk/benefit did not clearly favor churn):

- `server/tools/data_io.py` (~1k LOC) — ingest pipelines are more interdependent than the
  independent plot builders, and are imported widely (`_parse_timeseries`, `_parse_datamodel`,
  `_list_sensors`, `_get_data_coverage`); a package split is feasible with the same
  re-export approach but needs care.
- `server/api/routes/windkit.py` (142 endpoints) and `server/api/routes/analysis.py`.
- `frontend/src/store/useWorkspaceStore.ts` (~2k LOC) — the single largest frontend file;
  the sweep state was already peeled off into `useSweepStore.ts`, and further slicing by
  concern is possible.

When picking any of these up, keep the public import/HTTP surface identical, and validate
against the full backend and frontend suites (plus the tool count — 226 as of 2026-09-06)
before and after.
