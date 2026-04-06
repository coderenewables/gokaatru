# GoKaatru — Build Specification

> **காற்று** (*kāṟṟu*) = Wind in Tamil
>
> Wind Data Analysis MCP Server + Workflow Web App

---

## 1. System Overview

GoKaatru is a deterministic wind resource assessment (WRA) engine with two interfaces over the same analytical core:

1. A browser-based workflow web app for analysts
2. An MCP server for AI clients, automation, and debugging

The browser does not talk to MCP directly. Instead, it uses a thin HTTP API layer that calls the same session-aware backend logic as the MCP wrappers. This keeps the UI explicit and task-oriented while preserving MCP compatibility.

```
┌──────────────────────────────────────────────────────────────┐
│  Browser (Workflow Web App)                                  │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ Sidebar: workflow steps                                 │ │
│  │ Main pane: forms, charts, maps, tables, run results     │ │
│  │ Inspector: metrics, warnings, runconfig, status         │ │
│  └──────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
          │  HTTP/JSON
          ▼
┌──────────────────────────────────────────────────────────────┐
│  GoKaatru Web API (Python, FastAPI)                          │
│  • Session registry                                          │
│  • Upload and workflow endpoints                             │
│  • Calls shared analytical helpers                           │
└──────────────────────────────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────────────────────┐
│  Shared Analytics Layer                                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐       │
│  │ Data I/O │ │ Cleaning │ │ Shear    │ │ LTC/MCP   │       │
│  │ tools    │ │ tools    │ │ Extrap.  │ │ algorithms│       │
│  ├──────────┤ ├──────────┤ ├──────────┤ ├───────────┤       │
│  │ ERA5     │ │ Visual.  │ │ Rho/AirD │ │ Ensemble  │       │
│  │ Fetcher  │ │ tools    │ │ tools    │ │ Clipping  │       │
│  ├──────────┤ ├──────────┤ ├──────────┤ ├───────────┤       │
│  │ Config   │ │ Stats    │ │ Uncert.  │ │ Homogen.  │       │
│  │ Manager  │ │ tools    │ │ tools    │ │ tools     │       │
│  └──────────┘ └──────────┘ └──────────┘ └───────────┘       │
└──────────────────────────────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────────────────────┐
│  GoKaatru MCP Server  (Python, FastMCP)                      │
│  • Same logic exposed for AI clients and automation          │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. Design Principles (Non-Negotiable)

| # | Principle | Rule |
|---|-----------|------|
| 1 | **One Function, One Job** | Every MCP tool = one analytical function. No multi-purpose tools. |
| 2 | **Human-Readable** | Max 2 loop nesting. Max 50 lines logic/function. Descriptive names. |
| 3 | **Bankable Rigor** | IEC 61400-12-1, IEC 61400-12-2, TR6 compliance. Every formula cited in docstring. |
| 4 | **Deterministic** | Same input → same output. Monte Carlo accepts explicit `seed` parameter. |
| 5 | **Strict Typing** | Pydantic v2 everywhere. No `Any`. No `**kwargs`. |
| 6 | **Flat Over Nested** | Max depth 3 in JSON request/response schemas. |
| 7 | **Fail Loudly** | Validate first. Descriptive errors. No silent fallbacks. |
| 8 | **Open Source Everything** | Zero proprietary deps. All algorithms from published literature. |

---

## 3. Technology Stack

### 3.1 MCP Server

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Runtime | Python 3.11+ | NumPy/Pandas ecosystem |
| MCP Framework | `fastmcp` (PyPI) | Lightweight, stdio + SSE transport, tool decorator pattern |
| Validation | Pydantic v2 | Strict typing, JSON schema generation |
| Numerics | NumPy, SciPy, pandas | Industry standard, open source |
| ML (optional) | XGBoost, scikit-learn | LTC ML algorithm (XGBoost only) |
| Plotting | Matplotlib + Plotly JSON | Base64 PNG for static; Plotly JSON for interactive |
| ERA5 Access | `xarray` + `zarr` + `s3fs`/`fsspec` | EarthDataHub Destine Zarr store (no cdsapi) |
| Air Density | IEC 61400-12-1 formulas | Magnus formula, ideal gas law |
| Wind Rose | `windrose` (PyPI) | Open-source polar bar plotting |

### 3.2 Web API

| | |
|---|---|
| **Framework** | FastAPI |
| **Role** | Thin HTTP layer for browser clients |
| **Why** | Reuse Python analytics directly, expose typed JSON endpoints, support uploads, and avoid pushing MCP protocol concerns into the browser |

### 3.3 Frontend — Workflow Web App

| | |
|---|---|
| **Framework** | React 19 + TypeScript + Vite |
| **State** | TanStack Query for server state, Zustand for transient UI state |
| **Visualization** | Plotly.js for charts, React Leaflet for maps |
| **Routing** | React Router |
| **Why** | The product is a structured analyst workflow, not a general chat client. A route-based web app matches the domain and reduces infrastructure complexity. |

The frontend is an in-repo workflow app with explicit pages for data upload, site setup, reanalysis, long-term correction, and results. It renders Plotly JSON, GeoJSON, tables, and run summaries returned by the backend API.

### 3.4 Environment

| Component | Tool |
|-----------|------|
| Package manager | `conda` (environment: `gokaatru`) |
| Python environment | Conda env with pip for MCP-specific packages |
| Frontend runtime | Node.js 20+ |
| Frontend package manager | `npm` |
| Config | `pyproject.toml` |
| Linting | `ruff` |
| Testing | `pytest` |

---

## 4. MCP Server Architecture

### 4.1 Project Structure

```
gokaatru/
├── pyproject.toml
├── README.md
├── BUILD_SPECIFICATION.md
├── server/
│   ├── __init__.py
│   ├── api/                     # FastAPI application for the web UI
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── deps.py
│   │   └── routes/
│   │       ├── health.py
│   │       ├── sessions.py
│   │       ├── uploads.py
│   │       ├── config.py
│   │       ├── analysis.py
│   │       └── results.py
│   ├── main.py                  # FastMCP server entry point
│   ├── schemas/                 # Pydantic v2 models (all I/O types)
│   │   ├── __init__.py
│   │   ├── common.py            # Timestamp, WindRecord, Coordinate, etc.
│   │   ├── timeseries.py        # TimeseriesInput, TimeseriesStats, etc.
│   │   ├── shear.py             # ShearInput, ShearTable, etc.
│   │   ├── ltc.py               # LTCInput, LTCResult, LTCMetrics, etc.
│   │   ├── era5.py              # ERA5Query, ERA5Node, ERA5Download, etc.
│   │   ├── cleaning.py          # CleaningRule, CleaningLog, etc.
│   │   ├── uncertainty.py       # UncertaintyInput, UncertaintyResult, etc.
│   │   └── visualization.py     # PlotRequest, PlotResult, etc.
│   ├── tools/                   # MCP tool implementations (one file per domain)
│   │   ├── __init__.py
│   │   ├── data_io.py           # upload, parse, list sensors
│   │   ├── cleaning.py          # rule-based cleaning tools
│   │   ├── statistics.py        # coverage, diurnal, weibull, windrose stats
│   │   ├── shear.py             # shear calculation + table generation
│   │   ├── extrapolation.py     # hub-height extrapolation/interpolation
│   │   ├── era5.py              # ERA5 node discovery + data download
│   │   ├── ltc.py               # MCP/LTC algorithms (deterministic)
│   │   ├── ltc_ml.py            # MCP/LTC algorithm (ML: XGBoost)
│   │   ├── ensemble.py          # Multi-source ensemble
│   │   ├── clipping.py          # Clipping analysis (optimal start year)
│   │   ├── homogeneity.py       # Pettitt test, reanalysis homogeneity
│   │   ├── air_density.py       # IEC air density calculations
│   │   ├── uncertainty.py       # Uncertainty + P-values
│   │   ├── visualization.py     # Plot generation tools
│   │   ├── map.py               # Map marker generation (mast + ERA5 nodes)
│   │   └── config.py            # Run configuration management
│   ├── core/                    # Shared pure-logic modules (no MCP dependency)
│   │   ├── __init__.py
│   │   ├── formulas.py          # Cited IEC formulas (power law, log law, etc.)
│   │   ├── momm.py              # Mean of Monthly Means (Windographer-style)
│   │   ├── regression.py        # OLS, TLS, Huber robust regression
│   │   ├── spatial.py           # Haversine, IDW, linear interpolation
│   │   └── validators.py        # Reusable validation helpers
│   └── state/                   # Session state management
│       ├── __init__.py
│       ├── session.py           # Session model (per workspace)
│       └── manager.py           # Session registry and lookup helpers
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── router.tsx
│       ├── styles.css
│       ├── lib/
│       ├── stores/
│       ├── components/
│       └── pages/
├── tests/
│   ├── conftest.py
│   ├── test_shear.py
│   ├── test_ltc.py
│   ├── test_extrapolation.py
│   ├── test_air_density.py
│   ├── test_uncertainty.py
│   ├── test_era5.py
│   ├── test_api_sessions.py
│   └── test_api_workflow.py
└── data/                        # Runtime data directory (gitignored)
    ├── uploads/
    ├── era5_cache/
    ├── ltc_results/
  ├── runconfig.json
  └── sessions/
