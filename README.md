# GoKaatru

> Open-source **Wind Resource Assessment (WRA)** platform — turn a measured wind campaign into a long-term-corrected, hub-height, ensemble-blended dataset ready for an Energy Yield Assessment (EYA).

GoKaatru ships as two parts that work together:

- **[`server/`](./server)** — a Python **MCP server** (FastAPI + FastMCP) exposing **223 tools** across data ingest, cleaning, statistics, shear/extrapolation, ERA5 & MERRA-2 acquisition, homogeneity, five long-term-correction (MCP) algorithms, ensemble, clipping, uncertainty, mapping, visualization, BrightHub integration, and WindKit.
- **[`frontend/`](./frontend)** — a **workflow-driven web app** (React + Vite + TypeScript) with standalone data import, an editable React-Flow Canvas, a guided post-import Stepper, a read-only **Results** report, a **Sensor Overview** validation dashboard, a BYOK AI copilot, and scenario comparison. (The backend WindKit tool surface remains available via the API/MCP server, but the frontend no longer ships a dedicated WindKit tab.)

State is session-scoped; `runconfig` is the single source of truth for site metadata (project name, location, hub height, sensors, cleaning log, LTC settings). The frontend's convenience fields are **derived mirrors** of canonical backend keys, not independent state — the mapping is defined once in [`server/core/runconfig.py`](./server/core/runconfig.py) and enforced by `tests/test_runconfig_contract.py`.

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
| **4. Shear → hub (measured)** | Power-law (α) or log-law (z₀) shear + 12×24 lookup, extrapolate measured sensors to hub height. Only records above `min_speed_mps` (default **3.0 m/s**) contribute — below that, `ln(v₂/v₁)` is anemometer noise rather than profile. α is still bounded to [−1, 1] as a backstop, and every response reports how often that clamp fired. |
| **5. Reanalysis → hub** | Confirm long-term reference series are available at hub height using the chosen shear method. |
| **6. Long-Term Correction** | MCP between measured (short) and reanalysis (long) across 5 algorithms (`speedsort` — directionally binned, `linear_least_squares`, `total_least_squares`, `variance_ratio`, `xgboost`); scatter/residual/convergence diagnostics. Requires **at least six months** of valid concurrent records; below that it raises rather than returning a number. |
| **7. Clipping** | Pick the representative historical window that minimizes combined historic + climate uncertainty. Calendar years below **90%** completeness are excluded and reported, so a partial first or last year cannot inflate inter-annual variability. |
| **8. Ensemble & uncertainty** | Inverse-RMSE ensemble blend, RSS total uncertainty + P50/75/90/99, and named scenarios for comparison. |

