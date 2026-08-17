# GoKaatru

> Open-source **Wind Resource Assessment (WRA)** platform — turn a measured wind campaign into a long-term-corrected, hub-height, ensemble-blended dataset ready for an Energy Yield Assessment (EYA).

GoKaatru ships as two parts that work together:

- **[`server/`](./server)** — a Python **MCP server** (FastAPI + FastMCP) exposing **222 tools** across data ingest, cleaning, statistics, shear/extrapolation, ERA5 & MERRA-2 acquisition, homogeneity, five long-term-correction (MCP) algorithms, ensemble, clipping, uncertainty, mapping, visualization, BrightHub integration, and WindKit.
- **[`frontend/`](./frontend)** — a **workflow-driven web app** (React + Vite + TypeScript) with standalone data import, an editable React-Flow Canvas, a guided post-import Stepper, a read-only **Results** report, a **Sensor Overview** validation dashboard, a BYOK AI copilot, and scenario comparison. (The backend WindKit tool surface remains available via the API/MCP server, but the frontend no longer ships a dedicated WindKit tab.)

State is session-scoped; `runconfig` is the single source of truth for site metadata (project name, location, hub height, sensors, cleaning log, LTC settings).

## Application workflow

The default application flow is:

```
Data import + hub height
    │
    ├──► BrightHub sign-in when required
    │
    └──► Save config and run model
           │
           ▼
    Editable Canvas default plan
    (live node progress, timing, and ETA)
           │
           ▼
       Post-import Stepper and specialist tools
```

### Data import and default Canvas plan

1. Import measured time-series and an IEA Task 43 data model, import a BrightHub location, or load a shared dataset.
2. (Optional) In the **Analysis sensor selection** table, untick sensors to exclude them. Applying the selection removes them from the working data and records them in `excluded_sensors`; reloading the data file or re-importing from BrightHub restores the full set.
3. Enter the site metadata and **hub height**. Hub height has no default and is required before a model can run.
4. Click **Save config and run model**. If BrightHub credentials are not available, the app opens the BrightHub sign-in view instead of starting a run.
5. On successful authentication, the app persists the runconfig, opens the Canvas, and starts the default graph. The graph remains editable for later reruns or manual changes.

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
| **1. Data cleaning** | Review the imported measurement inventory, choose which sensors stay in the analysis (excluded sensors are removed from the working data and recorded in `excluded_sensors`), and apply explicit cleaning filters when appropriate. |
| **2. Reanalysis acquisition** | Review BrightHub ERA5 + MERRA-2 nodes and site interpolation; optional direct EarthDataHub ERA5 is available as a separate, credentialed fallback. |
| **3. Measured-data exploration** | Recovery/availability, wind rose, Weibull, diurnal/annual profiles, shear profile, turbulence intensity — to refine shear sensors and LTC strategy. |
| **4. Shear → hub (measured)** | Power-law (α) or log-law (z₀) shear + 12×24 lookup, extrapolate measured sensors to hub height. The power-law exponent is bounded to α ∈ [−1, 1] so a noisy record can't be amplified into a non-physical hub speed. |
| **5. Reanalysis → hub** | Confirm long-term reference series are available at hub height using the chosen shear method. |
| **6. Long-Term Correction** | MCP between measured (short) and reanalysis (long) across 5 algorithms (`speedsort`, `linear_least_squares`, `total_least_squares`, `variance_ratio`, `xgboost`); scatter/residual/convergence diagnostics. |
| **7. Clipping** | Pick the representative historical window that minimizes combined historic + climate uncertainty. |
| **8. Ensemble & uncertainty** | Inverse-RMSE ensemble blend, RSS total uncertainty + P50/75/90/99, and named scenarios for comparison. |