```

### 4.2 Server Entry Point

```python
# server/main.py
from fastmcp import FastMCP

mcp = FastMCP(
    name="GoKaatru",
    version="0.1.0",
    description="Wind Resource Assessment MCP Server"
)

# Tools are registered via @mcp.tool() decorators in tools/*.py
# Resources are registered via @mcp.resource() for session state

import server.tools.data_io
import server.tools.cleaning
import server.tools.statistics
import server.tools.shear
import server.tools.extrapolation
import server.tools.era5
import server.tools.ltc
import server.tools.ltc_ml      # XGBoost only
import server.tools.ensemble
import server.tools.clipping
import server.tools.homogeneity
import server.tools.air_density
import server.tools.uncertainty
import server.tools.visualization
import server.tools.map
import server.tools.config
```

---

## 5. MCP Tool Inventory

Each tool is a single-purpose function registered with `@mcp.tool()`. Inputs/outputs are Pydantic v2 models.

### 5.1 Data I/O Tools

| Tool Name | Description | Source Logic |
|-----------|-------------|-------------|
| `parse_timeseries` | Parse uploaded CSV/TSV/Excel into standard format. Auto-detect timestamp column. Support IEA Task 43 digital WRA data standard. | `utils.detect_timestamp_column_and_series` |
| `parse_datamodel` | Parse IEA Task 43 data model JSON. Extract height→column mapping. | `utils.get_available_heights_and_mapping` |
| `list_sensors` | List all sensors with height, type (speed/dir/temp/pressure), data coverage %. | `utils.get_available_heights_and_mapping` + coverage calc |
| `get_period_of_record` | Return start timestamp, end timestamp, total records, time step. | New (trivial) |
| `get_data_coverage` | Per-sensor data availability percentage and gap summary. | `visualize_TS` coverage logic |

### 5.2 Data Cleaning Tools

| Tool Name | Description | Standard |
|-----------|-------------|----------|
| `list_cleaning_rules` | Return all available rule types with descriptions and default parameters. | — |
| `apply_cleaning_rule` | Apply a single named rule to a sensor column for a date range. Log to cleaning record. | — |
| `get_cleaning_log` | Retrieve the full cleaning log (rules applied, periods, records affected). | — |
| `undo_cleaning_rule` | Remove a specific rule from the log and revert data. | — |

**Cleaning Rule Types:**
1. `range_check` — Remove values outside `[min, max]` range
2. `icing_filter` — Flag/remove periods where SD = 0 and temp < threshold
3. `stuck_sensor` — Flag repeating identical values for N consecutive records
4. `tower_shadow` — Exclude direction sectors with known tower shadow
5. `spike_filter` — Remove values exceeding N×σ from rolling window mean
6. `timestamp_gap_fill` — Insert NaN rows for missing timestamps
7. `custom_period_exclude` — Exclude a user-defined date range

### 5.3 Statistics Tools

| Tool Name | Description | Formula Reference |
|-----------|-------------|-------------------|
| `compute_weibull_params` | Fit Weibull distribution (A, k) to wind speed series. | `scipy.stats.weibull_min.fit(data, floc=0)` |
| `compute_windrose_data` | Compute frequency/speed by direction sector for windrose plot. | IEC 61400-12-1 §A.1 |
| `compute_diurnal_profile` | Monthly-hourly mean wind speed (MoMM-weighted). | Windographer MoMM method |
| `compute_monthly_stats` | Monthly mean, min, max, energy density, data coverage. | — |
| `compute_turbulence_intensity` | TI = σ / μ per wind speed bin (IEC method). | IEC 61400-1 Ed.4 §6.3 |
| `compute_momm` | Mean of Monthly Means for any sensor column. | TR6 / Windographer |
| `compute_scatter_stats` | Scatter statistics between two sensors (R², RMSE, bias, slope). | — |

### 5.4 Wind Shear & Extrapolation Tools

| Tool Name | Description | Formula Reference |
|-----------|-------------|-------------------|
| `calculate_shear_timeseries` | Power-law shear α at each timestamp from multi-height data. Weighted least-squares on log(v) vs log(h). | IEC 61400-12-1 §B.2; `extrapolation.calculate_shear_timeseries` |
| `calculate_roughness_timeseries` | Log-law roughness z₀ at each timestamp. Linear regression of U vs ln(z), z₀ = exp(−b/a). | IEC 61400-12-1 §B.3; `extrapolation.calculate_roughness_timeseries` |
| `build_shear_table` | 12×24 month-hour lookup table of shear α. Aggregation: mean, median, or MoMM. | `extrapolation.create_monthly_hourly_shear_table` |
| `build_roughness_table` | 12×24 month-hour lookup table of roughness z₀ (log-space aggregation). | `extrapolation.create_monthly_hourly_roughness_table` |
| `build_sector_shear_tables` | Per-sector 12×24 shear tables (direction-stratified). | `extrapolation.create_sector_shear_tables` |
| `build_aggr_momm_shear_table` | Aggregate MoMM approach: MoMM per wind speed per height first, then derive α. | `extrapolation._create_aggr_momm_shear_table` |
| `extrapolate_to_hub_height` | Calculate hub-height wind speed via power law or log law. Auto-detect interpolation vs extrapolation. | `extrapolation.calculate_hub_height_wind_speed` |
| `extrapolate_reanalysis_to_hub` | Extrapolate ERA5/reanalysis data to hub height using provided shear table. | `extrapolation.extrapolate_reanalysis_to_hub_height` |

### 5.5 ERA5 / Reanalysis Tools

| Tool Name | Description | Source |
|-----------|-------------|--------|
| `find_era5_nodes` | Given lat/lon, find nearest 4 ERA5 grid points. Return coordinates + distance from mast. | `utils.fetch_reanalysis_nodes`, Haversine |
| `extract_era5_data` | Extract ERA5 hourly data for a node from Zarr store via xarray (2000-01-01 to latest). Variables: u100, v100, sp, t2m, d2m. No file download — streamed from Zarr chunks. | EarthDataHub Zarr (`data.earthdatahub.destine.eu`) |
| `interpolate_era5_to_site` | Spatially interpolate 4 ERA5 nodes to mast location (linear, IDW fallback). | `utils.interpolate_spatial` |
| `compute_era5_wind_speed` | Convert u100, v100 components to wind speed and direction at 100 m. | $V = \sqrt{u^2 + v^2}$, $\theta = \text{atan2}(-u, -v)$ |

**ERA5 Variables:**

| Variable | ERA5 Key | Physical Quantity |
|----------|----------|-------------------|
| u100 | `100m_u_component_of_wind` | Eastward wind at 100 m (m/s) |
| v100 | `100m_v_component_of_wind` | Northward wind at 100 m (m/s) |
| sp | `surface_pressure` | Surface pressure (Pa) |
| t2m | `2m_temperature` | 2 m temperature (K) |
| d2m | `2m_dewpoint_temperature` | 2 m dewpoint (K) |
| ust | `friction_velocity` | Friction velocity (m/s) |
| blh | `boundary_layer_height` | BL height (m) |
| sshf | `surface_sensible_heat_flux` | Sensible heat flux (W/m²) |

### 5.6 Long-Term Correction (LTC / MCP) Tools

| Tool Name | Algorithm | Description | Formula Reference |
|-----------|-----------|-------------|-------------------|
| `run_ltc_linear_least_squares` | Linear Least Squares | Robust (Huber) regression of measured vs reference. | `LTC_engine.linear_least_squares` |
| `run_ltc_total_least_squares` | Total Least Squares | Orthogonal regression minimizing perpendicular distances (SVD). | `LTC_engine.total_least_squares` |
| `run_ltc_speedsort` | SpeedSort | Robust fit on high-wind tail + dog-leg below threshold. | `LTC_engine.speedsort` |
| `run_ltc_variance_ratio` | Variance Ratio | Distribution linking via mean and std ratio. | `LTC_engine.variance_ratio` |
| `run_ltc_xgboost` | XGBoost | Gradient-boosted trees with temporal/directional features, early stopping, feature importance. | `LTC_engine_ML.xgboost_mcp` |

**Common LTC Output Schema:**
```json
{
  "result_file": "path/to/corrected_timeseries.csv",
  "metrics": {
    "algorithm": "speedsort",
    "regression_slope": 1.023,
    "regression_intercept": -0.15,
    "r_squared": 0.87,
    "rmse_concurrent": 1.42,
    "mae_concurrent": 1.08,
    "mbe_concurrent": -0.03,
    "concurrent_data_points": 8760,
    "total_corrected_points": 219000
  }
}
```

### 5.7 Ensemble & Post-Processing Tools

| Tool Name | Description | Source Logic |
|-----------|-------------|-------------|
| `run_ensemble` | Inverse-RMSE weighted ensemble of multiple LTC outputs. Bias-correct each source, then weighted average. | `ensemble.perform_ensemble` |
| `run_clipping_analysis` | Find optimal LT start year minimizing combined historic + climate uncertainty (IAV-based). | `clippinganalysis.run_clipping_analysis` |
| `analyze_homogeneity` | Pettitt non-parametric test for change-points in reanalysis series. Recommend start year. | `rho.analyze_homogeneity` |
| `apply_homogeneity_cutoff` | Trim reanalysis data to post-changepoint period. | `rho.apply_cutoff` |

### 5.8 Air Density Tools

| Tool Name | Description | Formula Reference |
|-----------|-------------|-------------------|
| `compute_air_density` | IEC air density from pressure, temperature, dewpoint. Uses Magnus saturation vapor pressure formula + moist air equation of state. | IEC 61400-12-1 §A.5 |
| `compute_air_density_timeseries` | Air density for each timestamp in a dataset. | IEC 61400-12-1 §A.5 |

**Formulas (IEC 61400-12-1):**
- Saturation vapor pressure: $e_s = 6.1078 \times 10^{(7.5 T_d)/(237.3 + T_d)}$ (hPa)
- Moist air density: $\rho = \frac{1}{T} \left( \frac{P - e}{R_d} + \frac{e}{R_v} \right)$
  - where $R_d = 287.05$ J/(kg·K), $R_v = 461.5$ J/(kg·K)

### 5.9 Uncertainty Tools

| Tool Name | Description | Formula Reference |
|-----------|-------------|-------------------|
| `calculate_uncertainty` | RSS of measurement, vertical extrapolation, MCP, and future variability uncertainties. Returns P50/P75/P90/P99 factors. | TR6 methodology; `uncertainty.calculate_uncertainty` |

**Uncertainty Components:**
1. **Measurement** ($u_{meas}$): User-provided (% of mean speed)
2. **Vertical Extrapolation** ($u_{vert}$): $k_{shear} \times |\ln(h_{hub}/h_{meas})| \times 100$
3. **MCP** ($u_{MCP}$): $\frac{u_{base}}{\sqrt{N_{months}}} + (1 - R^2) \times C_{algo}$
4. **Future Variability** ($u_{future}$): $\frac{IAV}{\sqrt{20}}$ (20-year project life)
5. **Total**: $u_{total} = \sqrt{u_{meas}^2 + u_{vert}^2 + u_{MCP}^2 + u_{future}^2}$

**P-value factors:**
- P50: 1.0
- P75: $1 - 0.674 \times u_{total}/100$
- P90: $1 - 1.282 \times u_{total}/100$
- P99: $1 - 2.326 \times u_{total}/100$

### 5.10 Visualization Tools

| Tool Name | Description | Output |
|-----------|-------------|--------|
| `plot_windrose` | Polar bar chart of wind speed by direction. | Plotly JSON |
| `plot_weibull` | Histogram + fitted Weibull PDF overlay. | Plotly JSON |
| `plot_diurnal` | Line chart of mean wind speed by hour (optionally by month). | Plotly JSON |
| `plot_scatter` | Scatter of two sensors/columns with regression line and stats. | Plotly JSON |
| `plot_timeseries` | Time series overlay of selected columns. | Plotly JSON |
| `plot_data_coverage` | Horizontal bar showing data availability periods per sensor. | Plotly JSON |
| `plot_shear_table` | Heatmap of 12×24 shear/roughness table. | Plotly JSON |
| `plot_monthly_means` | Bar chart of MoMM by month across multiple datasets. | Plotly JSON |
| `plot_ltc_comparison` | Multi-algorithm overlay: scatter, histogram, KDE, MoMM, energy convergence. | Plotly JSON |
| `plot_annual_means` | Annual mean wind speed time series for LT datasets. | Plotly JSON |
| `plot_uncertainty_breakdown` | Stacked bar of uncertainty components. | Plotly JSON |

### 5.11 Map Tools

| Tool Name | Description | Output |
|-----------|-------------|--------|
| `get_mast_marker` | Return GeoJSON marker for measurement mast location. | GeoJSON Feature |
| `get_era5_node_markers` | Return GeoJSON markers for ERA5 grid points with distance labels. | GeoJSON FeatureCollection |
| `get_site_overview_map` | Combined mast + ERA5 nodes + labels. | GeoJSON FeatureCollection |

### 5.12 Configuration Tools

| Tool Name | Description |
|-----------|-------------|
| `get_run_config` | Return the current run configuration (all choices made so far). |
| `update_run_config` | Update a specific configuration key (hub height, shear method, sensor selection, etc.). |
| `save_run_config` | Persist runconfig.json to disk. |
| `load_run_config` | Load runconfig.json from disk. |
| `get_analysis_summary` | Return summary of all analysis steps completed and their outputs. |

---

## 6. Pydantic v2 Schema Design

### 6.1 Common Types

```python
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Literal

