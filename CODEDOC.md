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
wind-resource characterization suitable for feeding an Energy Yield Assessment, built for
**bankable rigor**. It makes no standards-conformance claim: methods cite the IEC 61400
clause they draw on, and those citations are not yet verified against the clause text.

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
| MCP tools registered | **90** (the 142 WindKit pass-throughs were removed 2026-11-19, decisions/0009) |
| FastAPI endpoints | ~100 across 13 route files |
| Backend tests | 83 pytest files (incl. an independent oracle harness) |
| Frontend tests | 30 vitest files |

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
│   ├── main.py          # FastAPI entry point; registers 13 routers under /api
│   ├── deps.py          # shared FastAPI dependencies (session resolution, etc.)
│   ├── mcp.py           # session-aware MCP transport mounted into the FastAPI app
│   ├── schemas.py       # thin request/response Pydantic models for the web layer
│   └── routes/          # 13 route files (~100 endpoints)
├── core/                # pure math + orchestration (no interface code)
├── tools/               # ~20 analytics modules
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

- **`server/api/main.py`** — the FastAPI app. `create_app()` includes 13 routers, all under
  the `/api` prefix, in a fixed order (health, mcp, sessions, datasets, workflow_execution,
  uploads, config, analysis, brighthub, results, sweep, exports, chat).
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
| `sweep.py` | Expands a scenario space, runs each leaf (grouped by prefix to reuse expensive upstream stages), and persists every scenario's record. Checkpoints after every shear-prefix group (`checkpoint`, an `in_progress` manifest via `_persist`); skips a leaf whose computation already ran (`_execution_key`, keyed on resolved columns); replaces every JSON file atomically (`_write_json_atomic`, `_REPLACE_ATTEMPTS` / `_REPLACE_RETRY_DELAY_S`). Manifests carry `engine_version` and `duplicates_skipped`. |
| `scenario_context.py` | Runs one scenario without disturbing the session it came from (ContextVar-bound isolation). |
| `scenario_pipeline.py` | One scenario expressed as composable stages, from shear to uncertainty. `resolve_fit` (axis A1) and `resolve_reference` (axis A2) are split so the sweep's shear-prefix step refuses only on the fit policy; `resolve_sensors` calls both. The extrapolate stage carries the measured series only. |
| `scenario_result.py` | One flat, hashable record per scenario (the sweep table row shape). `ENGINE_VERSION` (`2026.11.2`) is hashed into `fixed_prefix_hash`; cleaning-log entries are hashed without the time they ran (`CLEANING_LOG_UNHASHED_KEYS`). `config_hash` leaves policy names out of the spec. `build_result` takes the sweep's prefix rather than recomputing it. |
| `sweep_analysis.py` | Decomposes a sweep metric's variance across the five axes (design doc §7.9). Ported from `frontend/src/lib/sweepAnalysis.ts`, which was deleted — the statistic now has one implementation, reachable from both the Interrogate page and the chat tools. `duplicate_levels(rows, duplicates)` maps each policy level skipped as a duplicate to the level whose rows it shares, so an axis varied between two policies that picked the same sensors does not read as single-level. Also `uncertainty_substitution` (design doc §8.1, F9): folds each axis's level-mean spread of the long-term speed into the MCP and vertical terms by `max()`, adds the reference-source spread, and reports scenario totals with and without it; formerly browser-only. |
| `sensor_selection.py` | Resolves a sensor-selection *policy* (e.g. `availability_90`, `widest_lever`) to concrete sensors. |
| `datamodel_builder.py` | Builds a minimal IEA Task 43 data model from CSV column headers alone, for campaigns delivered without one. Header inference (`draft_columns`), spec validation and Task 43 emission (`build_datamodel`); emits a *document*, never session state. |
| `uncertainty_inputs.py` | Derives a scenario's uncertainty inputs from its own results. `is_hub_interpolated` takes the scenario's reference heights; `derive_uncertainty_inputs` selects `analyst_supplied` or `log_law` shear methods where the source is an analyst exponent or a roughness-only profile. |