Beyond the stepper, the **Canvas** tab renders the full pipeline as an editable React-Flow DAG (run auto/step, snapshots, fork branches), the **Results** tab is a read-only aggregate report of everything the session has produced (run overview, measured data, shear, reanalysis, LTC, ensemble & uncertainty, clipping/scenarios — it never triggers computation), the **Sensor Overview** tab is a measured-data validation dashboard, the **Copilot** tab is a BYOK chat that drives backend tools via natural language, and the **Compare** tab diffs saved scenarios.

## Quick start

### Backend (MCP server + web API)

```bash
conda activate gokaatru              # Python 3.11+
pip install -e ".[ml,dev]"
python -m server.main                # MCP server (stdio transport)
```

For a network-reachable SSE server:

```bash
python -m server.main --transport sse --host 0.0.0.0 --port 8080
```

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

Production build:

```bash
npm run build                        # tsc --noEmit && vite build → frontend/dist/
npm run test                         # vitest
```

## Project layout

```
server/                 # Python MCP server + FastAPI web API
├── api/                # FastAPI routes (sessions, analysis, brighthub, workflow, windkit, …)
├── core/               # executor, regression, spatial, formulas, validators
├── tools/              # MCP tools: data_io, cleaning, shear, extrapolation, era5, ltc, …
│   └── windkit/        # WindKit tools
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
| `/sessions` | POST | Create a new browser session |
| `/sessions/{id}` | GET | Session summary + `completed_steps` |
| `/sessions/{id}/config` | GET/PUT | Read or update runconfig |
| `/sessions/{id}/config/import` | POST | Import a complete runconfig JSON payload |
| `/sessions/{id}/summary` | GET | Workflow progress and analysis readiness |
| `/sessions/{id}/uploads/{timeseries\|datamodel}` | POST | Upload a file (multipart) |
| `/sessions/{id}/sensors` | GET | Sensor inventory |
| `/sessions/{id}/sensors/delete` | POST | Remove sensors from the session (drops their columns; persists `excluded_sensors`) |
| `/sessions/{id}/coverage/{sensor}` | GET | Per-sensor coverage/gap stats |
| `/sessions/{id}/statistics/{sensor}` | GET | Weibull, monthly/diurnal, percentiles |
| `/sessions/{id}/era5/{nodes\|extract\|interpolate}` | POST | ERA5 node discovery, extraction, interpolation |
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
| `/windkit/*` | POST | ~95 WindKit endpoints (OpenAPI-documented) |
| `/mcp/catalog` | GET | MCP tool/resource catalog for discovery |

## Tool inventory

### Air Density
- `compute_air_density`, `compute_air_density_timeseries`

### BrightHub
- `brighthub_login`, `brighthub_logout`, `brighthub_status`, `brighthub_list_locations`, `brighthub_get_data_model`, `brighthub_import_location`, `brighthub_find_reanalysis_nodes`, `brighthub_download_reanalysis`, `brighthub_prepare_reanalysis`

### Cleaning
- `list_cleaning_rules`, `apply_cleaning_rule`, `get_cleaning_log`, `undo_cleaning_rule`

### Clipping And Ensemble
- `run_clipping_analysis`, `run_ensemble`

### Configuration
- `get_run_config`, `update_run_config`, `save_run_config`, `load_run_config`, `get_analysis_summary`

### Data I/O
- `parse_timeseries`, `parse_datamodel`, `list_sensors`, `get_period_of_record`, `get_data_coverage`

### ERA5 And Reanalysis
- `find_era5_nodes`, `extract_era5_data`, `compute_era5_wind_speed`, `interpolate_era5_to_site`, `extrapolate_reanalysis_to_hub`, `analyze_homogeneity`, `apply_homogeneity_cutoff`

### Extrapolation And Shear
- `extrapolate_to_hub_height`, `calculate_shear_timeseries`, `calculate_roughness_timeseries`, `build_shear_table`, `build_roughness_table`, `build_sector_shear_tables`, `build_aggr_momm_shear_table`

### Long-Term Correction
- `run_ltc_linear_least_squares`, `run_ltc_total_least_squares`, `run_ltc_speedsort`, `run_ltc_variance_ratio`, `run_ltc_xgboost`

### Mapping
- `get_mast_marker`, `get_era5_node_markers`, `get_site_overview_map`

### Statistics
- `compute_weibull_params`, `compute_windrose_data`, `compute_diurnal_profile`, `compute_monthly_stats`, `compute_turbulence_intensity`, `compute_momm`, `compute_scatter_stats`, `calculate_uncertainty`

### Visualization
- `plot_windrose`, `plot_weibull`, `plot_diurnal`, `plot_scatter`, `plot_timeseries`, `plot_data_coverage`, `plot_shear_table`, `plot_shear_profile`, `plot_shear_timeseries`, `plot_era5_scatter`, `plot_monthly_means`, `plot_ltc_comparison`, `plot_annual_means`, `plot_uncertainty_breakdown`

### WindKit — Wind Functions (13 tools)
- `windkit_wind_speed`, `windkit_wind_direction`, `windkit_wind_speed_and_direction`, `windkit_wind_vectors`, `windkit_wind_direction_difference`, `windkit_wd_to_sector`, `windkit_vinterp_wind_direction`, `windkit_vinterp_wind_speed`, `windkit_rotor_equivalent_wind_speed`, `windkit_shear_extrapolate`, `windkit_shear_exponent`, `windkit_veer_extrapolate`, `windkit_wind_veer`

### WindKit — Climate (30 tools)
- `windkit_validate_tswc` / `windkit_is_tswc` / `windkit_create_tswc` / `windkit_read_tswc` / `windkit_tswc_from_dataframe` / `windkit_tswc_resample`
- `windkit_validate_bwc` / `windkit_is_bwc` / `windkit_create_bwc` / `windkit_read_bwc` / `windkit_bwc_from_tswc` / `windkit_bwc_to_file` / `windkit_combine_bwcs` / `windkit_weibull_fit`
- `windkit_validate_wwc` / `windkit_is_wwc` / `windkit_create_wwc` / `windkit_read_wwc` / `windkit_read_mfwwc` / `windkit_wwc_to_file` / `windkit_wwc_to_bwc` / `windkit_weibull_combined`
- `windkit_validate_gwc` / `windkit_is_gwc` / `windkit_create_gwc` / `windkit_read_gwc` / `windkit_gwc_to_file`
- `windkit_validate_geowc` / `windkit_is_geowc`

### WindKit — Climate Statistics (7 tools)
- `windkit_create_met_fields`, `windkit_mean_ws_moment`, `windkit_ws_cdf`, `windkit_ws_freq_gt_mean`, `windkit_mean_wind_speed`, `windkit_mean_power_density`, `windkit_get_cross_predictions`

### WindKit — LTC (2 tools)
- `windkit_ltc_linreg_mcp`, `windkit_ltc_varrat_mcp`

### WindKit — Topography (18 tools)
- Landcover: `windkit_get_landcover_table` / `windkit_add_landcover` / `windkit_roughness_to_landcover` / `windkit_landcover_to_roughness` / `windkit_read_landcover_map` / `windkit_write_landcover_map` / `windkit_get_landcover_from_gwa` / `windkit_get_landcover_from_remote`
- Elevation: `windkit_read_elevation_map` / `windkit_write_elevation_map`
- Raster: `windkit_create_raster_map` / `windkit_get_raster_from_remote`
- Vector: `windkit_create_vector_map` / `windkit_get_vector_from_gwa`
- Conversion: `windkit_lines_to_polygons` / `windkit_polygons_to_lines` / `windkit_snap_to_layer` / `windkit_check_dead_ends` / `windkit_check_lines_cross`

### WindKit — Wind Farm (16 tools)
- Turbines: `windkit_validate_wind_turbines` / `windkit_is_wind_turbines` / `windkit_check_wtg_keys` / `windkit_create_wt_from_dataframe` / `windkit_create_wt_from_arrays` / `windkit_wt_to_geodataframe`
- WTG: `windkit_validate_wtg` / `windkit_is_wtg` / `windkit_estimate_regulation_type` / `windkit_read_wtg` / `windkit_wtg_power` / `windkit_wtg_cp` / `windkit_wtg_ct`
- Losses: `windkit_validate_uncertainty_table` / `windkit_get_uncertainty_table` / `windkit_total_uncertainty` / `windkit_uncertainty_table_summary` / `windkit_total_uncertainty_factor`

### WindKit — Spatial (25+ tools)
- CRS: `windkit_get_crs` / `windkit_set_crs` / `windkit_crs_are_equal`
- Create: `windkit_create_dataset` / `windkit_create_raster` / `windkit_create_point` / `windkit_create_stacked_point` / `windkit_create_cuboid`
- Validate: `windkit_is_point` / `windkit_is_stacked_point` / `windkit_is_cuboid` / `windkit_is_raster`
- Convert: `windkit_to_point` / `windkit_to_cuboid` / `windkit_to_stacked_point` / `windkit_to_raster` / `windkit_gdf_to_ds` / `windkit_ds_to_gdf`
- Interpolation: `windkit_interp_structured_like` / `windkit_interp_unstructured` / `windkit_interp_unstructured_like`
- Comparison: `windkit_are_spatially_equal` / `windkit_equal_spatial_shape` / `windkit_covers`

### WindKit — Plotting (9 tools)
- `plot_histogram` / `plot_histogram_lines` / `plot_operational_curves` / `plot_raster` / `plot_roughness_rose` / `plot_time_series` / `plot_vertical_profile` / `plot_wind_rose` / `plot_landcover_map`

### WindKit — Other (14 tools)
- Tutorial: `windkit_get_tutorial_data` / `windkit_load_tutorial_data`
- Weibull: `windkit_fit_weibull_wasp_m1_m3_fgtm` / `windkit_fit_weibull_wasp_m1_m3` / `windkit_fit_weibull_k_sumlogm` / `windkit_weibull_moment` / `windkit_weibull_pdf` / `windkit_weibull_cdf` / `windkit_weibull_freq_gt_mean` / `windkit_get_weibull_probability`
- Coordinates: `windkit_create_sector_coords` / `windkit_create_wsbin_coords`
- WAsP: `windkit_read_cfdres`
- ERA5: `windkit_get_era5`

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
3. **Re-review the chat proxy's tool authority.** `POST /sessions/{id}/chat`
   executes MCP tools on the model's behalf. Read-only analysis and
   visualization tools are exposed by default; session-mutating, filesystem and
   network tools require `allow_mutating_tools=true` per request. Tool results
   re-enter the model's context and contain user-supplied text (CSV headers,
   sensor names, imported metadata), so a crafted column header is a
   prompt-injection vector — locally the attacker and the user are the same
   person, which is what makes the current default acceptable.
4. **Review outbound request surfaces.** The chat proxy accepts only the named
   providers in `_PROVIDER_URLS`; custom endpoint URLs are rejected outright so
   a caller cannot aim the server's outbound request at an internal address.
   Keep it that way, or add resolve-then-validate before relaxing it.

## Validation

Backend (registered tool count changes as capabilities are added; verify it with the command below):

```bash
python -m ruff check server/ tests/
python -m pytest tests/ -v
python -m pytest tests/test_api_sessions.py tests/test_api_workflow.py -v
python -m pytest tests/test_windkit.py -v
python -m pytest tests/test_sensor_selection.py tests/test_uploaded_dataset.py -v
python -c "import asyncio, json; from server.main import mcp; print(len(asyncio.run(mcp.list_tools())), 'tools')"
```

Frontend (Vitest coverage across types, store, import, stages, Canvas, copilot, compare, and WindKit):

```bash
cd frontend && npm run test
cd frontend && npm run build    # tsc --noEmit && vite build
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