class Coordinate(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    elevation_m: float = Field(default=0.0, ge=-500, le=9000)

class SensorInfo(BaseModel):
    name: str
    height_m: float = Field(..., gt=0)
    sensor_type: Literal["wind_speed", "wind_direction", "temperature", "pressure"]
    data_coverage_pct: float = Field(..., ge=0, le=100)
    record_count: int = Field(..., ge=0)

class PeriodOfRecord(BaseModel):
    start: datetime
    end: datetime
    total_records: int
    timestep_minutes: int
    sensors: list[SensorInfo]

class ShearTable(BaseModel):
    """12×24 month-hour lookup table."""
    values: list[list[float]]  # 12 rows (months) × 24 cols (hours)
    method: Literal["power_law", "log_law"]
    aggregation: Literal["mean", "median", "momm", "aggr_momm"]
    sector: str | None = None  # None = omnidirectional

class LTCMetrics(BaseModel):
    algorithm: str
    r_squared: float
    rmse_concurrent: float
    mae_concurrent: float
    mbe_concurrent: float
    regression_slope: float | None = None
    regression_intercept: float | None = None
    concurrent_data_points: int
    total_corrected_points: int

class CleaningLogEntry(BaseModel):
    rule_type: str
    sensor: str
    start_time: datetime
    end_time: datetime
    records_affected: int
    parameters: dict[str, float | str | int]
    applied_at: datetime

class UncertaintyResult(BaseModel):
    total_uncertainty_pct: float
    components: dict[str, float]  # measurement, vertical, mcp, future
    p_factors: dict[str, float]   # p50, p75, p90, p99
```

### 6.2 Tool I/O Patterns

Every tool follows this contract:
- **Input**: Pydantic model (flat, max depth 3)
- **Output**: Pydantic model or `dict` serializable to JSON
- **Errors**: Raise `ValueError` with descriptive message (MCP framework converts to error response)

---

## 7. ERA5 Data Integration

### 7.1 Data Source

- **Primary**: EarthDataHub Destine — Zarr store at `https://data.earthdatahub.destine.eu/era5/reanalysis-era5-single-levels-v0.zarr`
- **Access method**: `xarray.open_dataset()` with `engine="zarr"` — **no cdsapi, no file downloads**
- **Authentication**: User provides EarthDataHub API token (set as env var or passed to `storage_options`)
- **Token setup guide**: `https://earthdatahub.destine.eu/getting-started#obtain-access-token`

### 7.2 Zarr Access Pattern

```python
import xarray as xr

ds = xr.open_dataset(
    "https://data.earthdatahub.destine.eu/era5/reanalysis-era5-single-levels-v0.zarr",
    storage_options={"client_kwargs": {"trust_env": True}},
    chunks={},
    engine="zarr",
)

# Slice to region + time range (lazy — only fetches needed chunks)
subset = ds.sel(
    latitude=slice(lat + 0.5, lat - 0.5),   # ERA5 lat is descending
    longitude=slice(lon - 0.5, lon + 0.5),
    time=slice("2000-01-01", "2025-12-31"),
)[["u100", "v100", "sp", "t2m", "d2m"]]

df = subset.to_dataframe().reset_index()
```

### 7.3 Data Specification

| Parameter | Value |
|-----------|-------|
| Nodes | Nearest 4 grid points to measurement location (0.25° grid) |
| Period | 2000-01-01 to latest available |
| Frequency | Hourly |
| Variables | u100, v100, sp, t2m, d2m (+ ust, blh, sshf if available in store) |
| Format | Zarr (cloud-native) → sliced in-memory via xarray → pandas DataFrame |
| No local files | Data is streamed on-demand; optional local caching via `xarray` disk cache |

### 7.4 Processing Pipeline

```
1. find_era5_nodes(lat, lon)
   → Open Zarr store, read lat/lon coordinate arrays
   → Find nearest 4 grid points, compute Haversine distances

2. extract_era5_data(lat, lon, start_date, end_date, variables)
   → xr.open_dataset(..., engine="zarr")
   → ds.sel(latitude=..., longitude=..., time=slice(...))
   → .to_dataframe() per grid point
   → No file download — data streamed from Zarr chunks

3. compute_era5_wind_speed(u100, v100)
   → Spd_100m, Dir_100m

4. interpolate_era5_to_site([node1, node2, node3, node4], site_coords)
   → Single interpolated time series at mast location
   → Linear griddata with IDW fallback
```

---

## 8. Core Algorithm Specifications

### 8.1 Wind Shear — Power Law

$$V(z_2) = V(z_1) \left(\frac{z_2}{z_1}\right)^\alpha$$

**Shear exponent α calculation** (weighted least squares, multi-height):
$$\alpha = \frac{\sum w_i \cdot \ln(h_i^{(2)}/h_i^{(1)}) \cdot \ln(v_i^{(2)}/v_i^{(1)})}{\sum w_i \cdot \left[\ln(h_i^{(2)}/h_i^{(1)})\right]^2}$$
where $w_i = |\ln(h_i^{(2)}/h_i^{(1)})|$ (weight by height separation).

**Reference**: IEC 61400-12-1 §B.2

### 8.2 Wind Shear — Log Law

$$V(z) = \frac{u_*}{\kappa} \ln\left(\frac{z}{z_0}\right)$$

**Roughness z₀ derivation**: Linear regression of $V$ vs $\ln(z)$, then $z_0 = \exp(-b/a)$ where $a = u_*/\kappa$, $b = -a \ln(z_0)$.

**Reference**: IEC 61400-12-1 §B.3

### 8.3 MoMM (Mean of Monthly Means) — Windographer Method

$$\text{MoMM}_{m,h} = \frac{\sum_{y} \mu_{y,m,h} \cdot \lambda_{y,m,h} \cdot \psi_m}{\sum_{y} \lambda_{y,m,h} \cdot \psi_m}$$

Where:
- $\mu_{y,m,h}$ = mean value in year $y$, month $m$, hour $h$
- $\lambda_{y,m,h}$ = completeness ratio (valid samples / expected samples)
- $\psi_m$ = mean number of days in month $m$ (e.g., Feb = 28.24)

### 8.4 LTC — Linear Least Squares (Robust Huber)

Iteratively reweighted least squares using Huber loss ($\delta = 1.35$):
$$V_{site} = a \cdot V_{ref} + b$$

Outlier re-weighting: $w_i = \min\left(1, \frac{\delta}{|z_i|}\right)$ where $z_i = (y_i - \hat{y}_i) / \text{MAD}$

### 8.5 LTC — Total Least Squares (Orthogonal Regression)

Minimizes perpendicular distances using SVD decomposition. Fit: $V_{site} = a \cdot V_{ref} + b$ where $(a, b)$ are derived from the right singular vector corresponding to the smallest singular value.

### 8.6 LTC — SpeedSort

1. Sort reference speeds ascending
2. Threshold: $\min(4.0,\ 0.5 \times \bar{V}_{ref})$
3. Above threshold: TLS regression → slope $a$, intercept $b$
4. Below threshold: Dog-leg through origin → slope $= (a \cdot T + b) / T$
5. Apply piecewise to full long-term record

### 8.7 LTC — Variance Ratio

$$V_{corrected} = \bar{V}_{site} + \frac{\sigma_{site}}{\sigma_{ref}} \cdot (V_{ref,LT} - \bar{V}_{ref})$$

### 8.8 Clipping Analysis (Optimal Start Year)

For each candidate start year $Y$:
1. **Historic uncertainty**: $u_H = \frac{IAV}{\sqrt{N_{years}}}$
2. **Climate uncertainty**: $u_C = f_1 + f_2 \cdot \exp\left[-1 + \left(1 + \ln\frac{C_{max} - f_1}{f_2}\right) \cdot D^5\right]$
   - $D = |1 - 2\Phi(\text{LTA}_{5yr};\ 1,\ IAV/\sqrt{5})|$
3. **Combined**: $u_{total} = \sqrt{u_H^2 + u_C^2}$
4. **Optimal**: $Y^* = \arg\min_Y u_{total}$

Parameters: $f_1 = 0.005$, $f_2 = 0.01$, $C_{max} = 0.04$, training period = 5 years.

### 8.9 Ensemble (Inverse-RMSE Weighting)

1. Compute bias and RMSE for each LTC source vs measured (overlap period)
2. Weights: $w_i = \frac{1/\text{RMSE}_i}{\sum_j 1/\text{RMSE}_j}$
3. Bias-correct: $x'_i = x_i - \text{bias}_i$
4. Ensemble: $\hat{y} = \sum_i w_i \cdot x'_i$

### 8.10 Homogeneity — Pettitt Test

Non-parametric change-point test:
$$U_k = 2 \sum_{i=1}^{k} R_i - k(n+1)$$
$$K = \max_k |U_k|$$
$$p \approx 2 \exp\left(\frac{-6K^2}{n^3 + n^2}\right)$$

---

## 9. User Interaction Flow

### Phase 1: Setup
```
1. User opens GoKaatru UI
2. Configure LLM: select provider (OpenAI/Anthropic/OpenRouter), paste API key, select model
3. Configure ERA5: paste EarthDataHub API token
   → Link to https://earthdatahub.destine.eu/getting-started#obtain-access-token
4. Left pane: GoKaatru logo + setup form
```

### Phase 2: Data Import
```
5. Upload wind data:
   a. IEA Task 43 data model JSON + 10-min CSV, OR
   b. Plain CSV/TSV/Excel file
6. If plain file → chat prompts for: latitude, longitude, elevation,
   measurement type (lidar/mast/sodar), sensor metadata
7. MCP tool: parse_timeseries → parse_datamodel → list_sensors
8. Left pane: map with mast marker + data summary table
```

### Phase 3: Data Quality
```
9. Chat: "Here are the available cleaning rules: [list from list_cleaning_rules]"
10. User defines rules via chat OR LLM suggests rules based on data patterns
11. MCP tool: apply_cleaning_rule (for each rule)
12. Cleaning log captured and persisted
13. Visualization tools render before/after coverage, timeseries
```

### Phase 4: Reanalysis
```
14. MCP tool: find_era5_nodes → 4 points plotted on map with distances
15. MCP tool: extract_era5_data (×4 nodes, streamed from Zarr)
16. MCP tool: compute_era5_wind_speed → interpolate_era5_to_site
17. Left pane: map updated with ERA5 markers + distance labels
```

### Phase 5: Shear & Extrapolation
```
18. User selects shear method and sensors via chat
19. MCP tool: calculate_shear_timeseries → build_shear_table
    Options: annual 12×24, sector-wise 12×24, MoMM aggregation
20. MCP tool: extrapolate_to_hub_height (measured data)
21. MCP tool: extrapolate_reanalysis_to_hub (ERA5 data)
```

### Phase 6: Long-Term Correction
```
22. MCP tool: analyze_homogeneity → recommended start years
23. User selects algorithm(s) via chat
24. MCP tool: run_ltc_* (one or more algorithms)
25. MCP tool: run_ensemble (if multiple algorithms)
26. MCP tool: run_clipping_analysis → optimal period
27. Visualization tools: scatter, diurnal, MoMM comparison
```

### Phase 7: Uncertainty & Results
```
28. MCP tool: calculate_uncertainty → P50/P75/P90/P99
29. MCP tool: plot_uncertainty_breakdown
30. MCP tool: save_run_config (full configuration JSON)
```

### Phase 8: Iteration
```
31. User changes: hub height / shear method / sensor / algorithm / cleaning
32. Relevant tools re-run automatically
33. Results stored as new analysis run
34. Left pane: compare runs side-by-side
```

---

## 10. Configuration Schema (runconfig.json)

```json
{
  "project_name": "Site Alpha WRA",
  "location": {
    "latitude": 52.4,
    "longitude": 4.8,
    "elevation_m": 0.0,
    "measurement_type": "mast"
  },
  "hub_height_m": 150,
  "data_files": {
    "timeseries": "uploads/ts_abc123.csv",
    "datamodel": "uploads/datamodel_abc123.json"
  },
  "sensors": {
    "shear_sensors": [100, 80, 60],
    "primary_speed": "Spd_100m",
    "primary_direction": "Dir_100m"
  },
  "cleaning": {
    "rules_applied": [
      {
        "rule_type": "range_check",
        "sensor": "Spd_100m",
        "params": {"min": 0.3, "max": 40.0},
        "period": {"start": "2022-01-01", "end": "2023-12-31"},
        "records_affected": 42
      }
    ]
  },
  "shear": {
    "method": "power_law",
    "table_aggregation": "momm",
    "scope": "annual",
    "sector_count": 12
  },
  "era5": {
    "nodes": [
      {"lat": 52.25, "lon": 4.75, "distance_km": 18.3},
      {"lat": 52.25, "lon": 5.00, "distance_km": 15.1},
      {"lat": 52.50, "lon": 4.75, "distance_km": 11.7},
      {"lat": 52.50, "lon": 5.00, "distance_km": 14.9}
    ],
    "download_period": {"start": "2000-01-01", "end": "2024-12-31"},
    "variables": ["u100", "v100", "sp", "t2m", "d2m", "ust", "blh", "sshf"]
  },
  "ltc": {
    "algorithms": ["speedsort", "variance_ratio", "xgboost"],
    "concurrent_period": {"start": "2022-03-15", "end": "2023-09-30"},
    "optimal_start_year": 2003,
    "ensemble_weights": {
      "speedsort": 0.35,
      "variance_ratio": 0.30,
      "xgboost": 0.35
    }
  },
  "uncertainty": {
    "measurement_pct": 3.5,
    "iav_pct": 6.0,
    "total_pct": 5.87,
    "p90_factor": 0.9248
  }
}
```

---

## 11. Testing Strategy

| Layer | Scope | Framework |
|-------|-------|-----------|
| Unit | Each core formula function (regression, shear, air density) | pytest |
| Integration | Tool chain: parse → clean → shear → extrapolate → LTC | pytest |
| Determinism | Same input CSV + seed → bit-identical output | pytest parametrize |
| Schema | Pydantic model validation round-trip | pytest |
| Edge cases | Empty data, single-height shear, zero variance, NaN-heavy series | pytest |

### Test Data
- Synthetic 10-min timeseries (1 year, 3 heights) with known shear α = 0.14
- Synthetic reference series with known linear relationship to measured
- ERA5 sample node (4-point grid, 1 month)

---

## 12. Deployment

### Local Development
```bash
conda activate gokaatru
pip install -e ".[dev]"
python -m server.main          # stdio mode (for MCP client)
python -m server.main --sse    # SSE mode (for web frontend)
```

### Docker (Production)
```dockerfile
FROM python:3.11-slim
COPY . /app
WORKDIR /app
RUN pip install --no-cache-dir .
EXPOSE 8080
CMD ["python", "-m", "server.main", "--sse", "--port", "8080"]
```

### Web App Connection
- Browser talks to `http://localhost:8000/api`
- Each request carries a session identifier so backend state is workspace-scoped
- FastAPI routes call the same analytical helpers used by the MCP server
- Plotly JSON and GeoJSON are rendered directly in the web app
- MCP over SSE remains available at `http://localhost:8080/sse` for AI clients and debugging

---

## 13. Implementation Phases

### Phase 1 — Foundation (Tools 1-15)
- MCP server scaffold with FastMCP
- Pydantic schemas (common, timeseries, shear)
- Data I/O tools: `parse_timeseries`, `parse_datamodel`, `list_sensors`, `get_period_of_record`, `get_data_coverage`
- Statistics tools: `compute_weibull_params`, `compute_windrose_data`, `compute_diurnal_profile`, `compute_monthly_stats`, `compute_momm`
- Configuration tools: `get_run_config`, `update_run_config`, `save_run_config`
- Basic test suite

### Phase 2 — Shear & Extrapolation (Tools 16-24)
- Shear tools: `calculate_shear_timeseries`, `build_shear_table`, `build_sector_shear_tables`, `build_aggr_momm_shear_table`
- Roughness tools: `calculate_roughness_timeseries`, `build_roughness_table`
- Extrapolation tools: `extrapolate_to_hub_height`, `extrapolate_reanalysis_to_hub`
- Cleaning tools: `list_cleaning_rules`, `apply_cleaning_rule`, `get_cleaning_log`

### Phase 3 — ERA5 & LTC (Tools 25-35)
- ERA5 tools: `find_era5_nodes`, `extract_era5_data`, `interpolate_era5_to_site`, `compute_era5_wind_speed`
- LTC deterministic: `run_ltc_linear_least_squares`, `run_ltc_total_least_squares`, `run_ltc_speedsort`, `run_ltc_variance_ratio`
- LTC ML: `run_ltc_xgboost`
- Air density: `compute_air_density`, `compute_air_density_timeseries`

### Phase 4 — Post-Processing & Polish (Tools 36-50+)
- Ensemble: `run_ensemble`
- Clipping: `run_clipping_analysis`
- Homogeneity: `analyze_homogeneity`, `apply_homogeneity_cutoff`
- Uncertainty: `calculate_uncertainty`
- All visualization tools
- Map tools
- End-to-end workflow validation

### Phase 5 — Integration & Deployment
- End-to-end workflow test
- Docker packaging for the MCP server
- Local development Compose stack
- Example environment overrides
- MCP configuration for external clients

### Phase 6 — Workflow Web App
- Session registry refactor for browser-safe workspaces
- FastAPI web API over the existing analytical backend
- React/Vite workflow UI with route-based pages
- Upload, configuration, ERA5, LTC, and results workspaces
- Frontend build, API tests, and browser workflow validation

---

## 14. Decisions Log

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | Frontend | **In-repo React/Vite workflow app** | The product is a structured WRA workflow. A purpose-built UI is simpler and more controllable than a chat platform. |
| 2 | ERA5 Zarr caching | **Local disk cache** | Cache extracted DataFrames as Parquet on first fetch. ~500 MB/node but fast on repeat queries. Stored in `data/era5_cache/` |
| 3 | State persistence | **Session-scoped filesystem JSON + CSV** | Each browser workspace gets its own in-memory session and `data/sessions/<id>/` folder. Simple, inspectable, and safer than a global singleton. |
| 4 | Visualization format | **Both (Plotly JSON + PNG fallback)** | Plotly JSON is the primary format for the web UI; Base64 PNG remains the fallback for non-interactive contexts. |
| 5 | Multi-user support | **Session-scoped local workspaces** | Support multiple browser sessions on one host without adding full authentication or a database in the first web phase. |
| 6 | External interface | **HTTP API for UI, MCP SSE/stdio for AI and debug** | The browser gets simple JSON endpoints; MCP remains available for desktop clients, automation, and future AI integration. |