### 4.2a `server/operations.py` — the operation registry

Every tool is declared once as an operation (decisions/0009): `@operation(effect=..., stage=...)`,
with `canvas`, `assistant` and `network` where they differ from the defaults. The declaration
publishes the MCP tool itself (`_publish_to_mcp`, through `mcp.tool()`); no tool module touches
`mcp` directly, and `tests/test_mcp_surface.py` compares what clients receive with
`tests/snapshots/mcp_tools.json` (`python -m tests.mcp_surface --write` to refresh). `Operation` also carries disclosure fields, standards references, a code version and
an optional dry run; `REGISTRY` holds all 90. The parameter schema is read from the signature
by FastMCP's own parser. `STAGES` is the pipeline order used for the canvas tie-break. It lives
outside `core/` because it imports FastMCP. The chat route's two tiers and callables, the
executor's canvas dispatch (`_tool_registry`) and its stage tie-break are all read from it;
`tests/test_operations.py` pins the tiers, the non-canvas set and the stage order by name.

### 4.3 `server/tools/` — analytics (the MCP tool surface)

Each module owns one analysis area and exposes a handful of `@mcp.tool()` functions plus the
private helpers behind them. They total **90**.

| Module | Tools | Area |
|--------|:----:|------|
| `data_io.py` | 5 | Phase-1 timeseries + datamodel loading, sensor inventory, coverage. |
| `datamodel_builder.py` | 2 | Draft a Task 43 reading of the loaded columns, and build/persist/load the declared data model (`server/core/datamodel_builder.py` does the work). |
| `sweep_analysis.py` | 3 | Read and explain a persisted sweep: `list_sweeps`, `get_sweep_summary` (which axes varied, which the gates collapsed, which levels were duplicates of another), `analyze_sweep_spread`. The rest of the sweep engine is still HTTP-only. |
| `config.py` | 5 | Run-configuration management (get/update/save/load/summary). |
| `cleaning.py` | 4 | Rule-based timeseries cleaning (list/apply/log/undo). Apply and undo have dry runs (`preview_cleaning_rule`, `preview_undo_cleaning_rule`): the real function runs on a replica of the session (`_replica`) and `_change_summary` reports rows inserted, columns dropped, and per column the records set missing, restored or changed with their runs (at most `PREVIEW_RANGE_LIMIT` listed, `ranges_truncated` saying so). |
| `statistics.py` | 9 | Weibull, wind climate, turbulence, windrose, diurnal/monthly, MoMM, scatter. |
| `shear.py` | 7 | Shear/roughness time series and 12×24 lookup tables, sector + aggregated-MoMM tables. |
| `extrapolation.py` | 2 | Hub-height extrapolation of measured masts and reanalysis. Sub-gate records are extrapolated and counted, not dropped (the gate governs the fit only); `extrapolate_reanalysis=False` skips the reanalysis side effect for sweep leaves. |
| `air_density.py` | 2 | IEC moist-air density (point + time series). |
| `atmosphere.py` | 1 | Measured atmospheric-condition summaries (Sensor Overview). |
| `era5.py` | 7 | ERA5 node discovery, extraction, wind-speed compute, interpolation to site, plus the session-scoped EarthDataHub credential (`earthdatahub_set_credential`/`_clear_credential`/`_status`). |
| `homogeneity.py` | 2 | Pettitt homogeneity screening of reanalysis + cutoff application. |
| `ltc.py` | 4 | Deterministic long-term correction: linear LS, total LS, SpeedSort, variance ratio. `_speedsort_fit` is the rank-sorted fit (sort, then threshold) used at every SpeedSort fit site. |
| `ltc_ml.py` | 1 | XGBoost long-term correction (with truncation disclosure). |
| `ensemble.py` | 1 | Multi-algorithm LTC blending. |
| `clipping.py` | 1 | Long-term clipping vs. historic-climate-uncertainty tradeoff. |
| `uncertainty.py` | 2 | Total uncertainty (RSS) + exceedance factors and energy sensitivity. Interim shear constants `K_SHEAR_ASSUMED_POWER_LAW`, `K_SHEAR_LOG_LAW`, `K_SHEAR_ANALYST_SUPPLIED`; `VALID_SHEAR_METHODS` refuses unknown methods on the MCP path. |
| `diagnostics.py` | 4 | Sensor comparison, mast effects, QC diagnostics, MCP readiness. |
| `advanced_analysis.py` | 4 | Energy metrics, extreme winds, ramps, persistence (Sensor Overview). |
| `overview_summary.py` | — | Consolidated bankable Sensor Overview summary table. |
| `map.py` | 3 | GeoJSON site + ERA5-node map overlays. |
| `visualization/` | 11 | Plotly figure tools (see §4.4 — this is a package, not a single file). |
| `brighthub.py` | 9 | BrightHub auth, dataset browsing, and data import. |

