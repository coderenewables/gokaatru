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

The Compose stack starts three services:

- GoKaatru at `http://localhost:8080/sse`
- LibreChat at `http://localhost:3080`
- MongoDB for LibreChat at `mongodb://localhost:27017/LibreChat`

The checked-in Compose file includes a local MongoDB container plus the minimum LibreChat environment needed for startup. For local overrides, copy [.env.example](.env.example) to `.env` and replace the LibreChat secret placeholders before starting the stack.

## LibreChat Setup

If you use the included Docker Compose stack, LibreChat reads [librechat_config.yaml](librechat_config.yaml) automatically. The checked-in config includes the required `version` field plus an MCP domain allowlist for both `http://gokaatru:8080` and `http://localhost:8080`, so it can initialize the GoKaatru SSE server inside Docker and from a host-local LibreChat setup.

The Compose stack also configures `OPENAI_API_KEY=user_provided` by default so LibreChat can start without a baked-in provider secret. You still need to supply a real model provider key in LibreChat before you can use chat completions.

If LibreChat runs outside Docker, add this MCP server entry to its `librechat.yaml`:

```yaml
version: "1.3.6"

mcpSettings:
  allowedDomains:
    - http://localhost:8080

mcpServers:
  gokaatru:
    type: sse
    url: http://localhost:8080/sse
    timeout: 120000
```

## Validation

The repository has been validated with 59 registered MCP tools plus backend API and frontend workflow coverage.

```bash
python -m ruff check server/ tests/
python -m pytest tests/ -v
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