Beyond the stepper, the **Canvas** tab renders the full pipeline as an editable React-Flow DAG (run auto/step, snapshots, fork branches), the **Results** tab is a read-only aggregate report of everything the session has produced (run overview, measured data, shear, reanalysis, LTC, ensemble & uncertainty, clipping/scenarios — it never triggers computation), the **Sensor Overview** tab is a measured-data validation dashboard, the **Copilot** tab is a BYOK chat that drives backend tools via natural language (the *Allow the assistant to modify this session* setting controls whether it may write as well as read — see [Chat tool authority](#chat-tool-authority)), and the **Compare** tab diffs saved scenarios.

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
├── core/               # executor, regression, spatial, formulas, validators, runconfig contract
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
| `/sessions/{id}/chat` | POST | BYOK LLM chat proxy with server-side tool execution (read-only by default; see [Chat tool authority](#chat-tool-authority)) |
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
- `compute_weibull_params`, `compute_wind_climate`, `compute_windrose_data`, `compute_diurnal_profile`, `compute_monthly_stats`, `compute_turbulence_intensity`, `compute_turbulence_analysis`, `compute_momm`, `compute_scatter_stats`, `calculate_uncertainty`, `compute_energy_sensitivity`

### Diagnostics (Sensor Overview)
- `compute_qc_diagnostics`, `compute_sensor_comparison`, `compute_mast_effects`, `compute_mcp_readiness`, `compute_vertical_structure`

### Advanced analysis
- `compute_energy_metrics`, `compute_extreme_winds`, `compute_wind_persistence`, `compute_wind_ramps`

### Visualization
- `plot_windrose`, `plot_weibull`, `plot_diurnal`, `plot_scatter`, `plot_timeseries`, `plot_data_coverage`, `plot_shear_table`, `plot_monthly_means`, `plot_ltc_comparison`, `plot_annual_means`, `plot_uncertainty_breakdown`

Additional figures are reachable through `POST /sessions/{id}/plots/{name}` without being MCP tools in their own right — including `shear_profile`, `shear_timeseries`, `era5_scatter`, `mast_shadow`, `qc_flags`, `ltc_scatter`, `ltc_residuals`, `ltc_monthly`, `ltc_convergence`, and `uncertainty_tornado`.

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
- `windkit_plot_histogram` / `windkit_plot_histogram_lines` / `windkit_plot_operational_curves` / `windkit_plot_raster` / `windkit_plot_roughness_rose` / `windkit_plot_time_series` / `windkit_plot_vertical_profile` / `windkit_plot_wind_rose` / `windkit_plot_landcover_map`

### WindKit — Other (14 tools)
- Tutorial: `windkit_get_tutorial_data` / `windkit_load_tutorial_data`
- Weibull: `windkit_fit_weibull_wasp_m1_m3_fgtm` / `windkit_fit_weibull_wasp_m1_m3` / `windkit_fit_weibull_k_sumlogm` / `windkit_weibull_moment` / `windkit_weibull_pdf` / `windkit_weibull_cdf` / `windkit_weibull_freq_gt_mean` / `windkit_get_weibull_probability`
- Coordinates: `windkit_create_sector_coords` / `windkit_create_wsbin_coords`
- WAsP: `windkit_read_cfdres`
- ERA5: `windkit_get_era5`

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
| Datamodel declares no timezone | A wrong assumption here is silent and corrupts every LTC. Provide `timezone` (IANA) or `offset_from_utc_hrs` in `logger_main_config`. |
| Degenerate (vertical) relationship in total least squares | The slope is genuinely undefined; the old code returned a `1e12` sentinel. |

### Defaults that affect results

| Setting | Default | Notes |
|---|---|---|
| Weibull fit | **WAsP m1/m3** moment method | Matches the 1st and 3rd moments so mean *and* energy content are preserved — the wind-industry convention, and what WAsP/Windographer report. Moments are taken over the **full** series including calms. MLE remains available via `method="mle"`, which must exclude zeros. Expect roughly **k −0.1 and A −0.25** versus MLE on typical data. |
| Shear valid-record gate | **3.0 m/s** (`min_speed_mps`) | Persisted to `runconfig.shear.minSpeedMps`. Raising it from the old 0.1 m/s removes near-calm records whose `ln(v₂/v₁)` is noise; on a real two-year lidar campaign this dropped 5% of records and cut shear σ from 0.168 to 0.149. |
| Clipping year completeness | **0.9** (`min_year_completeness`) | Leap-aware, measured against the series' own cadence. |
| SpeedSort binning | **12 sectors × 30°**, min **200** records/sector | Sparse sectors fall back to the all-sector fit; `independent_sectors` and the per-sector `sector_models` report where the fit is thin. |
| Mast-shadow speed gate | **4.0 m/s**, min **50** records/sector | Detection is two-sided: a low ratio means `sensor_b` is shadowed, a high ratio means `sensor_a` is. Sparse sectors are reported but not flagged. |
| `range_check` bounds | **Derived from sensor type** | wind_speed 0–50 m/s, wind_direction 0–360°, temperature −60–60 °C, pressure 80 000–110 000 Pa, humidity 0–100%. An unknown type falls back to that sensor's own data range, which makes the rule a **no-op** — an intentional fail-safe, reported as `bounds_source: "sensor_data_range"`. Explicit `min`/`max` always win. |
| ERA5 spatial interpolation | **Scalar** for speed, **vector** for direction | Deliberately different. Vector interpolation of speed under-predicts where node directions diverge across the cell, because opposing components cancel. Reported as `speed_interpolation: "scalar"`. |
| Long-term reference | **ERA5** (`source` on `interpolate_era5_to_site`) | `"merra2"` selects the other downloaded reanalysis. Both write the same interpolated series every LTC algorithm reads, so switching source and repeating the LTC is how a result's dependence on the reference is tested. Reported as `reference_source`. |
| Timestamp interval label | **`interval_start`** (`runconfig.timestamp_label`) | IEA Task 43 permits start, end and centre labelling and a file does not say which it uses, so this is an assumption. Set it to `interval_end` or `interval_centre` and the measured index is shifted onto interval-start before matching — a mismatch against instantaneous reanalysis is a systematic half-interval offset in every LTC, not noise. |
| Hourly resample coverage | **0.5** of expected sub-hourly samples | A 3-of-6 hour is kept and averaged as a full hour; a 1-of-6 hour is dropped. Reported as `hours_kept`, `hours_dropped_below_minimum` and `hours_kept_partially_populated`. |
| Sector shear minimum | **200** records/sector | Matches the SpeedSort gate. Below it a sector is not tabulated, because 20 records produced a 288-cell table of which 285 were that sector's own mean. Every sector's count and the reason for each exclusion are reported; overridable via `min_sector_records`. |
| Roughness band | **[1e-6, 2.0] m** | The ceiling covers WAsP class 3 and dense forest or urban terrain. It was 1.5 m, which truncated them — and the clamp *raises* log-law hub speed, so it was not a conservative backstop. |
| Tower-shadow sector | **Derived per sensor** | Boom orientation from the datamodel (shadow centred at boom + 180 deg, width 70 deg), else the sectors `compute_mast_effects` measured, else the legacy 20-degree window at 170-190 deg — which reports `sector_basis: "default_guess"` and warns that it is about a third of a lattice tower's real shadow. |
| Icing conditions | **Speed SD + temperature + held vane** | A cold, steady flow satisfies the first two. The paired direction column must also be stationary within 5 deg over a three-record window. With no direction column mapped the test is skipped and the response says so. |
| MCP concurrent-months cap | **12** (`concurrent_months_cap`) | The `3/sqrt(months)` sampling term stops improving here, because beyond about a year the limit on an MCP is the stability of the transfer function rather than the number of pairs. `mcp_sampling_cap` reports the uncapped figure and the credit withheld. |
| Project life | **20 years** (`project_life_years`) | `u_future = iav / sqrt(life)`. A 15-year life gives 1.55% where 20 years gives 1.34% for the same 6% IAV. |
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

| Field | Appears in | Meaning |
|---|---|---|
| `records_clamped`, `clamped_fraction` | every shear response | How often α hit the [−1, 1] backstop. A clamped α = 1.0 turns 8.7 m/s at 150 m into 15.0 m/s. Above 5% the response carries an explicit `warning`. |
| `measured_resampled_to_hourly`, `resampling_note` | every LTC response | Measured data is averaged to hourly means while the reanalysis reference is instantaneous. This removes within-hour variance from the measured side only, biasing `variance_ratio` low. Slope-based methods are far less affected. |
| `negative_predictions_clipped` | every LTC response | Corrected speeds truncated at zero. A non-trivial count means the transfer function is bad. |
| `n_above_training_max`, `fraction_above_training_max` | `run_ltc_xgboost` | Long-term records above the campaign maximum. Trees are piecewise-constant and cannot extrapolate, so these collapse onto the model's highest leaf. **Do not use XGBoost alone for extreme-wind estimation** — it biases GEV/Gumbel annual maxima low. |
| `years_used`, `years_excluded`, `excluded_reason` | `run_clipping_analysis` | Which calendar years passed the completeness gate. |
| `calm_fraction`, `fit_excludes_calms`, `fit_method` | `compute_weibull_params` | `mean_speed` is always the **full-series** mean including calms, consistent with MoMM and the monthly means. |
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
| `method_models`, `method_is_mixed` | `extrapolate_to_hub_height` | Which physical model produced each hub record. Inside the mast range it is linear interpolation in ln(z); outside it is the shear or roughness table. A series with counts in both rows is a blend of two models. |
| `mcp_sampling_cap`, `combination` | `calculate_uncertainty` | What the 12-month cap withheld, and what the independence assumption costs at ρ = 0.5. |
| `method_by_variable`, `skipped_variables` | `interpolate_era5_to_site` | Which interpolation each variable actually used, rather than one label collapsed to "idw" if any variable fell back; and any variable dropped because a node does not carry it, with the nodes responsible. Dew point feeds air density and temperature/pressure feed the XGBoost features, so a silent drop surfaces later as an unrelated missing-column error. |
| `alpha_reclamped_records`, `stability_treatment` | `extrapolate_to_hub_height` | Records whose shear exponent hit the [-1, 1] clamp before extrapolation — normally zero, but reachable through the fallback fill and the aggregate MoMM path, and a clamp that fires changes the hub speed. And the standing neutral-profile assumption. |
| `reference_temporal_semantics` | every LTC response | Whether the reference is instantaneous (ERA5) or time-averaged (MERRA-2). The resampling note differs between them: the one-sided variance loss that biases variance-ratio results applies only against an instantaneous reference. |
| `iec_ti_at_15ms`, `iec_ti_bin_mps`, `iec_ti_bin_records` | `compute_turbulence_analysis` | Representative turbulence in the 1 m/s bin containing 15 m/s, which selects the IEC turbulence class (Iref 0.16 / 0.14 / 0.12 for A / B / C). The bin actually used and its record count travel with it, because a low-wind campaign may never reach 15 m/s — in which case the response says so and the class cannot be selected from it. |
| `gev.available`, `plausible`, `below_largest_observed` | `compute_extreme_winds` | Whether the GEV fit was performed at all, whether each fit's return levels are usable (divergent, or collapsed so that V100 is no higher than V50), and whether V50 sits below the largest observed annual maximum. The last is a cue, not a failure: the largest of twenty maxima is roughly a twenty-year event. |
| `years_excluded`, `min_year_coverage` | `compute_extreme_winds` | Calendar years covering too little of the calendar to hold an annual maximum, with their day coverage, months and the partial maximum they would have contributed. |
| `density_normalisation` | `calculate_uncertainty`, `compute_energy_sensitivity` | Whether speeds were normalised to the power curve's reference density per IEC 61400-12-1 before the sensitivity factor was measured. Requires a recorded site density; without one it reports `applied: false` rather than assuming standard conditions. |
| `upstream_processing` | `brighthub_import_location` | BrightHub cleaning, calibration and offsets applied **before** GoKaatru saw the data. Recorded as a non-undoable entry at the head of the cleaning log: coverage and recovery figures describe the data as received, not the raw campaign. |

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
generic curve GoKaatru ships:

| site mean speed | gross CF | S |
|---|---|---|
| 5.5 m/s | 27% | **2.12** |
| 6.5 m/s | 37% | 1.70 |
| 7.5 m/s | 46% | 1.37 |
| 8.5 m/s | 54% | 1.10 |
| 10.5 m/s | 65% | **0.64** |

The gap between the two bases is therefore **widest at marginal sites** — exactly where
the P90 decides whether a project is financeable. A fixed multiplier would be wrong in
both directions.

**Two caveats that matter.**

The power curve is **generic** — a 4.2 MW, 150 m rotor machine at 238 W/m², roughly IEC
class IIA — chosen to give the right shape and order, not to represent a specific turbine.
S is turbine-specific, so recompute it with the project machine before publishing.

And the converted figure is a **floor, not an estimate**. It propagates the wind-speed
uncertainty only. A bankable energy uncertainty must also carry power-curve, wake,
availability, electrical-loss and flow-modelling terms — none of which GoKaatru models.

### Known limitations

- **No energy yield is computed.** GoKaatru characterises the wind *resource* and stops
  short of the *yield*: there is no project AEP, no capacity factor and no loss model.
  The energy sensitivity factor above exists to make the speed-to-energy conversion
  explicit, not to substitute for an energy assessment.
- **Confidence intervals are approximate.** `ols_confidence_intervals` applies an
  AR(1) effective-sample-size correction estimated from the residuals' own lag-1
  autocorrelation, which on hourly wind widens the interval by roughly 3.5×
  against the raw i.i.d. figure. That is an approximation: a block bootstrap
  would be better and longer-range dependence is not captured, so the result is
  still a lower bound on the true uncertainty. Pass
  `autocorrelation_corrected=False` for the uncorrected interval.
- **`speedsort` is directional but not published SpeedSort.** It bins by
  reference direction and fits per-sector dog-leg transfer functions, which
  earns its lower MCP uncertainty coefficient, but it is not a reimplementation
  of the windPRO/Windographer algorithm.
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
surface is an explicit **name allowlist**, deny-by-default. A tool in neither
tier is not exposed at all, so adding a new MCP tool does not silently widen the
model's authority.

| Tier | Count | Exposed when |
|---|---|---|
| Read-only — query, compute, plot | 36 | always |
| Mutating — ingest, cleaning, config writes, ERA5 fetch, extrapolation, shear tables, LTC runs, uncertainty | 26 | only with `allow_mutating_tools: true` |

The authority check is repeated server-side at execution rather than trusted
from the tool list sent upstream, because a model can name a tool it was never
offered. Tool results are wrapped in `<untrusted-tool-output>` tags and the
system prompt instructs the model not to follow instructions found inside them —
that mitigates prompt injection; the allowlist is the actual control.

The Copilot UI sends `allow_mutating_tools: true` by default so the assistant can
drive the workflow, and exposes a checkbox in its BYOK settings to make the
assistant read-only. The API default is read-only.

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