#### WindKit

[`windkit`](https://pypi.org/project/windkit/) is pinned to exactly 2.2.0 and has no tool
surface of its own. `statistics.py` calls `windkit.weibull.fit_weibull_wasp_m1_m3` for the
WAsP Weibull fit; `tests/test_windkit_adopted.py` pins that fit and checks the native
variance-ratio and linear corrections against WindKit's `VarRatMCP` and `LinRegMCP`. The
`server/tools/windkit/` package of 142 pass-through wrappers and its HTTP mirror were removed
on 2026-11-19; `decisions/0009-operation-registry.md` lists what is adopted and why.

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
| `analysis.py` | 37 | Workflow analysis (statistics, shear, extrapolation, ERA5, ensemble, clipping, homogeneity, uncertainty, scenarios). |
| `workflow_execution.py` | 14 | Phase-3 Canvas DAG execution, snapshots, run comparison, branching. |
| `brighthub.py` | 8 | BrightHub login/logout/status, location browsing, reanalysis, import. |
| `sweep.py` | 8 | Scenario-sweep engine surface (axes, estimate, run, **run/stream** SSE, list, get, runconfig, **spread**). |
| `datasets.py` | 6 | Shared dataset-pool CRUD + load-into-session. |
| `uploads.py` | 7 | Timeseries/datamodel upload, the data model builder (draft/build), sensor inventory + coverage, delete. |
| `results.py` | 5 | LTC/ensemble results, plots, site map, runconfig export. |
| `sessions.py` | 4 | Session lifecycle. |
| `exports.py` | 4 | File downloads (timeseries CSV, LTC CSV, ensemble CSV, runconfig JSON). |
| `config.py` | 3 | Runconfig get/update + workflow summary. |
| `mcp.py` | 1 | MCP catalog endpoint. |
| `health.py` | 1 | Health check. |
| `chat.py` | 1 | OpenAI-compatible LLM chat proxy with MCP tool execution (drives the BYOK Copilot). |
| `operations.py` | 91 | Generated from the registry: `POST /sessions/{id}/operations/{name}` for each of the 90 operations, with a body model built from the function signature (`<Name>Parameters`, extra fields refused), and `GET /operations` listing every declaration. Same session binding and error mapping as chat. |

`api/mcp.py` additionally mounts a **session-aware MCP transport** into the FastAPI app, so a
browser session and an MCP client can share the same live session state.

### 4.6 `server/state/` — per-session working data

| Module | Responsibility |
|--------|----------------|
| `session.py` | `SessionState` — the mutating singleton holding all working data for one analysis (loaded frames, derived tables, LTC results, runconfig). Bound per-session through a `ContextVar` (`session`). Carries `data_version` stamps: `stamp_derived()` / `staleness_report()` implement the **no-silent-recomputation** rule (derived artifacts are marked stale, never auto-recomputed). |
| `manager.py` | `SessionManager` — the registry of browser workspaces (create / get / fork / delete). `_clone_session_state` copies every `SessionState` field; `_CLONE_EXCLUDED` names the identity fields a fork must not inherit. A coverage test enforces that every attribute is cloned or excluded. |
| `dataset_pool.py` | Shared dataset-pool storage and metadata, so an ingested dataset can be reused across sessions. |
| `project.py` | `ProjectStore` (decisions/0010): a session's state on disk. Raw inputs stay in `uploads/`, each with its SHA-256 in `catalogue.sqlite`; opening refuses (`ProjectIntegrityError`, HTTP 409) if one was changed or removed. Every DataFrame is written to `working/<content sha256>.parquet`, so an unchanged frame is not rewritten and identical frames are stored once; every other field is JSON in the catalogue. `EXCLUDED_FIELDS` names what is never written and why (identity, credentials, in-flight run status). `SessionManager.get_session` reopens a saved project after a restart, falling back to `runconfig.json` alone for a workspace without one. |

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
- **Checkpointing (T12).** With persistence on, `run_sweep` rewrites the manifest, results and
  runconfigs after each shear-prefix group, with `in_progress: true` until the final write.
  `list_sweeps` reports the flag; a crash loses at most the group in flight. Each checkpoint
  rewrites the whole sweep, so cost grows with sweep size (about 94,500 runconfig writes on a
  9,000-leaf, 20-group sweep).
- **Duplicates (T7).** A leaf whose resolved computation (fit and reference columns, shear model,
  reference source, LTC algorithm, hub height, analyst exponent) already completed in this sweep
  is not run; it is listed in `manifest.duplicates_skipped` with `same_as`.
- **Reanalysis (T8).** Sweep leaves never extrapolate the reanalysis to hub height; the LTC reads
  the native `Spd_100m` / `Spd_50m` columns.
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
├── App.tsx              # thin shell; gates on session existence, switches on activePhase
├── main.tsx             # React entry
├── components/
│   ├── PhaseRail.tsx     # primary nav (2026-09 redesign): Prepare / Run / Interrogate /
│   │                     #   Canvas / Copilot — replaced the old 10-tab PhaseTabs.tsx
│   ├── CommandPalette.tsx  # ⌘K "Ask or jump" — searches real phases/stages/presets/
│   │                     #   metrics/gates; free text falls through to Ask Copilot
│   ├── PrepareView.tsx   # Prepare phase: merges Data import/Cleaning/Reanalysis/Sensor
│   │                     #   Overview/Stepper/Results into one screen with an internal
│   │                     #   Data loading|Pipeline|Sensor Overview|Results section switcher,
│   │                     #   real prefix-stat tiles + stamp banner (server/tools/scenario_result.py)
│   ├── RunView.tsx       # Run phase: SweepDesigner + SweepMonitor on one screen
│   ├── InterrogateView.tsx  # Interrogate phase: SpreadSummaryView + SpreadExplorer +
│   │                     #   SensitivityView + GateReportView stacked under one metric switch
│   ├── AppHeader.tsx, HomeView.tsx, HowToView.tsx, AssetsDrawer.tsx
│   │                     #   HowToView is now a header-triggered overlay (howToOpen), not a tab
│   ├── WorkflowView.tsx  # Canvas: the editable React-Flow DAG. Populated *only* by
│   │                     #   "Load from sweep" (picks a sweep + scenario, loads that
│   │                     #   scenario's exact runconfig via loadScenarioIntoCanvas), "Upload
│   │                     #   config" (reads a local .json file via FileReader into the same
│   │                     #   Edit config textarea, 2026-09-08), or manual Edit config/
│   │                     #   Rebuild from config — no auto-built default pipeline
│   │                     #   (2026-09-07; see CLAUDE.md). Also hosts a "Compare runs" toggle
│   │                     #   that swaps in CompareView unchanged (Compare's tab was retired —
│   │                     #   it compares workflow-run executions, not sweep scenarios, so it
│   │                     #   relocated here rather than into Interrogate)
│   ├── Stepper.tsx       # guided linear per-stage review — now reached via Prepare's
│   │                     #   "Pipeline" section (StageShell), not a standalone tab
│   ├── SensorReviewView.tsx  # Sensor Overview validation dashboard — reached via Prepare's
│   │                     #   "Sensor Overview" section
│   ├── CopilotView.tsx   # BYOK AI Copilot (kept as its own PhaseRail entry, alongside ⌘K)
│   ├── CompareView.tsx   # manual 2–4 workflow-run comparison; mounted inside WorkflowView now
│   ├── common/           # shared widgets: PlotFrame, MetricsCard, NodeTable, SensorPicker,
│   │                     #   Disclosure, MiniMap, RunButton, StageHeader
│   ├── stages/           # one view per pipeline stage (DataLoad, DataModelBuilder,
│   │                     #   Cleaning, Shear/Extrap, Reanalysis, LTC, Ensemble,
│   │                     #   Clipping, Explore) — composed by StageShell inside
│   │                     #   PrepareView; DataModelBuilder is a DataLoad sub-path
│   ├── results/          # read-only Results report — reached via Prepare's "Results" section
│   └── sweep/            # the individual sweep views RunView/InterrogateView compose
│                         #   (Designer, Monitor, Spread/Sensitivity/Summary/GateReport);
│                         #   AnalysisEngineView.tsx (the old 6-sub-tab shell) was deleted
├── store/
│   ├── useWorkspaceStore.ts  # single Zustand store = entire app state (~2,300 LOC).
│   │                     #   Nav field is `activePhase: PhaseId` (5 values), not the old
│   │                     #   `activeTab: TabId` (10 values); `prepareSection` picks Prepare's
│   │                     #   internal section; `prefixHash`/`reanalysisSourcesForPrefix`/
│   │                     #   `cleaningActionsCount`/`loadPrefixHash()` back Prepare's tiles;
│   │                     #   `howToOpen`/`paletteOpen` are the two overlay flags;
│   │                     #   `loadScenarioIntoCanvas(sweepId, configHash)` is Canvas's sole
│   │                     #   population path (2026-09-07) — sequences the pre-existing
│   │                     #   `replaceWorkflowRunConfig`+`rebuildWorkflowGraph` pair
│   └── useSweepStore.ts      # separate sweep store (kept apart from the large workspace
│                         #   store); `previewSweepScenarios()` peeks a sweep's scenario list
│                         #   for Canvas's picker without touching manifest/rows/phase, unlike
│                         #   `openSweep()` which Run/Interrogate read from
├── lib/
│   ├── api.ts            # Axios/fetch HTTP client; auto-injects X-GoKaatru-Session header
│   ├── sweepApi.ts       # HTTP client for the sweep engine, incl. getPrefixHash (2026-09)
│   ├── prepareStats.ts   # pure helpers for Prepare's stat tiles (meanCoverage) — plain
│   │                     #   arithmetic over already-disclosed numbers, no disclosure entry
│   ├── workflow.ts       # React-Flow DAG builder for the 8-stage workflow
│   ├── defaultWorkflowPlan.ts, defaultConfig.ts  # default DAG + config
│   ├── stages.ts         # maps backend completed_steps → 8-stage status
│   ├── configSync.ts     # bidirectional sync: typed WindAnalysisConfig ⇄ flat backend runconfig
│   ├── normalization.ts  # reshape backend responses into uniform NormalizedAsset for the drawer
│   ├── scenarioCompare.ts, sweepAnalysis.ts       # client-side comparison/analysis helpers
│   └── copilotAgent.ts   # BYOK copilot agent over the OpenAI-compatible /chat endpoint
└── types/
    ├── analysis.ts       # canonical config schema + backend response interfaces
    └── sweep.ts          # sweep result-row schema, mirroring the backend; PrefixHash added
```

Two design points worth knowing:

- The **Canvas** (React-Flow DAG, editable, live execution) and the **Stepper** (guided
  linear review) are **not competing models** — Canvas = run the pipeline as a graph,
  Stepper = inspect one stage in depth. Since the 2026-09 redesign they are reached
  differently (Canvas is its own `PhaseRail` entry; the Stepper lives inside Prepare's
  "Pipeline" section) but the underlying distinction is unchanged.
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

### Backend (`tests/`, pytest — 83 files)

- `tests/test_heldout_height.py` (T2): predicts a withheld sensor from the two below it on real
  campaigns (Launakalana 80 m, Boxkite 250 m) and asserts the series-mean bias is under 1%.
  Needs the gitignored `data/uploads/` fixtures; errors at setup without them.
- `tests/test_speedsort_rank_sorted.py` (T3): SpeedSort mean-bias bands on Launakalana, and
  agreement between the rank-sorted and time-paired fits on perfectly correlated data. The
  Launakalana cases need the gitignored `data/uploads/` fixtures; the synthetic case does not.

- `tests/oracles.py` is an **independent-implementation oracle harness**: it imports nothing
  from `server/`, so a passing oracle test is real corroboration, not a tautology.
- Coverage spans ingest/timebase, cleaning, statistics, shear, extrapolation, reanalysis,
  LTC (incl. ML), ensemble, clipping, uncertainty, the sweep/Analysis Engine, the adopted
  WindKit functions, the runconfig contract, path-confinement, and the Sensor Overview.
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

### Frontend (`frontend/src/test/`, vitest — 30 files)

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
browser session through the UI. WindKit 2.2.0 reads its optional attribution variables
(`WINDKIT_NAME`, `WINDKIT_EMAIL`, `WINDKIT_INSTITUTION`) without ever prompting, so a
headless run needs none of them. `startup.ps1` is a Windows convenience launcher.

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

**2026-11-19 — WindKit narrowed (decisions/0009)**

- Removed `server/tools/windkit/` (142 pass-through tools and `_serializers.py`),
  `server/api/routes/windkit.py` (142 endpoints), `server/api/windkit_schemas.py`,
  `tests/test_windkit.py` and `tests/test_windkit_submodule_smoke.py`. Also removed the dead
  `SessionState.windkit_data` (initialised and cloned, never written), its `windkit`
  completed-step token, the per-session `windkit/` directory, the WindKit-only executor
  parameter aliases (`west_east`, `south_north`, `height`), and the frontend config values
  that named WindKit modes the backend never implemented (`shear.useWindKit`, shear method
  `windkit`, reanalysis provider `windkit`, LTC algorithms `windkit_linreg_mcp` /
  `windkit_varrat_mcp`). Dropped `geopandas` and `pyproj` as direct dependencies; nothing
  imports them, and WindKit still installs them. Tool count: 232 → 90.
- WindKit pinned `>=2.0,<2.1` → `==2.2.0`. `tests/test_windkit_adopted.py` replaces the
  removed smoke test's purpose (catch upstream drift) for the functions actually used.

**Candidates for a future pass** (larger modules with a plausible seam, left intact here
because the risk/benefit did not clearly favor churn):

- `server/tools/data_io.py` (~1k LOC) — ingest pipelines are more interdependent than the
  independent plot builders, and are imported widely (`_parse_timeseries`, `_parse_datamodel`,
  `_list_sensors`, `_get_data_coverage`); a package split is feasible with the same
  re-export approach but needs care.
- `server/api/routes/analysis.py` (37 endpoints).
- `frontend/src/store/useWorkspaceStore.ts` (~2k LOC) — the single largest frontend file;
  the sweep state was already peeled off into `useSweepStore.ts`, and further slicing by
  concern is possible.

When picking any of these up, keep the public import/HTTP surface identical, and validate
against the full backend and frontend suites (plus the tool count — 226 as of 2026-09-06)
before and after.
