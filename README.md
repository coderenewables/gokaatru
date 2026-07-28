# GoKaatru

> Open-source **Wind Resource Assessment (WRA)** platform — turn a measured wind campaign into a long-term-corrected, hub-height, ensemble-blended dataset ready for an Energy Yield Assessment (EYA).

GoKaatru ships as two parts that work together:

- **[`server/`](./server)** — a Python **MCP server** (FastAPI + FastMCP) exposing **209 tools** across data ingest, cleaning, statistics, shear/extrapolation, ERA5 & MERRA-2 acquisition, homogeneity, five long-term-correction (MCP) algorithms, ensemble, clipping, uncertainty, mapping, visualization, BrightHub integration, and WindKit (142 climate/spatial/Weibull/topography/wind-farm tools).
- **[`frontend/`](./frontend)** — a **workflow-driven web app** (React + Vite + TypeScript) that guides analysts through an **8-stage pipeline**, with an expert React-Flow canvas, a BYOK AI copilot, scenario comparison, and a WindKit explorer.

State is session-scoped; `runconfig` is the single source of truth for site metadata (project name, location, hub height, sensors, cleaning log, LTC settings).

## The 8-stage workflow

The web app drives the backend's tools in their required dependency order:

```
Stage 1 Data ─► Stage 2 Reanalysis ─► Stage 3 Explore ─► Stage 4 Shear → hub
                                       │                    │
                                       └─► Stage 5 Reanalysis → hub
                                                            │
                                                            ▼
                   Stage 6 LTC ─► Stage 7 Clipping ─► Stage 8 Ensemble + Uncertainty + Scenarios
```

| Stage | What happens |
|---|---|
| **1. Data loading** | Upload files (CSV/IEA Task 43 JSON) **or** import from BrightHub **or** load a shared dataset; set site & hub height. |
| **2. Reanalysis acquisition** | Find the 4 surrounding ERA5 + MERRA-2 nodes, download, derive wind speed, interpolate to the site (optional Pettitt homogeneity cutoff). |
| **3. Measured-data exploration** | Recovery/availability, wind rose, Weibull, diurnal/annual profiles, shear profile, turbulence intensity — to choose shear sensors & LTC strategy. |
| **4. Shear → hub (measured)** | Power-law (α) or log-law (z₀) shear + 12×24 lookup, extrapolate measured sensors to hub height (with direct/interpolated/extrapolated method counts). |
| **5. Reanalysis → hub** | Apply the same shear method to long-term ERA/MERRA nodes at hub height. |
| **6. Long-Term Correction** | MCP between measured (short) and reanalysis (long) across 5 algorithms (`speedsort`, `linear_least_squares`, `total_least_squares`, `variance_ratio`, `xgboost`); scatter/residual/convergence diagnostics. |
| **7. Clipping** | Pick the representative historical window that minimizes combined historic + climate uncertainty (advisory). |
| **8. Ensemble & uncertainty** | Inverse-RMSE ensemble blend, RSS total uncertainty + P50/75/90/99, save named scenarios for comparison. |

Beyond the stepper, the **Canvas** tab renders the full pipeline as an editable React-Flow DAG (run auto/step, snapshots, fork branches), the **Copilot** tab is a BYOK chat that drives backend tools via natural language, the **Compare** tab diffs saved scenarios, and the **WindKit** tab exposes the 142-tool WindKit surface.

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
│   └── windkit/        # 142 WindKit tools
├── state/              # session + dataset pool managers
└── schemas/            # Pydantic models (Coordinate, SensorInfo, PlotResult, …)

frontend/               # React + Vite + TypeScript web app
├── src/
│   ├── components/     # AppHeader, PhaseTabs, Stepper, stages/, WorkflowView, CopilotView, …
│   ├── store/          # useWorkspaceStore (Zustand)
│   ├── lib/            # api, configSync, stages, workflow, copilotAgent, openapi, …
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

## Tool inventory (209 MCP tools)

### Air Density
- `compute_air_density`, `compute_air_density_timeseries`

### BrightHub
- `brighthub_login`, `brighthub_logout`, `brighthub_status`, `brighthub_list_locations`, `brighthub_get_data_model`, `brighthub_import_location`, `brighthub_find_reanalysis_nodes`, `brighthub_download_reanalysis`

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
- `plot_windrose`, `plot_weibull`, `plot_diurnal`, `plot_scatter`, `plot_timeseries`, `plot_data_coverage`, `plot_shear_table`, `plot_monthly_means`, `plot_ltc_comparison`, `plot_annual_means`, `plot_uncertainty_breakdown`

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

## Validation

Backend (209 registered MCP tools — 67 core + 142 WindKit, ~200 web API routes, full test suite):

```bash
python -m ruff check server/ tests/
python -m pytest tests/ -v
python -m pytest tests/test_api_sessions.py tests/test_api_workflow.py -v
python -m pytest tests/test_windkit.py -v
python -c "import asyncio, json; from server.main import mcp; print(len(asyncio.run(mcp.list_tools())), 'tools')"
```

Frontend (vitest, ~85 tests across types, store, stages, canvas, copilot, compare, windkit):

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

- **[`WORKFLOW_FRONTEND_SPEC.md`](./WORKFLOW_FRONTEND_SPEC.md)** — the complete frontend build contract (8-stage workflow, store, API client, stage specs, endpoint reference). The canonical reference for the web app.
- [`BUILD_SPECIFICATION.md`](./BUILD_SPECIFICATION.md) / [`BUILD_INSTRUCTIONS.md`](./BUILD_INSTRUCTIONS.md) — backend build contract and phase-by-phase implementation history.

## Tech stack

**Backend:** Python 3.11+, FastAPI, FastMCP, pandas, xarray, scikit-learn / XGBoost (`[ml]` extra), Plotly + Kaleido, pytest, ruff.
**Frontend:** React 19, Vite 6, TypeScript (strict), Zustand, @xyflow/react (React Flow), Plotly.js, Zod, Vercel `ai` SDK + `@modelcontextprotocol/sdk` (BYOK copilot), vitest.
