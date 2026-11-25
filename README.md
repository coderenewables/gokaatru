# GoKaatru

> Open-source **Wind Resource Assessment (WRA)** platform — turn a measured wind campaign into a long-term-corrected, hub-height, ensemble-blended dataset ready for an Energy Yield Assessment (EYA).

GoKaatru ships as two parts that work together:

- **[`server/`](./server)** — a Python **MCP server** (FastAPI + FastMCP) exposing **101 tools** across data ingest, cleaning, statistics, shear/extrapolation, ERA5 & MERRA-2 acquisition, homogeneity, five long-term-correction (MCP) algorithms, ensemble, clipping, uncertainty, mapping, visualization, and BrightHub integration. DTU's WindKit library supplies the WAsP Weibull fit (see [WindKit](#windkit)).
- **[`frontend/`](./frontend)** — a **workflow-driven web app** (React + Vite + TypeScript) with standalone data import, an editable React-Flow Canvas, a guided post-import Stepper, a read-only **Results** report, a **Sensor Overview** validation dashboard, a BYOK AI copilot, and scenario comparison.

State is session-scoped; `runconfig` is the single source of truth for site metadata (project name, location, hub height, sensors, cleaning log, LTC settings). The frontend's convenience fields are **derived mirrors** of canonical backend keys, not independent state — the mapping is defined once in [`server/core/runconfig.py`](./server/core/runconfig.py) and enforced by `tests/test_runconfig_contract.py`.

## Application workflow

The default application flow is:

```
Data import + hub height + reanalysis provider
    │
    ├──► BrightHub sign-in when required
    │
    └──► Save config and setup
           │
           ├──► ERA5 / MERRA-2 download + interpolation
           │
           ▼
    Data cleaning (fully optional, skippable)
           │
           ▼
       Analysis Engine (scenario sweep)
           │
           ▼
    Editable Canvas default plan — prepared, run on demand
           │
           ▼
       Post-import Stepper and specialist tools
```

### Data import and default Canvas plan

1. Import measured time-series and an IEA Task 43 data model, import a BrightHub location, or load a shared dataset.
   - **No Task 43 JSON?** The fourth import path, **Build data model**, reads the loaded CSV's column headers and drafts a sensor per column — measurement type, height, and the turbulence column paired with each anemometer. The draft is a proposal: correct or exclude any row, declare the logger's UTC offset (or an IANA zone), optionally add boom orientation and a primary-sensor flag, then build. The result is a real Task 43 document written into the session workspace and parsed by the same code path as an uploaded one, so it is downloadable and re-usable rather than an inference living in server memory. Columns it could not read — quality flags, logger diagnostics, statistic channels — are listed with the reason rather than hidden.
