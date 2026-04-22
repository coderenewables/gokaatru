# GoKaatru

GoKaatru is a Wind Resource Assessment MCP server for ingesting wind measurement data, cleaning and extrapolating it, correlating it against ERA5 reanalysis, and producing long-term correction, uncertainty, visualization, and mapping outputs. The server exposes 209 MCP tools grouped across data I/O, statistics, shear, ERA5, LTC, post-processing, visualization, configuration, BrightHub workflows, and WindKit integration (142 tools covering wind functions, climate analysis, spatial operations, Weibull distributions, topography, wind farms, and plotting), with `runconfig` as the source of truth for site metadata such as location and hub height.

The workflow web app supports scenario management: save the current analysis state as a named scenario, or upload a `runconfig.json` file to import configuration overrides and automatically execute the LTC → ensemble → uncertainty pipeline, saving the result as a new scenario for comparison.

## Quick Start (Local)

```bash
conda activate gokaatru
pip install -e ".[ml,dev]"
python -m server.main
```

For a local SSE server that any network client can reach:

```bash
python -m server.main --transport sse --host 0.0.0.0 --port 8080
```

## Workflow Web App (Local Development)

Run the analyst-facing workflow stack as three processes:

```bash
conda activate gokaatru
pip install -e ".[ml,dev]"
npm --prefix frontend install
python -m uvicorn server.api.main:app --reload --port 8000
python -m server.main --transport sse --host 0.0.0.0 --port 8080
npm --prefix frontend run dev
```

Default local endpoints:

- Workflow UI: `http://127.0.0.1:5173`
- FastAPI web API: `http://127.0.0.1:8000/api`
- MCP SSE endpoint: `http://127.0.0.1:8080/sse`

The Vite dev server proxies `/api` to the FastAPI app, so the browser workflow never talks to MCP directly for core analysis actions.

On Windows, you can launch the local non-Docker stack with one command:

```powershell
.\startup.ps1
```

Useful options:

```powershell
.\startup.ps1 -OpenBrowser
.\startup.ps1 -IncludeMcp -OpenBrowser
```

## Quick Start (Docker)

```bash
docker compose up --build
```

The Compose stack starts one service:

- GoKaatru at `http://localhost:8080/sse`

## Validation

The repository has been validated with 209 registered MCP tools (67 core + 142 WindKit), ~200 web API routes, and full backend + frontend test coverage.

```bash
python -m ruff check server/ tests/
python -m pytest tests/ -v
python -m pytest tests/test_windkit.py -v
python -m pytest tests/test_api_sessions.py tests/test_api_workflow.py -v
python -m server.main --help
python -m uvicorn server.api.main:app --host 127.0.0.1 --port 8000
python -c "import asyncio, json; from server.main import mcp; print(json.dumps([tool.name for tool in asyncio.run(mcp.list_tools())], indent=2))"
npm --prefix frontend run build
npm --prefix frontend run test -- --run
docker build -t gokaatru .
docker compose config
docker compose up -d
docker compose ps
```

## Tool Inventory

### Air Density

- `compute_air_density`
- `compute_air_density_timeseries`

### BrightHub

- `brighthub_login`
- `brighthub_logout`
- `brighthub_status`
- `brighthub_list_locations`
- `brighthub_get_data_model`
- `brighthub_import_location`
- `brighthub_find_reanalysis_nodes`
- `brighthub_download_reanalysis`

### Cleaning

- `list_cleaning_rules`
- `apply_cleaning_rule`
- `get_cleaning_log`
- `undo_cleaning_rule`

### Clipping And Ensemble

- `run_clipping_analysis`
- `run_ensemble`

### Configuration

- `get_run_config`
- `update_run_config`
- `save_run_config`
- `load_run_config`
- `get_analysis_summary`

### Data I/O

- `parse_timeseries`
- `parse_datamodel`
- `list_sensors`
- `get_period_of_record`
- `get_data_coverage`

### ERA5 And Reanalysis

- `find_era5_nodes`
- `extract_era5_data`
- `compute_era5_wind_speed`
- `interpolate_era5_to_site`
- `extrapolate_reanalysis_to_hub`
- `analyze_homogeneity`
- `apply_homogeneity_cutoff`

### Extrapolation And Shear

- `extrapolate_to_hub_height`
- `calculate_shear_timeseries`
- `calculate_roughness_timeseries`
- `build_shear_table`
- `build_roughness_table`
- `build_sector_shear_tables`
- `build_aggr_momm_shear_table`

### Long-Term Correction

- `run_ltc_linear_least_squares`
- `run_ltc_total_least_squares`
- `run_ltc_speedsort`
- `run_ltc_variance_ratio`
- `run_ltc_xgboost`

### Mapping

- `get_mast_marker`
- `get_era5_node_markers`
- `get_site_overview_map`

### Statistics

- `compute_weibull_params`
- `compute_windrose_data`
- `compute_diurnal_profile`
- `compute_monthly_stats`
- `compute_turbulence_intensity`
- `compute_momm`
- `compute_scatter_stats`
- `calculate_uncertainty`

