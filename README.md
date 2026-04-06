# GoKaatru

GoKaatru is a Wind Resource Assessment MCP server for ingesting wind measurement data, cleaning and extrapolating it, correlating it against ERA5 reanalysis, and producing long-term correction, uncertainty, visualization, and mapping outputs. The server exposes 59 MCP tools grouped across data I/O, statistics, shear, ERA5, LTC, post-processing, visualization, and configuration workflows, with `runconfig` as the source of truth for site metadata such as location and hub height.

## Quick Start (Local)

```bash
conda activate gokaatru
pip install -e ".[ml,dev]"
python -m server.main
```

For a local SSE server that LibreChat or any network client can reach:

```bash
python -m server.main --transport sse --host 0.0.0.0 --port 8080
```

## Quick Start (Docker)

```bash
docker compose up --build
```

The GoKaatru SSE endpoint will be available at `http://localhost:8080/sse`, and LibreChat will be available at `http://localhost:3080`.

## LibreChat Setup

If you use the included Docker Compose stack, LibreChat reads [librechat_config.yaml](librechat_config.yaml) automatically and connects to the `gokaatru` service over the internal Docker network using `http://gokaatru:8080/sse`.

If LibreChat runs outside Docker, add this MCP server entry to its `librechat.yaml`:

```yaml
mcpServers:
  gokaatru:
    type: sse
    url: http://localhost:8080/sse
    timeout: 120000
```

## Validation

The completed repository has been validated with 59 registered MCP tools and 40 automated tests.

```bash
python -m ruff check server/ tests/
python -m pytest tests/ -v
python -m server.main --help
python -c "import asyncio, json; from server.main import mcp; print(json.dumps([tool.name for tool in asyncio.run(mcp.list_tools())], indent=2))"
docker build -t gokaatru .
docker compose config
```

## Tool Inventory

### Air Density

- `compute_air_density`
- `compute_air_density_timeseries`

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