2. (Optional) In the **Analysis sensor selection** table, untick sensors to exclude them. Applying the selection removes them from the working data and records them in `excluded_sensors`; reloading the data file or re-importing from BrightHub restores the full set.
3. Enter the site metadata and **hub height**. Hub height has no default and is required before a model can run.
4. In **Long-term reference**, choose the reanalysis provider — BrightHub (ERA5 + MERRA-2) or EarthDataHub (direct ERA5 only) — and the date window. The choice persists to `runconfig` as `reanalysis.acquisitionSource` (default `brighthub`), so which reanalysis a result was built on is recorded with the analysis rather than being a per-session UI setting. It is a frontend-owned key, not a mirror: nothing on the backend derives it, and `tests/test_runconfig_contract.py` asserts it survives normalization. Choosing EarthDataHub reveals a credential field for a PAT (a "Standard API key" or a legacy "Classic" key from [earthdatahub.destine.eu](https://earthdatahub.destine.eu)'s Quota & API keys page — both work identically here) — entered once per browser session and stored server-side in memory only, exactly like the BrightHub client credentials on the same page; there is no server config file to edit.
5. Click **Save config and setup**. When the provider is BrightHub and credentials are not available, the app opens the BrightHub sign-in view instead of downloading.
6. The app persists the runconfig, downloads and interpolates the reanalysis, prepares the default Canvas graph, and opens the optional cleaning step. **The Canvas is not executed automatically** — the prepared graph stays editable and runs only when the analyst starts it from the Canvas.

### Running a model on Canvas

`Run auto` sends the Canvas graph to the session workflow executor. The backend executes executable nodes in dependency order and streams lifecycle events back to the browser as each node starts, finishes, fails, or is cancelled.

While a run is active, the Canvas shows:

- a node state of `pending`, `running`, `done`, or `error` for every executable operation;
- elapsed time for the active node and completed duration for finished nodes;
- completed-node count and total elapsed run time;
- an estimated remaining time once at least one node has finished. The estimate uses the average duration of completed nodes, so it improves as the run advances;
- a rolling event log with the server message for each operation.

Use **Stop** to request cancellation. The graph stays on the Canvas with its final statuses and event history so the analyst can inspect or edit the failing branch before another run.

The default graph makes conservative, editable choices:

- uses the two measured wind-speed heights nearest to the requested hub height for power-law shear;
- loads BrightHub ERA5 and MERRA-2, then interpolates ERA5 to the site;
- runs `linear_least_squares` and `variance_ratio` LTC branches;
- produces an inverse-RMSE ensemble, ensemble-based clipping, and uncertainty;
- leaves cleaning as a manual review node, so importing data never silently removes measurements.

### Post-import Stepper

The Stepper remains available after data import for guided review and manual operation of the analysis stages:

| Stage | What happens |
|---|---|
| **1. Data cleaning** | Review the imported measurement inventory, choose which sensors stay in the analysis (excluded sensors are removed from the working data and recorded in `excluded_sensors`), and apply explicit cleaning filters when appropriate. Fully optional — it has its own top-level tab, and nothing downstream requires it. |
| **2. Reanalysis acquisition** | Review the ERA5 + MERRA-2 nodes and site interpolation already downloaded by **Save config and setup**, and re-run acquisition if needed. The provider (BrightHub, or direct EarthDataHub ERA5) and date window are chosen on the Data import page. |
| **3. Measured-data exploration** | Recovery/availability, wind rose, Weibull, diurnal/annual profiles, shear profile, turbulence intensity — to refine shear sensors and LTC strategy. |
| **4. Shear → hub (measured)** | Power-law (α) or log-law (z₀) shear + 12×24 lookup, extrapolate measured sensors to hub height. Only records above `min_speed_mps` (default **3.0 m/s**) contribute — below that, `ln(v₂/v₁)` is anemometer noise rather than profile. α is still bounded to [−1, 1] as a backstop, and every response reports how often that clamp fired. |
| **5. Reanalysis → hub** | Confirm long-term reference series are available at hub height using the chosen shear method. |
| **6. Long-Term Correction** | MCP between measured (short) and reanalysis (long) across 5 algorithms (`speedsort` — directionally binned, `linear_least_squares`, `total_least_squares`, `variance_ratio`, `xgboost`); scatter/residual/convergence diagnostics. Requires **at least six months** of valid concurrent records; below that it raises rather than returning a number. |
| **7. Clipping** | Pick the representative historical window that minimizes combined historic + climate uncertainty. Calendar years below **90%** completeness are excluded and reported, so a partial first or last year cannot inflate inter-annual variability. |
| **8. Ensemble & uncertainty** | Inverse-RMSE ensemble blend, RSS total uncertainty + P50/75/90/99, and named scenarios for comparison. |

Tabs are ordered **Data import → Data cleaning → Analysis Engine → Canvas → Stepper → Results → Copilot → Sensor Overview → Compare → How To**, so the scenario sweep is reached before committing to a single pipeline. The **Canvas** tab renders the full pipeline as an editable React-Flow DAG (run auto/step, snapshots, fork branches) — it is prepared by *Save config and setup* but never executed automatically; the **Results** tab is a read-only aggregate report of everything the session has produced (run overview, measured data, shear, reanalysis, LTC, ensemble & uncertainty, clipping/scenarios — it never triggers computation), the **Sensor Overview** tab is a measured-data validation dashboard, the **Copilot** tab is a BYOK chat that drives backend tools via natural language (the *Allow the assistant to modify this session* setting controls whether it may write as well as read — see [Chat tool authority](#chat-tool-authority)), and the **Compare** tab diffs saved scenarios.

## Quick start

### Backend (MCP server + web API)

```bash
conda activate gokaatru              # Python 3.11+
pip install -e ".[ml,dev]"
python -m server.main                # MCP server (stdio transport)
```

For an SSE server on this machine only:

```bash
python -m server.main --transport sse --host 127.0.0.1 --port 8080
```

The SSE transport has no authentication, and every tool can read and change session data.
`--host 0.0.0.0` exposes all of them to anyone on the network; do not use it outside an
isolated network.

The FastAPI web API (consumed by the frontend) runs separately:

```bash
python -m uvicorn server.api.main:app --host 127.0.0.1 --port 8000
```

### Frontend (web app)

```bash
cd frontend
npm install
npm run dev                          # http://127.0.0.1:5173 (proxies /api → :8000)
```

The workbench is served beside the current interface at `/workbench/` (decisions/0014.9): its
start screen lists the projects, and `/workbench/?project=<id>&campaign=<session id>` opens the
shell on a campaign. Both talk to the same server, so a change made in one shows in the other;
the current interface at `/` is retired at the Phase 3 gate.

The server keeps its sessions and projects under `data/`, or under `GOKAATRU_DATA_DIR` when it
is set (the Playwright backend sets it to `frontend/.e2e-data`).

Production build:

```bash
npm run build                        # tsc --noEmit && vite build → frontend/dist/
npm run test                         # vitest
```

## Project layout

```
server/                 # Python MCP server + FastAPI web API
├── api/                # FastAPI routes (sessions, analysis, brighthub, workflow, …)
├── core/               # executor, regression, spatial, formulas, validators, runconfig contract
├── tools/              # MCP tools: data_io, cleaning, shear, extrapolation, era5, ltc, …
├── state/              # session + dataset pool managers
└── schemas/            # Pydantic models (Coordinate, SensorInfo, PlotResult, …)

frontend/               # React + Vite + TypeScript web app
├── src/
│   ├── components/     # AppHeader, PhaseTabs, Stepper, stages/, results/, WorkflowView, CopilotView, …
│   ├── store/          # useWorkspaceStore (Zustand)
│   ├── lib/            # api, configSync, stages, workflow, copilotAgent, …
│   └── types/          # analysis.ts (config schema + response interfaces)
└── tests/              # backend pytest suite
```

## Web API (consumed by the frontend)

All session-scoped routes require the `X-GoKaatru-Session` header matching the path `{id}`. Errors: `ValueError` → 400, upstream → 502.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/projects` | GET, POST | List projects, most recently changed first; create one (`name`, `site_name`). A project holds the campaigns measured at one site and one reanalysis node cache they share (decisions/0014.11) |
| `/projects/{id}` | GET, PATCH | One project with each campaign's own coordinate and timezone (read from its configuration) and `timezones_differ`, shown and never reconciled; rename it or its site |
| `/projects/{id}/campaigns` | POST | Add a campaign (`name`, `kind`: `mast`, `lidar` or `floating_lidar`): a new session, reopened by its own id after a restart, whose reanalysis nodes are cached in the project |
| `/projects/{id}/campaigns/{session_id}` | PATCH | Rename a campaign |
| `/sessions` | POST | Create a new browser session |
| `/sessions/{id}` | GET | Session summary + `completed_steps` |
| `/sessions/{id}/config` | GET/PUT | Read or update runconfig |
| `/sessions/{id}/config/import` | POST | Import a complete runconfig JSON payload |
| `/sessions/{id}/summary` | GET | Workflow progress and analysis readiness |
| `/sessions/{id}/uploads/{timeseries\|datamodel}` | POST | Upload a file (multipart) |
| `/sessions/{id}/sweep/{sweep_id}/spread` | POST | Decompose one sweep metric's variance across the five scenario axes |
| `/sessions/{id}/datamodel/draft` | GET | Draft a Task 43 reading of the loaded timeseries columns (header inference, for review) |
| `/sessions/{id}/datamodel/build` | POST | Build a minimal Task 43 data model from declared columns, persist it, and load it |
| `/sessions/{id}/sensors` | GET | Sensor inventory |
| `/sessions/{id}/sensors/delete` | POST | Remove sensors from the session (drops their columns; persists `excluded_sensors`). The same logic as `remove_sensors`, which is undoable through the generated route; this one, for the current interface, is not |
| `/sessions/{id}/coverage/{sensor}` | GET | Per-sensor coverage/gap stats |
| `/sessions/{id}/statistics/{sensor}` | GET | Weibull, monthly/diurnal, percentiles |
| `/sessions/{id}/era5/{nodes\|extract\|interpolate}` | POST | ERA5 node discovery, extraction, interpolation |
| `/sessions/{id}/era5/credential` | POST/DELETE | Set or clear this session's EarthDataHub PAT (direct-ERA5 path) |
| `/sessions/{id}/era5/credential/status` | GET | Whether this session has an EarthDataHub PAT configured |
| `/sessions/{id}/shear/{calculate\|table}` | POST | Shear timeseries + 12×24 lookup |
| `/sessions/{id}/roughness/{calculate\|table}` | POST | Log-law roughness equivalents |
| `/sessions/{id}/extrapolation/hub` | POST | Extrapolate measured + reanalysis to hub height |
| `/sessions/{id}/homogeneity/{analyze\|apply}` | POST | Pettitt test + cutoff year |
| `/sessions/{id}/ltc/{algorithm}` | POST | Run one LTC algorithm |
| `/sessions/{id}/ensemble` | POST | Blend LTC algorithms |
| `/sessions/{id}/clipping` | POST | Representative-period analysis |
| `/sessions/{id}/uncertainty` | POST | Total uncertainty + P-factors |
| `/sessions/{id}/scenarios` | GET/POST | List or save scenarios |
| `/sessions/{id}/scenarios/run` | POST | Import config + execute pipeline + save scenario |
| `/sessions/{id}/scenarios/{index}` | DELETE | Remove a saved scenario |
| `/sessions/{id}/plots/{name}` | POST | Generate a named Plotly figure |
| `/sessions/{id}/exports/*` | GET | Download timeseries, LTC, ensemble, or runconfig files |
| `/sessions/{id}/brighthub/*` | various | BrightHub login/locations/import/reanalysis |
| `/sessions/{id}/workflow/{execute,step,status,…}` | various | Workflow canvas execution + snapshots + compare |
| `/sessions/{id}/map/site` | GET | Site-overview GeoJSON (mast + ERA5 nodes) |
| `/sessions/{id}/chat` | POST | BYOK LLM chat proxy with server-side tool execution (read-only by default; see [Chat tool authority](#chat-tool-authority)) |
| `/mcp/catalog` | GET | MCP tool/resource catalog for discovery |
| `/operations` | GET | Every declared operation: effect, stage, canvas, assistant, network, parameters |
| `/sessions/{id}/operations/{name}` | POST | Run one operation; JSON body of its parameters (generated, one route per operation). The OpenAPI schema types every request and result (`<Name>Parameters`, `<Name>Result`), and 400 and 502 as `ErrorDetail`; a float in a result may be null, which is how NaN and infinity are sent |
| `/sessions/{id}/pairs` | GET, POST | A scatter's points as an Arrow stream: `time`, `x`, `y` and, with a `highlight` selection, `highlighted`, described in the schema metadata. Query or body: `x_channel`, `y_channel`, `start`, `end`, `highlight`. The same pairs as `get_scatter_pairs`; not logged as a change. Five years of 10-minute records, 262,800 pairs: 6.3 MB in 14 ms, 59 ms with a 199-vertex lasso highlighted (`python -m tests.measure_series_transport`) |
| `/sessions/{id}/series` | GET, POST | A window of measured channels as an Arrow stream (`application/vnd.apache.arrow.stream`): per-bucket `<channel>.min`, `.max` and `.count` beside `time`, the window described in the schema metadata (`gokaatru`). Query: `channels`, `start`, `end` (UTC offset required), `buckets`, `selection` (a name or an inline definition); POST takes the same fields as a JSON body, for a lasso too long for a URL, and is not logged as a change. The same window as `get_series_window` |
| `/sessions/{id}/operations/{name}/preview` | POST | Dry run with the same body: what the operation would return and change, nothing applied (`apply_cleaning_rule`, `undo_cleaning_rule`, `remove_sensors`) |

## Tool inventory

### Air Density
- `compute_air_density`, `compute_air_density_timeseries`

### BrightHub
- `brighthub_login`, `brighthub_logout`, `brighthub_status`, `brighthub_list_locations`, `brighthub_get_data_model`, `brighthub_import_location`, `brighthub_find_reanalysis_nodes`, `brighthub_download_reanalysis`, `brighthub_prepare_reanalysis`

### Cleaning
- `list_cleaning_rules`, `apply_cleaning_rule`, `get_cleaning_log`, `undo_cleaning_rule`
- `exclude_selection` is the rule a flag drawn on a chart applies (decisions/0014.1): `params` carries the selection's `definition` frozen as an object (never a saved selection's name, which can change), the other columns of the instrument in `sensors` (the drawn column is `sensor`), a `reason` from `icing`, `maintenance`, `instrument_fault`, `mast_or_boom_effect`, `logger_or_transfer_fault`, `suspect`, `other` (`MANUAL_FLAG_REASONS`), and a `note`, required for `other`. One application is one log entry and one undo step whatever the number of columns; the entry adds the definition in words (`description`), the records it held (`selected_records`) and the values set missing by column (`affected_by_sensor`, summed in `records_affected`), and every flag carries the analyst's reason. The period comes from the definition, so `start_date` and `end_date` are refused. Like every rule it re-resolves on replay, against the data as the earlier rules leave it. Where an older rule describes the same records the flags are identical (`tests/test_exclude_selection.py`): a period and `custom_period_exclude` ending on the last record before the drawn end, a box and the same comparisons in `expression_filter`; sectors on the paired vane and `tower_shadow` agree except on the closing edge, which `tower_shadow` includes and a sector does not.

### Clipping And Ensemble
- `run_clipping_analysis`, `run_ensemble`

### Configuration
- `get_run_config`, `update_run_config`, `save_run_config`, `load_run_config`, `get_analysis_summary`

### History
- `remove_sensors` — take sensors out of the analysis: inventory, height mapping (a speed sensor's standard deviation slot goes with it) and the working and raw data, recorded in the run configuration's `excluded_sensors` so a datamodel re-import keeps them out; a new timeseries brings every sensor back. It marks derived results stale. A dry run shows the columns it would drop; the removed columns are kept aside (`removed_sensors`, saved with the project) so undo puts back every field exactly.
- `undo_last_change`, `redo_last_change` — undo the last cleaning rule, configuration change, sensor removal or data model build still in the history, or redo what was undone. Undo refuses when a later change has moved what it would restore; any other change clears what can be redone.
- `get_operation_log` — the most recent operation calls (actor, operation, parameters with credentials redacted, data versions) and the undo state.

### Selections
- `define_selection`, `delete_selection`, `list_selections`, `resolve_selection` — named record selections: time ranges, direction sectors (wrapping through north), value bands on a channel, polygons over two channels (a lasso on a scatter: even-odd rule, at most 1,000 vertices, more is refused), or explicit record sets, combined by union and intersection. Bounds are half-open (a point on a polygon's left or lower edge is inside, on its right or upper edge outside) and a missing value is never selected. The server resolves a selection against the working data each time it is used, so every view counts the same records.
- 24 statistics, charts and the series window, all reading the measured records, take a `selection` parameter (`selectable: true` in `GET /operations`): the Weibull, wind-climate, turbulence, windrose, diurnal, monthly, MoMM and scatter statistics, energy metrics, ramps, persistence, sensor comparison, mast effects, QC diagnostics, vertical structure and sector shear tables, the windrose, Weibull, diurnal, scatter, time-series and monthly-mean charts, and `get_series_window`. It is a saved selection's name, or a definition sent inline as a JSON object (the browser's live brushing): a read on an inline definition is not written to the operation log, because it is view state with nothing to trace, and a saved selection's name cannot start with `{`. The operation then runs with every record outside the selection missing, and its result carries a `selection` block (below). Reads of stored results, the long-term series, the reanalysis or the data inventory take none; `tests/test_selection_operations.py` lists each with the reason.

### Scenario sweep (Analysis Engine)
- `get_fixed_prefix_hash`, `list_sweeps`, `get_sweep_summary`, `analyze_sweep_spread`
- The rest of the sweep engine remains HTTP-only; these four are the read surface an
  assistant needs to answer questions about a completed sweep instead of guessing.

### Data I/O
- `parse_timeseries`, `parse_datamodel`, `list_sensors`, `get_period_of_record`, `get_data_coverage`
- Data model builder, for a campaign delivered as a bare CSV with no IEA Task 43 JSON:
  `draft_data_model`, `build_data_model`. The draft also reports the data model in use (`in_use`: its file, whether the builder wrote it, and the spec it was built from). Building again from an edited spec is how the workbench's mast diagram edits a data model: it marks derived results stale, and `undo_last_change` puts back the mapping, inventory, timezone, document and run-configuration paths. Two builds are refused: any build while the campaign's own uploaded data model is in use (decisions/0014.8: shown, never changed), and undo of the build that first puts the records into UTC, which would move every timestamp. A data model of any origin whose timezone differs from the one the records were put into UTC with is refused; load the timeseries again to apply another. A refused build leaves the document on disk as it was.

### ERA5 And Reanalysis
- `find_era5_nodes`, `extract_era5_data`, `compute_era5_wind_speed`, `interpolate_era5_to_site`, `extrapolate_reanalysis_to_hub`, `analyze_homogeneity`, `apply_homogeneity_cutoff`
- Direct-ERA5 (EarthDataHub) credential, session-scoped like the BrightHub login above: `earthdatahub_set_credential`, `earthdatahub_clear_credential`, `earthdatahub_status`

### Extrapolation And Shear
- `extrapolate_to_hub_height`, `calculate_shear_timeseries`, `calculate_roughness_timeseries`, `build_shear_table`, `build_roughness_table`, `build_sector_shear_tables`, `build_aggr_momm_shear_table`

### Long-Term Correction
- `run_ltc_linear_least_squares`, `run_ltc_total_least_squares`, `run_ltc_speedsort`, `run_ltc_variance_ratio`, `run_ltc_xgboost`

### Mapping
- `get_mast_marker`, `get_era5_node_markers`, `get_site_overview_map`

### Statistics
- `compute_weibull_params`, `compute_wind_climate`, `compute_windrose_data`, `compute_diurnal_profile`, `compute_monthly_stats`, `compute_turbulence_intensity`, `compute_turbulence_analysis`, `compute_momm`, `compute_scatter_stats`, `calculate_uncertainty`, `compute_energy_sensitivity`

### Diagnostics (Sensor Overview)
- `compute_qc_diagnostics`, `compute_sensor_comparison`, `compute_mast_effects`, `compute_mcp_readiness`, `compute_vertical_structure`

### Advanced analysis
- `compute_energy_metrics`, `compute_extreme_winds`, `compute_wind_persistence`, `compute_wind_ramps`

### Visualization
- `plot_windrose`, `plot_weibull`, `plot_diurnal`, `plot_scatter`, `plot_timeseries`, `plot_data_coverage`, `plot_shear_table`, `plot_monthly_means`, `plot_ltc_comparison`, `plot_annual_means`, `plot_uncertainty_breakdown`
- `get_series_window` — measured channels over a half-open window, reduced on the server to at most `buckets` equal-width time buckets (default 2000), each with every channel's minimum, maximum and valid count, so the band a chart draws is the data's exact envelope. A window of no more records than buckets is returned record by record; zoom by asking for a narrower window. The interface reads the same window as Arrow from `GET /sessions/{id}/series`.
- `get_scatter_pairs` — every record of a half-open window where two channels are both valid, as time, x and y, for a scatter. `highlight` is a selection (a saved name or an inline definition) whose records are marked in `highlighted` rather than removed, so the scatter still draws every point. The JSON form is refused past a leap year of 10-minute records (`MAX_JSON_PAIRS` = 52,704); the interface reads the same pairs as Arrow from `/sessions/{id}/pairs`, which has no limit.
- `get_flag_intervals` — the cleaning flags of measured channels over a half-open window, as intervals of consecutive working records flagged by one rule application, each with its rule, reason, actor and time and `next`, the record where its band ends. Per channel `flagged_records` counts every flag in the window. Expanding the intervals gives the flag table back exactly.

Additional figures are reachable through `POST /sessions/{id}/plots/{name}` without being MCP tools in their own right — including `shear_profile`, `shear_timeseries`, `era5_scatter`, `mast_shadow`, `qc_flags`, `ltc_scatter`, `ltc_residuals`, `ltc_monthly`, `ltc_convergence`, and `uncertainty_tornado`.

### WindKit

GoKaatru uses DTU's [WindKit](https://pypi.org/project/windkit/), pinned to exactly 2.2.0,
only where it is the reference implementation, and exposes none of it as a tool of its own
([decisions/0009](decisions/0009-operation-registry.md)). Today that is the WAsP mean and
third-moment Weibull fit behind `compute_weibull_params` (`method="wasp_m1_m3"`, the default)
and the wind-climate statistics. Its two sectorwise long-term corrections
are not used in any result; `tests/test_windkit_adopted.py` runs them as a second
implementation that the native variance-ratio and linear corrections are checked against.
The WAsP TAB writer, the windIO and turbine-file readers, and direction interpolation to hub
height are adopted for later work and enter the registry when that work is built.

The 142 pass-through wrappers that exposed WindKit's API one function at a time were removed
on 2026-11-19. No pipeline stage called them and the assistant could not reach them. The two
long-term correction wrappers were broken: on 2.0.1 every call raised inside WindKit, and they
passed the measured series where WindKit expects the reference, which on 2.2.0 would have
returned a long-term mean 38.9% low on a synthetic year.

## Methodology, defaults and disclosure

Choices that change reported numbers are listed here, because they are the ones a
reviewer needs in order to reconcile GoKaatru against WAsP, Windographer or an
earlier GoKaatru run. Wherever a choice has a runtime consequence, the tool
response carries the resolved value alongside the result, so the numbers travel
with their basis rather than depending on a reader finding this page.

### Refusals — where GoKaatru declines to produce a number

These raise rather than returning a value, on the reasoning that a number
invites use:

| Condition | Why |
|---|---|
| Fewer than **4 380 valid concurrent records** (six months) for any LTC algorithm | A sub-six-month MCP is not defensible. Counted as valid concurrent *pairs*, not calendar span, so a gappy nine-month overlap is judged on the data it actually contains. This also rejects coarse-cadence references: a five-year monthly series is 60 pairs. |
| Fewer than **six complete annual means** for clipping | After the completeness gate below. |
| Inferred timestep not in `{1, 2, 5, 10, 15, 30, 60}` minutes | A silently repaired cadence propagates into gap statistics, diurnal aggregation and ERA5 alignment with no trace. |
| Datamodel declares no timezone | A wrong assumption here is silent and corrupts every LTC. Provide `timezone` (IANA) or `offset_from_utc_hrs` in `logger_main_config`. The data model builder refuses to emit a document without one, for the same reason. |
| No hub-height series when an LTC is requested | The LTC corrects the series at the height the answer is reported at. Correcting a raw sensor instead publishes a measurement from a different height under a hub-height label, which nothing downstream can detect. Extrapolate to hub height first; the refusal names the missing column. |
| A built data model column with no declared height | `build_data_model` names the column instead of defaulting. 0 m is a real height, and a sensor silently placed on the ground is not detectable in any downstream result. |
| Degenerate (vertical) relationship in total least squares | The slope is genuinely undefined; the old code returned a `1e12` sentinel. |
| Unknown `shear_method` on `calculate_uncertainty` | The MCP tool has no Pydantic layer, so an unknown name used to fall through silently to the 0.03 power-law constant. It now raises, naming the valid values (`VALID_SHEAR_METHODS`: `calculate_shear`, `simple_power_law`, `log_law`, `analyst_supplied`, `power_law`), the same set the HTTP schema accepts. |

### Defaults that affect results

| Setting | Default | Notes |
|---|---|---|
| Weibull fit | **WAsP m1/m3** moment method | Matches the 1st and 3rd moments so mean *and* energy content are preserved — the wind-industry convention, and what WAsP/Windographer report. Moments are taken over the **full** series including calms. MLE remains available via `method="mle"`, which must exclude zeros. Expect roughly **k −0.1 and A −0.25** versus MLE on typical data. |
| Shear valid-record gate | **3.0 m/s** (`min_speed_mps`) | Persisted to `runconfig.shear.minSpeedMps`. Raising it from the old 0.1 m/s removes near-calm records whose `ln(v₂/v₁)` is noise; on a real two-year lidar campaign this dropped 5% of records and cut shear σ from 0.168 to 0.149. The gate governs the **fit** only. `extrapolate_to_hub_height` still extrapolates a record below it with the table's exponent, because leaving it out truncated the hub series (Launakalana at 120 m: 25% of records lost, long-term mean +5.8% to +12.8%). Such records are counted in `method_counts.below_shear_gate` and `records_below_extrapolation_gate`, and reported in `extrapolation_gate_warning`. Held-out check on real campaigns with the sub-gate records kept: Launakalana 80 m from 40/60 m -0.43%, Boxkite 250 m from 180/200 m -0.40% (`tests/test_heldout_height.py`). |
| Clipping year completeness | **0.9** (`min_year_completeness`) | Leap-aware, measured against the series' own cadence. |
| Reusing a cached BrightHub node | **Reused when its series reaches the campaign's last measured record** | A node is cached by dataset and coordinate, in the project's shared cache for a campaign in one (decisions/0014.11), in the session's own otherwise. The long-term correction needs the reference over the concurrent period, so a cached node that ends before the campaign's last record, or any node before a record is loaded, is downloaded again. A cached node is otherwise never refreshed: values still preliminary (ERA5T) when it was downloaded are not revised. Each node reports `cache` (`hit`, `downloaded`, `empty`) and `cached_through`. A full hit needs no BrightHub login. |
| SpeedSort binning | **12 sectors × 30°**, min **200** records/sector | Sparse sectors fall back to the all-sector fit; `independent_sectors` and the per-sector `sector_models` report where the fit is thin. |
| Mast-shadow speed gate | **4.0 m/s**, min **50** records/sector | Detection is two-sided: a low ratio means `sensor_b` is shadowed, a high ratio means `sensor_a` is. Sparse sectors are reported but not flagged. |
| MCP readiness thresholds | **4,380 concurrent hours** (`MIN_CONCURRENT_HOURS`, the correction's own floor), **R² ≥ 0.5** (`READINESS_MIN_R_SQUARED`) | `compute_mcp_readiness` used a 720-hour floor, so it could report `ready` for a series long-term correction then refused. It now imports the correction's floor. The R² threshold is a diagnostic cue only: the sweep's R² admissibility gate was removed as biased against non-least-squares methods. |
| `range_check` bounds | **Derived from sensor type** | wind_speed 0–50 m/s, wind_direction 0–360°, temperature −60–60 °C, pressure 80 000–110 000 Pa, humidity 0–100%. An unknown type falls back to that sensor's own data range, which makes the rule a **no-op** — an intentional fail-safe, reported as `bounds_source: "sensor_data_range"`. Explicit `min`/`max` always win. |
| LTC measured column | **The hub-height series**, refused if absent | Was "the highest-height speed sensor in `sensor_mapping`" — and a hub column is never in that mapping (extrapolation appends it to `timeseries_df`), so the resolver could not return one at any site. The sweep therefore computed the hub series and discarded it, fitting every LTC on the top sensor. Measured on a 167 m lidar campaign with sensors at 140/160/180/200 m: the LTC ran on `Spd_200m`, whose measured level is **+0.185 m/s (+2.05%)** above the 167 m hub level (9.2166 vs 9.0316 m/s), and that level propagated into `long_term_mean_speed_mps`, the indicative AEP and the capacity factor. It also made axes A1, A2 and B unable to move any published metric, because everything downstream of the shear and extrapolation stages was bypassed — the Interrogate page attributed 100% of the spread to the LTC axis, the only axis still able to vary. |
| SpeedSort directional binning in a sweep | **On** (12 sectors × 30°) | The sweep called every non-XGBoost algorithm as `runner(state, short, long)`, so SpeedSort's `long_dir_col` defaulted to empty and it ran direction-agnostically in every sweep ever executed, losing the per-sector transfer functions that are the reason to choose it — while XGBoost kept its directional feature, so axis D compared them on unequal terms. All three dispatch sites now share `DIRECTIONAL_LTC_ALGORITHMS`. |
| Variance-decomposition axis with one level | **0% share, reported with `levels`** | An axis that was not varied has its group mean equal to the grand mean, so its between-group sum of squares is exactly zero. That renders identically to "this choice was tested and does not matter", which is a much stronger claim — so the level count travels with every share, and `single_level_axes` names them explicitly. |
| Boom-pair tie-break | **Alphabetical**, after coverage | Resolution order is unchanged — primary flag, then coverage, then name — but a coverage *tie* now falls through to the name instead of keeping whichever candidate the document happened to list first. Ties are the normal case, not a corner one: every boom pair in Horns Rev and Launakalana ties exactly, because both booms are logged on one channel schedule. Ordering therefore decided the mast's representative sensor, worth **+1.15%** of mean wind speed at Horns Rev 30 m (8.302 → 8.398 m/s) and **−0.21%** at Launakalana 60 m. Reported as `resolution: "coverage_tie_name_alphabetical"` in `runconfig.site.sensor_resolution`, distinct from `"coverage"`, so a coverage figure that decided nothing does not read as if it had. |
| Turbulence (`sd_col`) column | **Declared column if present, else `{speed}_sd` if present, else none** | Previously `f"{speed}_sd"` unconditionally, whether or not such a column was ever logged — Boxkite's mapping named `Spd_250m_sd` against a CSV with no standard-deviation channels at all. Inert downstream (the icing rule skips a column it cannot find) but it travelled into `runconfig` as fact. A Task 43 `logger_measurement_config[].column_name` declaration with `statistic_type_id: "sd"` is now preferred, **but only when that column exists in the loaded data**: Horns Rev declares `wind_speed__sd__062__…` while its CSV holds `Spd_62m_sd`, so trusting declarations blindly would lose a real column. With no timeseries loaded yet, existence cannot be checked and the suffix convention still applies. |
| Built data model provenance | **Recorded in the artifact** | A data model produced by `build_data_model` carries a note on its `measurement_location` stating that column roles and heights were drafted by header inference and declared by the analyst, not taken from an instrument record. Nothing is defaulted during a build: a column with no readable height, an unknown measurement type, a duplicate name, a statistic column absent from the data, or a missing timezone is refused by name rather than filled in. |
| ERA5 spatial interpolation | **Scalar** for speed, **vector** for direction | Deliberately different. Vector interpolation of speed under-predicts where node directions diverge across the cell, because opposing components cancel. Reported as `speed_interpolation: "scalar"`. |
| Long-term reference | **ERA5** (`source` on `interpolate_era5_to_site`) | `"merra2"` selects the other downloaded reanalysis. Both write the same interpolated series every LTC algorithm reads, so switching source and repeating the LTC is how a result's dependence on the reference is tested. Reported as `reference_source`. |
| Timestamp interval label | **`interval_start`** (`runconfig.timestamp_label`) | IEA Task 43 permits start, end and centre labelling and a file does not say which it uses, so this is an assumption. Set it to `interval_end` or `interval_centre` and the measured index is shifted onto interval-start before matching — a mismatch against instantaneous reanalysis is a systematic half-interval offset in every LTC, not noise. |
| Hourly resample coverage | **0.5** of expected sub-hourly samples | A 3-of-6 hour is kept and averaged as a full hour; a 1-of-6 hour is dropped. Reported as `hours_kept`, `hours_dropped_below_minimum` and `hours_kept_partially_populated`. |
| `availability_90` denominator | **The sensor's own deployed period** | Was the *total* record count, which charged every sensor for the campaign before it was installed. On Horns Rev — where `Spd_58m` predates the rest of the mast by ~13 months — the best sensor read **87.1%** and *no* sensor cleared the 90% floor, so axis A silently lost a level on an ordinary campaign; measured over each sensor's own deployment the best reads **100.0%** and **4 of 5** clear it. The window comes from the Task 43 datamodel's sensor `date_from`/`date_to` where present, else the column's own first-to-last record; `availability_basis` reports which, because the two are not comparable. Boxkite is **unchanged at 89.7%** — its losses are real scattered gaps, not late installation, so it still fails the floor and should. |
| Sector shear minimum | **200** records/sector | Matches the SpeedSort gate. Below it a sector is not tabulated, because 20 records produced a 288-cell table of which 285 were that sector's own mean. Every sector's count and the reason for each exclusion are reported; overridable via `min_sector_records`. |
| Roughness band | **[1e-6, 2.0] m** | The ceiling covers WAsP class 3 and dense forest or urban terrain. It was 1.5 m, which truncated them — and the clamp *raises* log-law hub speed, so it was not a conservative backstop. |
| Tower-shadow sector | **Derived per sensor** | Boom orientation from the datamodel (shadow centred at boom + 180 deg, width 70 deg), else the sectors `compute_mast_effects` measured, else the legacy 20-degree window at 170-190 deg — which reports `sector_basis: "default_guess"` and warns that it is about a third of a lattice tower's real shadow. |
| Icing conditions | **Speed SD + temperature + held vane** | A cold, steady flow satisfies the first two. The paired direction column must also be stationary within 5 deg over a three-record window. With no direction column mapped the test is skipped and the response says so. |
| MCP concurrent-months cap | **12** (`concurrent_months_cap`) | The `3/sqrt(months)` sampling term stops improving here, because beyond about a year the limit on an MCP is the stability of the transfer function rather than the number of pairs. `mcp_sampling_cap` reports the uncapped figure and the credit withheld. |
| Project life | **20 years** (`project_life_years`) | `u_future = iav / sqrt(life)`. A 15-year life gives 1.55% where 20 years gives 1.34% for the same 6% IAV. |
| Vertical shear constant, assumed power law | **0.03** (`K_SHEAR_ASSUMED_POWER_LAW`) | Interim (decision D2, 2026-11-14, pending owner sign-off). Used for `simple_power_law` and for a fitted profile with no measured dispersion. A fitted profile takes `min(measured shear scatter, 0.03)`, so measuring can lower `u_vert` but never raise it above the assumed value. Reported as `inputs.k_shear` and `inputs.k_shear_basis`. |
| Vertical shear constant, log law | **0.07** (`K_SHEAR_LOG_LAW`) | Raised from 0.05 on 2026-11-16 (owner decision D2). Held-out height error for the log law measured 0.065 pooled and 0.070 in the worst year at Launakalana, 0.038 and 0.069 at Boxkite, so 0.05 understated a single-year campaign at both sites. Same heights (80 m measurement, 120 m hub): 2.03% → 2.84%. Used when `shear_method` is `log_law`, which `derive_uncertainty_inputs` selects for any roughness-derived profile with no power-law shear table. |
| Vertical shear constant, analyst-supplied exponent | **0.07** (`K_SHEAR_ANALYST_SUPPLIED`) | Raised from 0.05 on 2026-11-17 (owner decision) to match the log-law constant. Used for `shear_method: "analyst_supplied"`, which an analyst-typed exponent takes. It has no measured dispersion, so it takes the largest of the assumed constants and never scores better than the log law. Same heights (80 m measurement, 120 m hub), formula values: fitted 1.22%, assumed 1.22%, log law 2.84%, analyst-supplied 2.84% (was 2.03%). The evidence-based vertical term that replaces these constants is not built. |
| Sweep uncertainty substitution | **Sample std of level means, ≥ 3 levels** (`MIN_LEVELS_FOR_EMPIRICAL`, `server/core/sweep_analysis.py`) | Owner decision 2026-11-17 (F9). An axis's empirical term is the sample standard deviation of the long-term mean speed across its level means, as a percentage of the sweep's mean speed; a component measured by several axes combines them in quadrature. Per scenario, `max(parametric, empirical)` replaces the MCP and vertical terms and the reference-source spread is added. An axis with fewer than 3 levels gives nothing, so with two reanalyses the reference-source term never fires. Until 2026-11-18 this was computed only in the browser, from the swing of `total_uncertainty_pct`; on the two stored sweeps the LTC term moved 0.30% → 0.55% and 0.24% → 1.76%, and 4 of 40 scenario totals rose (minimum 3.134% → 3.146%). |
| Uncertainty combination | **Pure quadrature** (`component_correlation = 0`) | Measurement, vertical extrapolation and MCP all derive from the same measured series, so independence is optimistic. Every response reports the total at rho = 0.5 alongside — about 30% higher — so the size of the assumption is visible. |
| Clipping window floor | **10 years** (`min_window_years`) | Every candidate window ends at the final year and so contains the 5-year reference period; the shortest candidate *is* that period, with deviation exactly zero and its climate term pinned at the minimum. Without a floor a 10-year record selected 6 years. The unconstrained optimum is still reported. |
| Date order | **Determined from the data** (`runconfig.dayfirst`) | Whichever of DD/MM and MM/DD parses more rows wins, because any day above 12 settles it. Where every day is 12 or below neither reading parses more, ingest **refuses** rather than guessing, and `dayfirst` resolves it. ISO-8601 avoids the question. |
| SpeedSort dog-leg threshold | **Half the concurrent reference mean**, capped at 4 m/s | Both the directional and non-directional paths use the concurrent mean; they previously disagreed by 2% on the same data. Reported as `threshold_basis`. |
| Atmospheric stability | **Neutral profile** | No Monin-Obukhov length, Richardson number or stability class exists anywhere. The 12x24 month-hour shear table is the empirical stability proxy, capturing the diurnal and seasonal signature of stability rather than modelling it. Reported as `stability_treatment`. |
| Turbulence speed gate | **3.0 m/s** (`min_speed_mps`) | Shared by both TI tools. Below cut-in, sigma/U is the ratio of two small numbers; the two tools previously gated at 3 and 0 m/s and published TI figures 13.8% apart under the same key. Reported as `speed_gate_mps`. |
| Turbulence bin minimum | **20** records | A bin thinner than this cannot support a mean plus 1.28 standard deviations. Every bin reports its count and `sufficient_records`. |
| Representative TI | **Population-weighted** across bins | An unweighted mean gave a 1-record bin at 29 m/s the same weight as a 4 900-record bin at 5 m/s — 0.173 against 0.211. `representative_ti_unweighted` is retained. |
| Extreme-wind series | **`auto`** (`source`) | Prefers the long-term corrected series (ensemble, then any LTC result) over the measured campaign. A 50-year level from 2 annual maxima extrapolates 25x beyond its data; from 20 years, 2.5x. Reported as `series_basis`. |
| Extreme-wind year coverage | **0.9** (`min_year_coverage`) | The fraction of a calendar year's **days** holding at least one record — not record completeness, which cannot tell a partial season from ordinary sensor downtime (85% scattered recovery scores 84.93% on completeness and 100% on day coverage). A partial year moved V50 by up to +40.9%. |
| GEV minimum years | **10** annual maxima | Below this the three-parameter GEV is not fitted at all, because it is not identifiable: measured across twelve two-year campaigns, every fit either collapsed onto the observed data or diverged past 1e9 m/s. The two-parameter Gumbel fit is still reported. |
| Climate deviation exponent | **5** (`climate_deviation_exponent`) | Undocumented in the source methodology and dominant in the objective's shape: the term stays within 3% of its floor until deviation reaches ~0.6. Every response carries a sweep over 1, 2, 3, 5 and 8 showing which window each would have selected. |

### Disclosure fields — read these before trusting a number

Each field below is declared on the operation that returns it (`disclosure` in
`server/operations.py`). `tests/test_disclosure_fields.py` checks this table against those
declarations in both directions, and runs a synthetic pipeline to find every declared field
in its operation's response.

| Field | Appears in | Meaning |
|---|---|---|
| `records_clamped`, `clamped_fraction` | every shear response | How often α hit the [−1, 1] backstop. A clamped α = 1.0 turns 8.7 m/s at 150 m into 15.0 m/s. Above 5% the response carries an explicit `warning`. |
| `measured_resampled_to_hourly`, `resampling_note` | every LTC response | Measured data is averaged to hourly means while the reanalysis reference is instantaneous. This removes within-hour variance from the measured side only, biasing `variance_ratio` low. Slope-based methods are far less affected. |
| `fit_basis` | `run_ltc_speedsort` | `"rank_sorted"`: the SpeedSort fit pairs sorted reference and measured speeds, not time-paired records. Stored sweeps and LTC results from before 2026-11-14 used the time-paired fit and are not comparable. |
| `negative_predictions_clipped` | every LTC response | Corrected speeds truncated at zero. A non-trivial count means the transfer function is bad. |
| `n_above_training_max`, `fraction_above_training_max` | `run_ltc_xgboost` | Long-term records above the campaign maximum. Trees are piecewise-constant and cannot extrapolate, so these collapse onto the model's highest leaf. **Do not use XGBoost alone for extreme-wind estimation** — it biases GEV/Gumbel annual maxima low. |
| `years_used`, `years_excluded`, `excluded_reason` | `run_clipping_analysis` | Which calendar years passed the completeness gate. |
| `calm_fraction`, `fit_excludes_calms`, `fit_method` | `compute_weibull_params` | `mean_speed` is always the **full-series** mean including calms, consistent with MoMM and the monthly means. |
| `ready`, `not_ready_reasons`, `min_concurrent_hours`, `min_r_squared` | `compute_mcp_readiness` | The thresholds used and one reason string per failed condition (measured value and threshold); empty when ready. |
| `range_failures`, `range_min`, `range_max`, `range_bounds_source` | `compute_qc_diagnostics` (per sensor) | Failures are counted against the bounds `range_check` would apply to that sensor (`_resolve_range_bounds`, no explicit min/max), where it was a fixed 0-50 for every speed sensor. `range_bounds_source: "sensor_data_range"` means the type is unknown, the bounds are the data's own range and the count is necessarily 0. |
| `bounds_source`, `min_applied`, `max_applied` | `apply_cleaning_rule` (`range_check`) | The bounds actually applied, recorded in the cleaning log so it cannot imply a check that did not happen. |
| `weights`, `weight_basis` | `run_ensemble` | Inverse-RMSE component weights, using each algorithm's **out-of-sample** RMSE where it reports one (currently XGBoost only) and its overlap RMSE otherwise. `weight_basis` labels which each component used and `weight_basis_is_mixed` flags the mixture, because in-sample error is systematically lower and tilts the blend for reasons unrelated to skill. |
| `component_spread` | `run_ensemble` | Per-timestamp disagreement between the bias-corrected components. Level disagreement is already removed by the bias correction, so this is **shape** disagreement — an empirical estimate of LTC model uncertainty, which the uncertainty model does not otherwise carry. Reported, not folded into the total. |
| `out_of_sample_basis`, `cv_fold_reports`, `cv_rmse_spread` | `run_ltc_xgboost` | The held-out error is the out-of-fold error over four contiguous blocks spanning the whole concurrent period, not a terminal 20% slice — which on a one-year campaign covered October to December only, a +17.7% seasonal offset. A large `cv_rmse_spread` means the model's skill depends on the season. |
| `estimator`, `huber_delta` | `run_ltc_linear_least_squares` | The fit is **Huber IRLS at δ = 1.35**, not ordinary least squares, despite the tool name. Huber is the better estimator under contamination, but the slope will not reconcile exactly against an OLS fit in WAsP, windPRO or Windographer. |
| `error_variance_ratio_assumed` | `run_ltc_total_least_squares` | TLS assumes equal error variance in both series. Reanalysis error greatly exceeds mast error, so TLS overshoots the slope (measured 1.138 against a true 1.080) and OLS undershoots. Treat the two as bracketing the answer rather than as peers. |
| `variance_ratio_to_reference` | every LTC response | How much of the reference's variance the transfer function retained. Slope methods attenuate it; `variance_ratio` preserves it by construction. The spread reached ~10% of IAV across algorithms, which flows into `u_future` and the clipping objective. |
| `duplicate_timestamps` | `parse_timeseries` | Repeated timestamps found and collapsed by averaging. Left in place they were counted twice by every month-hour grouping downstream. |
| `hour_basis`, `site_utc_offset_hours` | diurnal profile, shear/roughness/sector tables | Hour-of-day bins count **UTC** hours. Bins and lookups share the clock so the physics is self-consistent, but a 14:00 local peak at UTC+5:30 appears at 08:30. The diurnal profile also returns `hours_local`. |
| `order_dependence` | `apply_cleaning_rule` | Which rules already touched this sensor. Rule order is material — `stuck_sensor` then `icing_filter` removed 10 records where the reverse removed 2, on the same data. |
| `below_shear_gate`, `records_below_extrapolation_gate` | `extrapolate_to_hub_height` | Records whose reference speed sits below the 3.0 m/s shear gate. They **are** extrapolated and included in the hub series; the count is informational, so a reader can see how much of the hub series rests on the table's exponent outside the speeds it was fitted on. `method_counts.extrapolated` includes them. |
| `method_models`, `method_is_mixed` | `extrapolate_to_hub_height` | Which physical model produced each hub record. Inside the mast range it is linear interpolation in ln(z); outside it is the shear or roughness table. A series with counts in both rows is a blend of two models. |
| `mcp_sampling_cap`, `combination` | `calculate_uncertainty` | What the 12-month cap withheld, and what the independence assumption costs at ρ = 0.5. |
| `k_shear`, `k_shear_basis` | `calculate_uncertainty` (`inputs`) | The shear constant the vertical term used and which branch supplied it: `measured_dispersion` or `measured_dispersion_capped` (fitted, the cap at 0.03 firing when the scatter exceeds it), `assumed_power_law`, `log_law`, `analyst_supplied`, or `not_applied_*` for interpolated or invalid heights (then `k_shear` is null). Interim rule, decision D2 (2026-11-14). |
| `method_by_variable`, `skipped_variables` | `interpolate_era5_to_site` | Which interpolation each variable actually used, rather than one label collapsed to "idw" if any variable fell back; and any variable dropped because a node does not carry it, with the nodes responsible. Dew point feeds air density and temperature/pressure feed the XGBoost features, so a silent drop surfaces later as an unrelated missing-column error. |
| `alpha_reclamped_records`, `stability_treatment` | `extrapolate_to_hub_height` | Records whose shear exponent hit the [-1, 1] clamp before extrapolation — normally zero, but reachable through the fallback fill and the aggregate MoMM path, and a clamp that fires changes the hub speed. And the standing neutral-profile assumption. |
| `reference_temporal_semantics` | every LTC response | Whether the reference is instantaneous (ERA5) or time-averaged (MERRA-2). The resampling note differs between them: the one-sided variance loss that biases variance-ratio results applies only against an instantaneous reference. |
| `reference_height_m.record_counts` | `extrapolate_to_hub_height` | The reference height is chosen per record and drops to a lower sensor whenever the top one is missing; `min`/`max`/`most_common` alone cannot distinguish "one record fell back" from "a quarter of the campaign did". `record_counts` gives the full distribution across every height actually used. |
| `fallback_alpha`/`fallback_z0`, `fallback_source`, `table_coverage` | `build_shear_table`, `build_roughness_table`, `build_aggr_momm_shear_table` | The value substituted into any month-hour cell the campaign never observed — the campaign's own mean (`"series_mean"`), or, only when every cell is empty, a hardcoded generic default (`"one_seventh_power_law_default"` / `"open_water_default"`) — and how much of the table is fill. All three table-building tools now report the same fields; the roughness and aggregate-MoMM paths previously reported neither. |
| `iec_ti_at_15ms`, `iec_ti_bin_mps`, `iec_ti_bin_records` | `compute_turbulence_analysis` | Representative turbulence in the 1 m/s bin containing 15 m/s, which selects the IEC turbulence class (Iref 0.16 / 0.14 / 0.12 for A / B / C). The bin actually used and its record count travel with it, because a low-wind campaign may never reach 15 m/s — in which case the response says so and the class cannot be selected from it. |
| `gev.available`, `plausible`, `below_largest_observed` | `compute_extreme_winds` | Whether the GEV fit was performed at all, whether each fit's return levels are usable (divergent, or collapsed so that V100 is no higher than V50), and whether V50 sits below the largest observed annual maximum. The last is a cue, not a failure: the largest of twenty maxima is roughly a twenty-year event. |
| `years_excluded`, `min_year_coverage` | `compute_extreme_winds` | Calendar years covering too little of the calendar to hold an annual maximum, with their day coverage, months and the partial maximum they would have contributed. |
| `density_normalisation` | `calculate_uncertainty`, `compute_energy_sensitivity` | Whether speeds were normalised to the power curve's reference density before the sensitivity factor was measured, as `U*(rho/rho0)^(1/3)`: the IEC 61400-12-1 treatment for a pitch-regulated turbine (`turbine_regulation: "pitch"`, `method: "iec_61400_12_1_wind_speed_normalisation"`; the method was labelled `iec_61400_12_1_stall` before 2026-11-17, with the same arithmetic). Requires a recorded site density; without one it reports `applied: false` rather than assuming standard conditions. |
| `upstream_processing` | `brighthub_import_location` | BrightHub cleaning, calibration and offsets applied **before** GoKaatru saw the data. Recorded as a non-undoable entry at the head of the cleaning log: coverage and recovery figures describe the data as received, not the raw campaign. |
| `engine_version` | sweep `manifest.json`, `get_sweep_summary`, `fixed_prefix_hash` | The engine release that produced the numbers (`ENGINE_VERSION`, currently `"2026.11.2"`), also hashed into the fixed-prefix hash, so every config hash moves with it. Sweeps stored before the stamp read as `null`. The 2026.11 changes (sub-gate records extrapolated, SpeedSort rank-sorted fit, interim vertical-uncertainty rule) moved the numbers, so a `null` or older version is not comparable with a current sweep. Re-run rather than compare. |
| `duplicates_skipped` | sweep `manifest.json` (`counts.duplicates_skipped`) | Leaves that resolved to the same computation as an earlier leaf and were **not run**. The computation is identified by the resolved sensor columns for the shear-fit and extrapolation-reference policies, plus shear model, reference source, LTC algorithm, hub height and any analyst exponent, so two policy names that pick the same sensors on this mast run once. Each entry names the two policies and `same_as`, the `config_hash` of the row that was run. A skipped duplicate has no row of its own. `planned` = `completed` + `failed` + `duplicates_skipped` on a sweep that was not stopped early. Only completed runs are matched against: if the first of two identical leaves fails, the second runs. Stored sweeps from before 2026-11-14 hashed the policy names and are not comparable on `config_hash`. |
| `duplicate_levels` | `get_sweep_summary` (`axes.<axis>.duplicate_levels`), `analyze_sweep_spread` / `POST .../spread` (`contributions[].duplicate_levels`) | For the two policy axes, each level whose leaves were skipped as duplicates, the level whose rows it shares (`same_as`) and how many scenarios that covers. Such a level has no rows, so it is absent from `levels_admissible` and the decomposition's `levels`; without this field an axis varied between two policies that picked the same sensors reads as "not varied". `levels_designed` includes it. Only duplicates of rows in view count: a filtered or inadmissible `same_as` row drops its duplicates too. The Interrogate page shows it as "same sensors: <level> = <level>", and the Run monitor's Outcome panel shows `counts.duplicates_skipped`. |
| `uncertainty_substitution` | `analyze_sweep_spread` / `POST .../spread` | Per component: the parametric mean, the sweep's empirical term, the value applied and its `basis` (`empirical`, `parametric`, `added`, `not_resolved`), and which axes were used, under-resolved (two levels) or not varied. Per sweep: the distribution of scenario totals with and without the substitution, how many it raised, and how many lacked a parametric component and were left out. Computed over the caller's row selection. The scenario rows' own `total_uncertainty_pct` is unchanged. |
| `is_interpolation` (`inputs`, `provenance.is_interpolation`) | `derive_uncertainty_inputs` | Whether hub height sits inside the profile the scenario extrapolated from: its own reference heights (axis A2) when given, otherwise every mapped height. A scenario restricted to sensors below hub is extrapolating even when another sensor sits above hub, so it takes the extrapolated vertical term rather than the 1% interpolated one. |
| `extrapolate_reanalysis`, `reanalysis_status` | `extrapolate_to_hub_height` (sweep stage detail) | Sweep leaves pass `extrapolate_reanalysis=False`: the eight reanalysis node frames are not carried to hub height and the stage reports `reanalysis_status: "not_run"`. The reanalysis response reads `{"status": "skipped", "reason": "not_requested", "wrote_hub_column": false}`. The sweep's LTC reads the native `Spd_100m` / `Spd_50m` columns, so no reported number changes (68 rows identical before and after, 2026-11-14). The MCP tool and HTTP route still default to extrapolating. |
| `selection` | every selectable operation, when a selection is given | Its `name` (`null` with `inline: true` for a definition sent inline), how many of the working records it holds (`records` of `of_records`), and the `basis`: records outside it are **blanked, not dropped**. Their timestamps stay, so a ramp, calm spell or flat line never joins records the selection separates and the measurement interval is still inferred from the full record (dropped instead, every other record of a 10-minute series reads as a 20-minute cadence, which the timestep check refuses). A coverage or availability figure in such a result is the share of records both selected and valid. The shear and roughness timeseries and the raw data are blanked with the working data. |
| `decimated`, `bucket_ms` | `get_series_window`, `GET /sessions/{id}/series` (schema metadata) | Whether the window was reduced to buckets and how wide each is, in whole milliseconds (the width is rounded up, so there are at most `buckets`; `DEFAULT_SERIES_BUCKETS` = 2000). A bucket's bounds are the exact minimum and maximum of its records, not a sample, and `count` says how many valid records it holds: 0 marks a gap, with null bounds. `decimated: false` means every record is its own bucket and `bucket_ms` is null. |
| `truncated` | `get_flag_intervals` | Whether the response stopped at `MAX_FLAG_INTERVALS` (20,000) intervals. Past it the remaining intervals are left out, never merged or sampled, while each channel's `flagged_records` stays complete; the interface asks again for a narrower window. `interval_count` and `interval_limit` are beside it. |
| `in_progress` | sweep `manifest.json` (`list_sweeps`) | `true` on a checkpoint written while a sweep runs, or left by one that died part-way; absent on a finished sweep. The rows and runconfigs present are the shear-prefix groups completed so far. `finished_at` is the checkpoint time. `get_sweep_summary` and `analyze_sweep_spread` do not flag it yet. |

### Uncertainty is reported on a wind-speed basis — converting it to energy

Every component of the uncertainty model is a **percentage of wind speed**: measurement,
vertical extrapolation, MCP and future variability. So `total_uncertainty_pct` and the
`p_factors` beside it are **wind-speed** exceedances, and the response says so
(`basis: "wind_speed"`).

In wind resource assessment P50/P75/P90 normally name **energy** exceedances. The two are
not the same number, and the gap is the site's energy sensitivity factor:

```
S = d(ln AEP) / d(ln U)
```

`calculate_uncertainty` measures S on the session's own long-term series and returns it
under `energy_sensitivity`, together with the arithmetic. `compute_energy_sensitivity`
does the same on demand for any figure you pass it.

**To convert:**

| step | |
|---|---|
| 1 | Take the reported wind-speed uncertainty, e.g. **5.66%** |
| 2 | Multiply by this site's S, e.g. **1.22** |
| 3 | That gives **6.90%** — the energy uncertainty implied by the wind-speed uncertainty |
| 4 | Apply the exceedance quantiles to the *energy* figure: `P90 = AEP × (1 − 1.282 × 6.90/100) = AEP × 0.9116` |

**Do not** apply the wind-speed `p_factors` to an energy yield. They are speed
exceedances; using them directly on AEP understates the energy band by a factor of S.

**S is not a constant.** It falls as a site sits higher on the power curve, because more
hours at rated power means extra wind speed buys no extra energy. Measured against the
generic curve GoKaatru ships, on one synthetic 20-year hourly long-term series rescaled to
each mean (`tests/test_readme_energy_table.py` recomputes every row):

| site mean speed | gross CF | S |
|---|---|---|
| 5.5 m/s | 27% | **2.10** |
| 6.5 m/s | 37% | 1.70 |
| 7.5 m/s | 46% | 1.37 |
| 8.5 m/s | 54% | 1.10 |
| 10.5 m/s | 65% | **0.63** |

The gap between the two bases is therefore **widest at marginal sites** — exactly where
the P90 decides whether a project is financeable. A fixed multiplier would be wrong in
both directions.

**Two caveats that matter.**

The power curve is **generic** — a 3.0 MW, 130 m rotor machine at 226 W/m², roughly IEC
class IIA — chosen to give the right shape and order, not to represent a specific turbine.
S is turbine-specific, so recompute it with the project machine before publishing.

And the converted figure is a **floor, not an estimate**. It propagates the wind-speed
uncertainty only. A bankable energy uncertainty must also carry power-curve, wake,
availability, electrical-loss and flow-modelling terms — none of which GoKaatru models.

### Known limitations

- **No project energy yield is computed.** An indicative gross AEP and capacity factor
  (`indicative_aep_mwh`, `indicative_capacity_factor`) are computed off the generic curve
  and labelled indicative. There is no project power curve, no loss model, no wakes, no
  net energy and no energy-basis P50/P90. By the owner's decision of 2026-11-16 these will
  not be built: the product's output is long-term-corrected wind data.
- **Confidence intervals are approximate.** `ols_confidence_intervals` applies an
  AR(1) effective-sample-size correction estimated from the residuals' own lag-1
  autocorrelation, which on hourly wind widens the interval by roughly 3.5×
  against the raw i.i.d. figure. That is an approximation: a block bootstrap
  would be better and longer-range dependence is not captured, so the result is
  still a lower bound on the true uncertainty. Pass
  `autocorrelation_corrected=False` for the uncorrected interval.
- **`speedsort` is directional, and fits through rank-sorted pairs.** It bins by
  reference direction and fits per-sector dog-leg transfer functions, which
  earns its lower MCP uncertainty coefficient. Each fit sorts the reference and
  measured speeds independently and fits through the ranked pairs, as the
  published method does (`fit_basis: "rank_sorted"`); the previous time-paired
  fit overshot the slope when the correlation was modest. Measured on
  Launakalana (hub 120 m from 60 m and 80 m, ERA5 reference): concurrent mean
  bias -0.40 → -0.09 m/s non-directional and -0.40 → -0.18 m/s directional, long-term
  mean 4.49 → 4.83 and 4.41 → 4.66 m/s. The remaining bias sits in the dog-leg
  segment below the threshold, a method choice not yet made. It is still not a
  reimplementation of the windPRO/Windographer software.
- **IDW interpolation is a fallback only.** `interpolate_spatial` prefers
  bilinear whenever the four ERA5 nodes form a 2×2 cell containing the site,
  which is the normal case.
- **Ensemble weights use a mixed RMSE basis.** XGBoost is weighted on its
  held-out cross-validated RMSE while the linear methods are weighted on their
  concurrent-overlap RMSE, because only XGBoost reports an out-of-sample
  metric. That is the lesser of two evils — weighting a deep boosted ensemble
  on in-sample error would hand it a disproportionate share of the blend — but
  it is not like-for-like. `run_ensemble` now labels the basis of every weight
  and flags the mixture, so the tilt is at least auditable.
- **Inter-annual variability is assumed independent across years.**
  `u_future = iav / sqrt(project_life_years)` treats annual means as
  independent draws, which ignores inter-annual persistence and any climate
  trend. The life is a parameter; the independence assumption is not.
- **Extreme winds need a complete calendar year, and say so.** A campaign that
  starts or ends mid-year has no annual maximum, and the tool refuses rather
  than fitting a partial-season maximum as though it were one. The bundled
  Horns Rev fixture is 10.5 months and is refused for exactly this reason.
- **An all-ambiguous date column is refused, not guessed.** A DD/MM/YYYY file
  whose days all fall on or below 12 parses equally well either way, and reading
  it the wrong way round relabels the campaign silently — a 12-day March campaign
  becomes a series spanning January to December, at an unchanged 10-minute
  cadence, so nothing downstream detects it. Set `dayfirst` on the run
  configuration or supply ISO-8601.
- **A bimodal wind rose is reported by frequency, not energy.**
  `mean_direction_deg` and `prevailing_sector` both describe how often the wind
  blows from a sector, not how much energy arrives from it. On a site with a
  frequent weak easterly and a rarer strong westerly the two headline direction
  fields say east while essentially all the energy comes from the west.
  `compute_windrose_data` exposes the per-sector energy split; there is no
  energy-weighted mean direction field.
- **No outlier detection of any kind.** `range_check` bounds by sensor type,
  `stuck_sensor` catches frozen channels and `icing_filter` catches iced ones,
  but a single wild excursion inside the physical bounds passes through
  untouched. `list_cleaning_rules` reports this as `outlier_detection: "none"`.
- **Cleaning rules are order-dependent.** A rule that introduces NaNs changes
  what later rules observe, and the difference is large — 10 records against 2
  on the same data, from order alone. The order is logged and every apply says
  the order is material, but there is no canonical order and forcing one would
  substitute a different arbitrary choice.

## Deployment model — single-user-local

**GoKaatru is built and reviewed for a single trusted user running it on their own
machine.** Several security properties depend on that assumption. It is recorded
here so it is visible to whoever changes the deployment model.

The web API has **no authentication layer**. The session id is the only
credential, and it travels in the URL path (`/api/sessions/{id}/…`). Ids are
`uuid4().hex` (122 bits, unguessable) and there is no session-listing endpoint,
so the capability itself is sound — but a credential in a URL lands in
web-server and proxy access logs, browser history, and `Referer` headers, and
`SessionManager.get_session` will resurrect that session from disk long after
the browser closed. Session workspaces currently persist indefinitely.

### Before moving to team-internal, shared, or hosted deployment

These must be addressed first:

1. **Add authentication and scope sessions to an authenticated principal**, so a
   leaked session id alone is not sufficient authority. Failing that, move the
   session id out of the URL path into a header, use an opaque path segment,
   and ensure access logs redact it.
2. **Expire idle sessions and their workspaces on a timer.** A workspace left on
   disk stays resurrectable by anyone who recovers its id from a log.
3. **Re-review the chat proxy's tool authority** — see below. Locally the
   attacker and the user are the same person, which is what makes the current
   default acceptable; that stops being true the moment anyone else can reach
   the API.
4. **Review outbound request surfaces.** The chat proxy accepts only the named
   providers in `_PROVIDER_URLS`; custom endpoint URLs are rejected outright so
   a caller cannot aim the server's outbound request at an internal address.
   Keep it that way, or add resolve-then-validate before relaxing it.

### Chat tool authority

`POST /sessions/{id}/chat` executes MCP tools on the model's behalf, so the tool
surface is deny-by-default. Each tool's operation declaration (`server/operations.py`)
says whether the assistant may be offered it and whether it changes data or calls the
network; the two tiers are generated from that, and `tests/test_operations.py` pins
both by name, so moving a tool between tiers is a visible test edit. A tool declared
with `assistant=False` is not exposed at all.

| Tier | Count | Exposed when |
|---|---|---|
| Read-only — query, compute, plot, series windows, scatter pairs, flag intervals, the operation log, listing and resolving selections | 55 | always |
| Mutating — ingest, cleaning, config writes, ERA5 fetch, extrapolation, shear tables, LTC runs, uncertainty, the atmospheric diagnostic (it records the density the energy sensitivity uses), the clipping analysis (it records the inter-annual variability the uncertainty model uses), undo and redo, defining and deleting selections, removing sensors | 34 | only with `allow_mutating_tools: true` |

The remaining 12 of the 98 registered tools are declared `assistant=False` and
therefore unreachable from chat: every BrightHub / EarthDataHub tool — the read-only
tier's contract is "no session mutation, no filesystem, **no network**", and the
credential tools would additionally hand an injected prompt a view of the session's
authentication state. The exclusion is pinned by tests.

The authority check is repeated server-side at execution rather than trusted
from the tool list sent upstream, because a model can name a tool it was never
offered. Tool results are wrapped in `<untrusted-tool-output>` tags and the
system prompt instructs the model not to follow instructions found inside them —
that mitigates prompt injection; the allowlist is the actual control.

The Copilot UI sends `allow_mutating_tools: false` by default, and its BYOK
settings carry an opt-in checkbox ("Allow the assistant to change session data").
When on, the assistant can change session data without asking for each change;
per-action approval is not built yet, so it is off until the user opts in. The API
default is read-only as well.

### Projects survive a restart

A session's workspace is a project (`server/state/project.py`, decisions/0010). Raw
uploads stay untouched with their SHA-256 recorded, every frame is saved as Parquet named
by its content hash, and every other field goes into `catalogue.sqlite`. Each operation call
is logged with its actor, parameters (credentials redacted), code version and data versions,
and every successful change saves the project, so a restarted server reopens it as it was.
Each derived result records the call that built it (`derived_provenance`). A result built
from older data, or by an earlier engine version, is listed by `staleness_report` with the
reason (`stale_reasons`) and left as it is: nothing is recomputed silently.
A project whose recorded raw input was changed or removed outside GoKaatru is refused (HTTP
409) rather than shown with results the inputs no longer support. Credentials are never
written to disk.

## Validation

Backend (registered tool count changes as capabilities are added; verify it with the command below):

```bash
python -m ruff check server/ tests/
python -m pytest tests/ -v
python -m pytest tests/test_api_sessions.py tests/test_api_workflow.py -v
python -m pytest tests/test_windkit_adopted.py -v
python -m pytest tests/test_sensor_selection.py tests/test_uploaded_dataset.py -v
python -c "import asyncio, json; from server.main import mcp; print(len(asyncio.run(mcp.list_tools())), 'tools')"
```

`python -m tests.published_numbers --check` reruns the pipeline on the three reference
campaigns and compares every number it returns, and a SHA-256 of every series, with the
committed snapshot `tests/snapshots/published_numbers.json`; any difference, down to the
last bit, fails. `--write` refreshes the snapshot when a number is meant to move.

Tests that read the real reference campaigns (Boxkite, Horns Rev, Launakalana) need files
under the gitignored `data/uploads/` (set `GOKAATRU_TEST_UPLOADS_DIR` to read them from
elsewhere). Without them those tests skip with a message naming the missing file; they do
not error.

Frontend (Vitest coverage across types, store, import, stages, Canvas, copilot, and compare):

```bash
cd frontend && npm run test
cd frontend && npm run build    # tsc --noEmit && vite build
cd frontend && npm run check:api   # the generated API client matches frontend/src/api/openapi.json
cd frontend && npx playwright install chromium   # once
cd frontend && npm run test:e2e # Playwright smoke test; starts its own backend (:8011) and Vite (:5183)
```

Smoke checks:

```bash
python -m server.main --help
python -m uvicorn server.api.main:app --host 127.0.0.1 --port 8000
```

## Documentation

The canonical behavior contract is the code itself: the central config schema and response interfaces live in [`frontend/src/types/analysis.ts`](./frontend/src/types/analysis.ts), the web-API surface in [`server/api/routes/`](./server/api/routes), and the stage metadata in [`frontend/src/lib/stages.ts`](./frontend/src/lib/stages.ts). This README tracks the current workflow, endpoints, and tool inventory.

## Tech stack

**Backend:** Python 3.11+, FastAPI, FastMCP, pandas, xarray, scikit-learn / XGBoost (`[ml]` extra), Plotly + Kaleido, pytest, ruff.
**Frontend:** React 19, Vite 6, TypeScript (strict), Zustand, @xyflow/react (React Flow), Plotly.js, Zod, Vercel `ai` SDK + `@modelcontextprotocol/sdk` (BYOK copilot), vitest.