### WindKit — Wind Functions (13 tools)

- `windkit_wind_speed`
- `windkit_wind_direction`
- `windkit_wind_speed_and_direction`
- `windkit_wind_vectors`
- `windkit_wind_direction_difference`
- `windkit_wd_to_sector`
- `windkit_vinterp_wind_direction`
- `windkit_vinterp_wind_speed`
- `windkit_rotor_equivalent_wind_speed`
- `windkit_shear_extrapolate`
- `windkit_shear_exponent`
- `windkit_veer_extrapolate`
- `windkit_wind_veer`

### WindKit — Climate (30 tools)

- `windkit_validate_tswc` / `windkit_is_tswc` / `windkit_create_tswc` / `windkit_read_tswc` / `windkit_tswc_from_dataframe` / `windkit_tswc_resample`
- `windkit_validate_bwc` / `windkit_is_bwc` / `windkit_create_bwc` / `windkit_read_bwc` / `windkit_bwc_from_tswc` / `windkit_bwc_to_file` / `windkit_combine_bwcs` / `windkit_weibull_fit`
- `windkit_validate_wwc` / `windkit_is_wwc` / `windkit_create_wwc` / `windkit_read_wwc` / `windkit_read_mfwwc` / `windkit_wwc_to_file` / `windkit_wwc_to_bwc` / `windkit_weibull_combined`
- `windkit_validate_gwc` / `windkit_is_gwc` / `windkit_create_gwc` / `windkit_read_gwc` / `windkit_gwc_to_file`
- `windkit_validate_geowc` / `windkit_is_geowc`

### WindKit — Climate Statistics (7 tools)

- `windkit_create_met_fields`
- `windkit_mean_ws_moment`
- `windkit_ws_cdf`
- `windkit_ws_freq_gt_mean`
- `windkit_mean_wind_speed`
- `windkit_mean_power_density`
- `windkit_get_cross_predictions`

### WindKit — LTC (2 tools)

- `windkit_ltc_linreg_mcp`
- `windkit_ltc_varrat_mcp`

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

### Visualization

- `plot_windrose`
- `plot_weibull`
- `plot_diurnal`
- `plot_scatter`
- `plot_timeseries`
- `plot_data_coverage`
- `plot_shear_table`
- `plot_monthly_means`
- `plot_ltc_comparison`
- `plot_annual_means`
- `plot_uncertainty_breakdown`

## Build Notes

See [BUILD_SPECIFICATION.md](BUILD_SPECIFICATION.md) for the full build contract and [BUILD_INSTRUCTIONS.md](BUILD_INSTRUCTIONS.md) for the phase-by-phase implementation plan.

## Web API Endpoints

The FastAPI layer exposes session-scoped workflow endpoints under `/api/sessions/{id}/`:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/sessions` | POST | Create a new browser session |
| `/sessions/{id}/config` | GET/PUT | Read or update runconfig |
| `/sessions/{id}/config/import` | POST | Import a complete runconfig JSON payload |
| `/sessions/{id}/summary` | GET | Workflow progress and analysis readiness |
| `/sessions/{id}/era5/nodes` | POST | Find surrounding ERA5 grid nodes |
| `/sessions/{id}/era5/extract` | POST | Extract ERA5 node data |
| `/sessions/{id}/era5/interpolate` | POST | Interpolate ERA5 to site |
| `/sessions/{id}/ltc/{algorithm}` | POST | Run one LTC algorithm |
| `/sessions/{id}/ensemble` | POST | Blend LTC algorithms |
| `/sessions/{id}/uncertainty` | POST | Calculate total uncertainty |
| `/sessions/{id}/scenarios` | GET/POST | List or save scenarios |
| `/sessions/{id}/scenarios/run` | POST | Import config + execute pipeline + save scenario |
| `/sessions/{id}/scenarios/{index}` | DELETE | Remove a saved scenario |
| `/sessions/{id}/plots/{name}` | POST | Generate a named Plotly figure |
| `/sessions/{id}/exports/*` | GET | Download timeseries, LTC, ensemble, or runconfig files |
| `/sessions/{id}/brighthub/login` | POST | Authenticate with BrightHub |
| `/sessions/{id}/brighthub/logout` | POST | Clear BrightHub token |
| `/sessions/{id}/brighthub/status` | GET | Check BrightHub authentication status |
| `/sessions/{id}/brighthub/locations` | GET | List BrightHub measurement locations |
| `/sessions/{id}/brighthub/locations/{uuid}/datamodel` | GET | Fetch data model for a location |
| `/sessions/{id}/brighthub/reanalysis/nodes` | POST | Find ERA5 + MERRA-2 nodes |
| `/sessions/{id}/brighthub/reanalysis/download` | POST | Download reanalysis data (ERA5 source: BrightHub or EarthDataHub) |
| `/sessions/{id}/brighthub/import` | POST | Fetch timeseries + datamodel and load into session |
