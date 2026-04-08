# GoKaatru — Phase-by-Phase Build Instructions

> **For AI coding agents.** Read `BUILD_SPECIFICATION.md` first for full context.
> Each phase is self-contained: complete it, test it, then move to the next.

---

## GLOBAL RULES (Apply to ALL phases)

### Code Style
- Python 3.11+. Use `from __future__ import annotations` in every file.
- Pydantic v2 **only**. No v1 compat. Use `model_validator`, `field_validator`, not old `@validator`.
- No `Any` type. No `**kwargs`. No `Optional` — use `X | None` instead.
- Max 50 lines per function. Max 2 levels of loop nesting. Break into helpers.
- Every function has a docstring citing the formula or standard (e.g., "IEC 61400-12-1 §B.2").
- Use `numpy` for vectorized operations. Avoid Python loops over timeseries rows.
- `ruff` clean. No unused imports, no bare excepts.
- Descriptive error messages: `raise ValueError("Shear requires ≥2 heights, got 1")`.

### File Headers
Every `.py` file starts with:
```python
"""<module_name> — <one-line description>.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations
```

### MCP Tool Pattern
Every tool follows this exact pattern:
```python
from server.main import mcp

@mcp.tool()
def tool_name(param1: str, param2: float) -> dict:
    """One-sentence description of what this tool does."""
    # 1. Validate inputs
    # 2. Load data from session state
    # 3. Compute
    # 4. Return result dict (flat, max depth 3)
```

### Testing Pattern
Every tool gets a test:
```python
def test_tool_name():
    # Arrange: create minimal input
    # Act: call the function directly (not via MCP)
    # Assert: check output values, types, keys
```

### Environment Setup (run once before any phase)
```bash
Use conda hook to create and activate environment: C:\ProgramData\anaconda3\shell\condabin\conda-hook.ps1
conda activate gokaatru
pip install fastmcp pydantic numpy scipy pandas matplotlib plotly windrose xarray zarr fsspec s3fs ruff pytest
```

---

## PHASE 1 — Foundation

**Goal**: MCP server runs, accepts tool calls, can parse wind data files, compute basic statistics, and manage configuration.

**Files to create** (in order):

---

### Step 1.1: Project skeleton

Create the directory structure and `pyproject.toml`.

**File: `pyproject.toml`**
```toml
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "gokaatru"
version = "0.1.0"
description = "Wind Resource Assessment MCP Server"
requires-python = ">=3.11"
dependencies = [
    "fastmcp>=2.0.0",
    "pydantic>=2.0",
    "numpy>=1.24",
    "scipy>=1.10",
    "pandas>=2.0",
    "matplotlib>=3.7",
    "plotly>=5.15",
    "windrose>=1.9",
    "xarray>=2023.1",
    "zarr>=2.14",
    "fsspec>=2023.1",
    "s3fs>=2023.1",
]

[project.optional-dependencies]
ml = ["xgboost>=1.7", "scikit-learn>=1.2"]
dev = ["pytest>=7.0", "ruff>=0.1"]

[tool.ruff]
line-length = 120
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "W"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

**Create these empty directories + `__init__.py` files:**
```
server/__init__.py           (empty)
server/schemas/__init__.py   (empty)
server/tools/__init__.py     (empty)
server/core/__init__.py      (empty)
server/state/__init__.py     (empty)
tests/__init__.py            (empty)
tests/conftest.py            (empty for now)
data/uploads/                (empty dir)
data/era5_cache/             (empty dir)
data/ltc_results/            (empty dir)
```

Also create `.gitignore`:
```
data/
__pycache__/
*.pyc
.ruff_cache/
*.egg-info/
dist/
build/
```

---

### Step 1.2: Session state manager

**File: `server/state/session.py`**

This is an in-memory singleton that holds the current project state. All tools read/write to this.

Implement:
- `class SessionState` with these attributes:
  - `project_name: str | None`
  - `coordinate: Coordinate | None` (from schemas)
  - `measurement_type: str | None` (lidar/mast/sodar)
  - `hub_height_m: float | None`
  - `timeseries_df: pd.DataFrame | None` — the loaded timeseries data
  - `raw_timeseries_df: pd.DataFrame | None` — backup before cleaning
  - `sensor_mapping: dict[float, dict[str, str | None]]` — height → {speed_col, dir_col, sd_col, temp_col, pressure_col}
  - `cleaning_log: list[dict]` — list of cleaning log entries
  - `shear_table: pd.DataFrame | None` — 12×24
  - `roughness_table: pd.DataFrame | None` — 12×24
  - `era5_nodes: list[dict] | None`
  - `era5_data: dict[str, pd.DataFrame]` — key = "lat_lon" string
  - `era5_interpolated_df: pd.DataFrame | None`
  - `ltc_results: dict[str, dict]` — algorithm_name → {result_df, metrics}
  - `ensemble_df: pd.DataFrame | None`
  - `runconfig: dict` — full config dict

- Module-level singleton: `session = SessionState()`
- Method `reset()` → clears all fields back to None/empty
- Method `to_runconfig() -> dict` → serializes current state to runconfig dict
- Method `get_data_dir() -> str` → returns `"data"`, creates if not exists

**Important**: `pd.DataFrame` fields are NOT Pydantic models. `SessionState` is a plain Python class (not BaseModel) since DataFrames are not serializable by Pydantic.

---

### Step 1.3: Pydantic schemas — common types

**File: `server/schemas/common.py`**

Implement exactly these models:
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

class PlotResult(BaseModel):
    plotly_json: str  # JSON string of Plotly figure
    png_base64: str | None = None  # optional fallback
    title: str
```

**File: `server/schemas/__init__.py`**
Re-export all schema classes:
```python
from server.schemas.common import Coordinate, SensorInfo, PeriodOfRecord, PlotResult
```

---

### Step 1.4: Core utility — validators

**File: `server/core/validators.py`**

Implement these pure functions (no MCP, no state):
```python
def validate_dataframe_has_columns(df: pd.DataFrame, required: list[str]) -> None:
    """Raise ValueError if any required column is missing from df."""

def validate_positive(value: float, name: str) -> None:
    """Raise ValueError if value <= 0."""

def validate_timestamp_index(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure df has a DatetimeIndex. If 'Timestamp' column exists, set as index. Raise if no datetime found."""

def detect_timestep_minutes(df: pd.DataFrame) -> int:
    """Infer the most common timestep in minutes from a DatetimeIndex."""
```

---

### Step 1.5: Core utility — spatial

**File: `server/core/spatial.py`**

Implement:
```python
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km. Formula: standard haversine with R=6371."""

def bearing_compass(lat1: float, lon1: float, lat2: float, lon2: float) -> str:
    """Return 8-point compass bearing (N, NE, E, ...) from point 1 to point 2."""

def idw_interpolate(points: list[tuple[float, float]], values: np.ndarray, target: tuple[float, float], power: int = 2) -> np.ndarray:
    """Inverse Distance Weighting interpolation. Fallback for degenerate grids."""

def interpolate_spatial(points: list[tuple[float, float]], values: np.ndarray, target: tuple[float, float]) -> tuple[np.ndarray, str]:
    """Try scipy.interpolate.griddata linear, fallback to IDW. Return (values, method_used)."""
```

---

### Step 1.6: FastMCP server entry point

**File: `server/main.py`**

```python
"""GoKaatru MCP Server — entry point.

Registers all tools from server.tools.* modules.
Run: python -m server.main
"""
from __future__ import annotations

from fastmcp import FastMCP

mcp = FastMCP(
    name="GoKaatru",
    version="0.1.0",
    description="Wind Resource Assessment MCP Server — IEC-compliant wind data analysis tools",
)
```

Do NOT import tool modules yet — they will be added in each step as they are created.

Add at the bottom:
```python
if __name__ == "__main__":
    mcp.run()
```

---

### Step 1.7: Data I/O tools

**File: `server/tools/data_io.py`**

Implements 5 tools. Import `from server.main import mcp` and `from server.state.session import session`.

**Tool 1: `parse_timeseries`**
```
@mcp.tool()
def parse_timeseries(file_path: str) -> dict:
```
- Read CSV, TSV, or Excel file using pandas (detect by extension).
- Auto-detect timestamp column: try column names ["Timestamp", "timestamp", "DateTime", "datetime", "Date", "date", "Time", "time"]. Use `pd.to_datetime(col, errors='coerce')` and pick the one with most valid parses.
- Set timestamp as DatetimeIndex, sort by time.
- Store in `session.timeseries_df` AND `session.raw_timeseries_df` (copy).
- Return: `{"status": "ok", "rows": N, "columns": [...], "start": "...", "end": "...", "timestep_minutes": M}`

**Tool 2: `parse_datamodel`**
```
@mcp.tool()
def parse_datamodel(file_path: str) -> dict:
```
- Read a JSON file (IEA Task 43 data model format).
- Walk the JSON tree recursively to find `measurement_point` arrays.
- For each point: extract `name`, `height_m`, `measurement_type_id`.
- Build `session.sensor_mapping`: `{height: {"speed_col": ..., "dir_col": ..., "sd_col": ..., "temp_col": ..., "pressure_col": ...}}`
- If `session.timeseries_df` is loaded, filter to only heights whose speed_col exists in the DataFrame columns.
- Return: `{"status": "ok", "heights": [100, 80, 60, ...], "mapping": {...}}`

**Tool 3: `list_sensors`**
```
@mcp.tool()
def list_sensors() -> dict:
```
- Require `session.timeseries_df` and `session.sensor_mapping` to be loaded.
- For each sensor in the mapping, compute data coverage: `(non-null count / total rows) * 100`.
- Return: `{"sensors": [{"name": "Spd_100m", "height_m": 100, "sensor_type": "wind_speed", "data_coverage_pct": 98.5, "record_count": 52416}, ...]}`

**Tool 4: `get_period_of_record`**
```
@mcp.tool()
def get_period_of_record() -> dict:
```
- Require `session.timeseries_df`.
- Return start, end, total_records, timestep_minutes, plus sensor list from `list_sensors` logic.

**Tool 5: `get_data_coverage`**
```
@mcp.tool()
def get_data_coverage(sensor_name: str) -> dict:
```
- Require `session.timeseries_df`.
- Calculate: total records, valid records, coverage %, largest gap (duration), number of gaps > 1 hour.
- Return flat dict with these stats.

**Update `server/main.py`** — add at bottom (before `if __name__`):
```python
import server.tools.data_io  # noqa: F401
```

---

### Step 1.8: Statistics tools

**File: `server/core/momm.py`**

Implement the Windographer-style MoMM function (this is reused everywhere):
```python
def compute_weighted_momm_table(df: pd.DataFrame, value_col: str) -> pd.DataFrame:
    """
    Build MoMM table per month-hour bin.

    For each (year, month, hour) bin:
      mu_i = mean value
      lambda_i = valid_count / expected_count (completeness)
      psi_i = mean calendar days in month (Feb=28.24)

    Aggregate across years:
      MoMM = sum(mu_i * lambda_i * psi_i) / sum(lambda_i * psi_i)

    Returns: DataFrame with index=month(1-12), columns=hour(0-23).

    Reference: Windographer MoMM methodology, TR6.
    """
```

Use `MEAN_DAYS_IN_MONTH = {1:31, 2:28.24, 3:31, 4:30, 5:31, 6:30, 7:31, 8:31, 9:30, 10:31, 11:30, 12:31}`.

Infer `samples_per_hour` from the most common time delta in the index.

**File: `server/tools/statistics.py`**

Implements 7 tools:

**Tool: `compute_weibull_params`**
```
@mcp.tool()
def compute_weibull_params(sensor_name: str) -> dict:
```
- Get column data from `session.timeseries_df`.
- Filter to positive values. Fit `scipy.stats.weibull_min.fit(data, floc=0)` → (shape_k, loc, scale_A).
- Return: `{"sensor": name, "k": shape_k, "A": scale_A, "mean_speed": mean, "record_count": N}`

**Tool: `compute_windrose_data`**
```
@mcp.tool()
def compute_windrose_data(speed_sensor: str, direction_sensor: str, num_sectors: int = 16) -> dict:
```
- Compute frequency table: for each direction sector, count records and mean speed.
- Return: `{"sectors": [{"center_deg": 0, "label": "N", "frequency_pct": 8.5, "mean_speed": 7.2}, ...]}`

**Tool: `compute_diurnal_profile`**
```
@mcp.tool()
def compute_diurnal_profile(sensor_name: str) -> dict:
```
- Group by hour (0-23), compute mean.
- Return: `{"sensor": name, "hours": [0..23], "mean_speeds": [...]}`

**Tool: `compute_monthly_stats`**
```
@mcp.tool()
def compute_monthly_stats(sensor_name: str) -> dict:
```
- Group by month (1-12), compute mean, min, max, coverage.
- Return: `{"sensor": name, "months": [{"month": 1, "mean": ..., "min": ..., "max": ..., "coverage_pct": ...}, ...]}`

**Tool: `compute_turbulence_intensity`**
```
@mcp.tool()
def compute_turbulence_intensity(speed_sensor: str, sd_sensor: str) -> dict:
```
- TI = sd / speed for each record. Bin by 1 m/s speed bins. Compute mean TI, representative TI (mean + 1.28σ).
- Reference: IEC 61400-1 Ed.4 §6.3.
- Return: `{"bins": [{"bin_center": 4.5, "mean_ti": 0.12, "representative_ti": 0.15, "count": 234}, ...]}`

**Tool: `compute_momm`**
```
@mcp.tool()
def compute_momm(sensor_name: str) -> dict:
```
- Use `core.momm.compute_weighted_momm_table`.
- Compute overall MoMM = weighted mean of 12×24 table (weight by psi_m for each month).
- Return: `{"sensor": name, "momm_speed": float, "table": [[...], ...]}` (12×24 nested list)

**Tool: `compute_scatter_stats`**
```
@mcp.tool()
def compute_scatter_stats(sensor_a: str, sensor_b: str) -> dict:
```
- Inner join on index, drop NaN.
- Compute: R², RMSE, MAE, MBE, OLS slope, OLS intercept, count.
- Return flat dict with all metrics.

**Update `server/main.py`** — add:
```python
import server.tools.statistics  # noqa: F401
```

---

### Step 1.9: Configuration tools

**File: `server/tools/config.py`**

Implements 5 tools:

**Tool: `get_run_config`** → Return `session.runconfig` dict.

**Tool: `update_run_config`**
```
@mcp.tool()
def update_run_config(key: str, value: str) -> dict:
```
- `key` is a dot-separated path like `"location.latitude"` or `"hub_height_m"`.
- Parse value as JSON if possible, else keep as string.
- Set in `session.runconfig` (create nested dicts as needed).
- Return updated config.

**Tool: `save_run_config`** → Write `session.runconfig` to `data/runconfig.json`.

**Tool: `load_run_config`** → Read `data/runconfig.json` into `session.runconfig`.

**Tool: `get_analysis_summary`** → Return dict listing which steps have been completed (based on what's populated in session).

**Update `server/main.py`** — add:
```python
import server.tools.config  # noqa: F401
```

---

### Step 1.10: Tests for Phase 1

**File: `tests/conftest.py`**
```python
import pytest
import pandas as pd
import numpy as np
from server.state.session import session

@pytest.fixture(autouse=True)
def reset_session():
    """Reset session state before each test."""
    session.reset()
    yield
    session.reset()

@pytest.fixture
def sample_timeseries_df():
    """Create a synthetic 1-year, 10-min timeseries with 3 heights."""
    np.random.seed(42)
    idx = pd.date_range("2023-01-01", "2023-12-31 23:50", freq="10min")
    n = len(idx)
    alpha = 0.14  # known shear
    v_100 = np.random.weibull(2.0, n) * 8.0
    v_80 = v_100 * (80 / 100) ** alpha
    v_60 = v_100 * (60 / 100) ** alpha
    dirs = np.random.uniform(0, 360, n)
    return pd.DataFrame({
        "Timestamp": idx,
        "Spd_100m": v_100,
        "Spd_80m": v_80,
        "Spd_60m": v_60,
        "Dir_100m": dirs,
        "Spd_100m_sd": v_100 * 0.1,
    }).set_index("Timestamp")
```

**File: `tests/test_phase1.py`**

Write tests for:
1. `test_session_reset` — verify session resets to None
2. `test_weibull_params` — load sample df into session, call `compute_weibull_params`, check k > 0, A > 0
3. `test_diurnal_profile` — check returns 24 values
4. `test_monthly_stats` — check returns 12 months
5. `test_momm` — check returns float and 12×24 table
6. `test_scatter_stats` — check R² ≈ 1.0 for Spd_100m vs Spd_80m (since they're power-law related)
7. `test_haversine` — known distance check (e.g., Paris to London ≈ 344 km)
8. `test_idw` — 4 equal-distance points should average to mean of values
9. `test_config_update_save_load` — round-trip test

**Run**: `python -m pytest tests/test_phase1.py -v`

---

### Step 1.11: Verify MCP server starts

```bash
python -m server.main --help
```

Should show FastMCP help. Then test with stdio:
```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | python -m server.main
```

Should return JSON listing all registered tools.

---

## PHASE 2 — Shear, Extrapolation & Cleaning

**Goal**: Calculate wind shear profiles, extrapolate to hub height, apply data cleaning rules.

**Prerequisite**: Phase 1 complete and tests passing.

---

### Step 2.1: Core regression functions

**File: `server/core/regression.py`**

Implement:

**`robust_huber_fit(x, y, delta=1.35, max_iter=50, tol=1e-6) -> tuple[float, float, np.ndarray, float]`**
- IRLS using Huber loss. Returns (slope, intercept, y_hat, r_squared).
- MAD-scaled residuals. Weight: `min(1, delta/|z|)`.

**`total_least_squares_fit(x, y) -> tuple[float, float]`**
- SVD on centered data. Returns (slope, intercept).
- Handle edge case: `|ny| < 1e-12`.

**`ols_confidence_intervals(x, y) -> tuple[tuple[float,float]|None, tuple[float,float]|None]`**
- 95% CIs for slope and intercept. z=1.96.
- Return (None, None) if n < 3.

---

### Step 2.2: Core formula functions

**File: `server/core/formulas.py`**

Implement cited IEC formulas as pure functions:

```python
def power_law_extrapolate(v_ref: float, h_ref: float, h_target: float, alpha: float) -> float:
    """V(h_target) = V(h_ref) * (h_target / h_ref)^alpha. IEC 61400-12-1 §B.2."""

def log_law_extrapolate(v_ref: float, h_ref: float, h_target: float, z0: float) -> float:
    """V(h_target) = V(h_ref) * ln(h_target/z0) / ln(h_ref/z0). IEC 61400-12-1 §B.3."""

def shear_from_two_heights(v1: float, h1: float, v2: float, h2: float) -> float:
    """alpha = ln(v2/v1) / ln(h2/h1). Returns NaN if invalid inputs."""

def roughness_from_two_heights(v1: float, h1: float, v2: float, h2: float) -> float:
    """z0 = exp((v2*ln(h1) - v1*ln(h2)) / (v2 - v1)). Returns NaN if invalid."""

def air_density_iec(pressure_pa: float, temperature_k: float, dewpoint_k: float) -> float:
    """IEC 61400-12-1 §A.5. Magnus formula for vapor pressure, moist air density.
    e_s = 6.1078 * 10^(7.5*Td_C / (237.3+Td_C))
    rho = (1/T) * ((P - e*100)/287.05 + (e*100)/461.5)
    """

MEAN_DAYS_IN_MONTH: dict[int, float] = {1:31, 2:28.24, 3:31, 4:30, 5:31, 6:30, 7:31, 8:31, 9:30, 10:31, 11:30, 12:31}
```

---

### Step 2.3: Shear tools

**File: `server/tools/shear.py`**

Implements 6 tools:

**Tool: `calculate_shear_timeseries`**
```
@mcp.tool()
def calculate_shear_timeseries(height_sensors: str) -> dict:
```
- `height_sensors` is JSON string like `'{"100": "Spd_100m", "80": "Spd_80m"}'` (height → column name).
- Parse to `dict[float, str]`.
- For each timestamp, find valid speeds (> 0.1 m/s). If ≥ 2 valid heights, compute α using weighted least squares on all height pairs (weight = |ln(h2/h1)|).
- Store result as `session.shear_timeseries_df` (add this field to SessionState).
- Return: `{"status": "ok", "records": N, "mean_shear": float, "median_shear": float, "std_shear": float}`

**Tool: `calculate_roughness_timeseries`**
- Same pattern but fitting log law: U vs ln(z) regression. z0 = exp(-intercept/slope).
- Clip z0 to [0.000001, 1.5]. Require slope > 0.1.
- Store in `session.roughness_timeseries_df`.

**Tool: `build_shear_table`**
```
@mcp.tool()
def build_shear_table(aggregation: str = "mean") -> dict:
```
- `aggregation` must be one of: "mean", "median", "momm".
- Build 12×24 lookup table from `session.shear_timeseries_df`.
- If "momm": use `core.momm.compute_weighted_momm_table`.
- Fill NaN cells with overall mean (fallback 0.143).
- Store in `session.shear_table`.
- Return: `{"method": "power_law", "aggregation": "momm", "table": [[...], ...]}` (12×24 nested list)

**Tool: `build_roughness_table`**
- Same but for roughness z0. Operations in log-space (mean of log, then exp).
- Default fallback: 0.0002 (offshore).
- Store in `session.roughness_table`.

**Tool: `build_sector_shear_tables`**
```
@mcp.tool()
def build_sector_shear_tables(direction_sensor: str, num_sectors: int = 12, aggregation: str = "mean") -> dict:
```
- Split data by direction sector, build separate 12×24 shear table per sector.
- Return: `{"sectors": {"0-30": [[...]], "30-60": [[...]], ...}}`

**Tool: `build_aggr_momm_shear_table`**
```
@mcp.tool()
def build_aggr_momm_shear_table(height_sensors: str) -> dict:
```
- Aggregate MoMM approach: compute MoMM of raw wind speeds per height first, then derive α from those aggregated tables.
- Only use timestamps where ALL selected sensors have valid data > 0.1 m/s.

---

### Step 2.4: Extrapolation tools

**File: `server/tools/extrapolation.py`**

Implements 2 tools:

**Tool: `extrapolate_to_hub_height`**
```
@mcp.tool()
def extrapolate_to_hub_height(hub_height_m: float, shear_model: str = "power_law") -> dict:
```
- `shear_model`: "power_law" or "log_law".
- Require: `session.timeseries_df`, `session.sensor_mapping`, and either `session.shear_table` or `session.roughness_table`.
- For each timestamp:
  - If hub height matches a measured height → direct (no extrapolation).
  - If hub height between two measured heights → interpolate (log-linear).
  - Else → extrapolate using closest height + shear/roughness table lookup (month, hour).
- Add hub-height column to `session.timeseries_df` as `f"Spd_{hub_height}m_hub"`.
- Track usage stats (how many timestamps used direct/interpolation/extrapolation).
- Update `session.hub_height_m`.
- Return: `{"status": "ok", "column_name": "Spd_150m_hub", "method_counts": {"direct": 0, "interpolated": 0, "extrapolated": 52416}}`

**Tool: `extrapolate_reanalysis_to_hub`**
```
@mcp.tool()
def extrapolate_reanalysis_to_hub(hub_height_m: float, reference_height_m: float = 100.0) -> dict:
```
- Require: `session.era5_interpolated_df` (or fail with message to run ERA5 tools first), `session.shear_table`.
- Apply power law from reference_height to hub_height using session shear table (monthly-hourly lookup).
- Add column `f"Spd_{hub_height}m_hub"` to the ERA5 dataframe.
- Return status + column name.

---

### Step 2.5: Cleaning tools

**File: `server/tools/cleaning.py`**

Implements 4 tools:

**Tool: `list_cleaning_rules`**
```
@mcp.tool()
def list_cleaning_rules() -> dict:
```
- Return static list of all 7 rules with name, description, and default parameters:
  - `range_check`: params `{"min": 0.0, "max": 50.0}`
  - `icing_filter`: params `{"temp_threshold_c": 2.0}` (requires SD column and temp column)
  - `stuck_sensor`: params `{"consecutive_count": 6}`
  - `tower_shadow`: params `{"exclude_sectors": [170, 190]}` (direction range to exclude)
  - `spike_filter`: params `{"window_size": 6, "sigma_threshold": 4.0}`
  - `timestamp_gap_fill`: params `{}` (inserts NaN rows for missing timestamps)
  - `custom_period_exclude`: params `{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}`

**Tool: `apply_cleaning_rule`**
```
@mcp.tool()
def apply_cleaning_rule(rule_type: str, sensor: str, params: str, start_date: str = "", end_date: str = "") -> dict:
```
- `params` is JSON string of parameters.
- Validate rule_type is one of the 7 known rules.
- Apply the rule to `session.timeseries_df`:
  - `range_check`: set values outside [min, max] to NaN.
  - `icing_filter`: find timestamps where SD column == 0 AND temp < threshold → set speed to NaN.
  - `stuck_sensor`: find N consecutive identical values → set to NaN.
  - `tower_shadow`: find timestamps where direction is in excluded sectors → set speed to NaN.
  - `spike_filter`: rolling mean ± sigma_threshold × rolling std → outliers to NaN.
  - `timestamp_gap_fill`: reindex to regular frequency, new rows have NaN.
  - `custom_period_exclude`: set values in date range to NaN.
- If start_date/end_date provided, only apply within that period.
- Count records affected. Add entry to `session.cleaning_log`.
- Return: `{"status": "ok", "rule": rule_type, "sensor": sensor, "records_affected": N}`

**Tool: `get_cleaning_log`**
```
@mcp.tool()
def get_cleaning_log() -> dict:
```
- Return: `{"entries": [{"rule_type": ..., "sensor": ..., "records_affected": ..., "applied_at": ..., "params": ...}, ...]}`

**Tool: `undo_cleaning_rule`**
```
@mcp.tool()
def undo_cleaning_rule(entry_index: int) -> dict:
```
- Restore `session.timeseries_df` from `session.raw_timeseries_df`.
- Re-apply all cleaning rules EXCEPT the one at `entry_index`.
- Remove entry from `session.cleaning_log`.
- Return: `{"status": "ok", "remaining_rules": N}`

**Update `server/main.py`** — add:
```python
import server.tools.shear  # noqa: F401
import server.tools.extrapolation  # noqa: F401
import server.tools.cleaning  # noqa: F401
```

---

### Step 2.6: Tests for Phase 2

**File: `tests/test_phase2.py`**

1. `test_shear_timeseries_known_alpha` — Use `sample_timeseries_df` (α=0.14). Compute shear timeseries. Mean shear should be ≈ 0.14 ± 0.05.
2. `test_shear_table_shape` — Build table, verify shape (12, 24), all values > 0.
3. `test_extrapolate_to_hub_height` — Extrapolate to 120m. Verify column exists, values > 0, values > Spd_100m on average (since 120 > 100 and shear > 0).
4. `test_cleaning_range_check` — Apply range_check [0, 25]. Verify all remaining values in range.
5. `test_cleaning_undo` — Apply rule, undo, verify data matches raw.
6. `test_huber_regression` — Fit y = 2x + 1 with outliers. Should recover slope ≈ 2.
7. `test_tls_fit` — Fit with noise on both axes. Slope should be closer to true than OLS.
8. `test_power_law_formula` — `power_law_extrapolate(10, 80, 100, 0.14)` ≈ 10 * (100/80)^0.14.
9. `test_air_density` — Standard atmosphere: 101325 Pa, 288.15 K, 275 K → ρ ≈ 1.225 ± 0.01.

---

## PHASE 3 — ERA5 & Long-Term Correction

**Goal**: Fetch ERA5 reanalysis data from EarthDataHub Zarr, run MCP/LTC algorithms, compute air density.

**Prerequisite**: Phase 2 complete and tests passing.

---

### Step 3.1: ERA5 tools

**File: `server/tools/era5.py`**

Implements 4 tools:

**Tool: `find_era5_nodes`**
```
@mcp.tool()
def find_era5_nodes(latitude: float, longitude: float) -> dict:
```
- Open the Zarr store (lazy):
  ```python
  ds = xr.open_dataset(
      "https://data.earthdatahub.destine.eu/era5/reanalysis-era5-single-levels-v0.zarr",
      storage_options={"client_kwargs": {"trust_env": True}},
      chunks={},
      engine="zarr",
  )
  ```
- Read `ds.latitude.values` and `ds.longitude.values`.
- Find the 4 nearest grid points (2 lat × 2 lon surrounding the target).
- ERA5 grid is 0.25° — find floor/ceil for lat and lon.
- Compute Haversine distance + compass bearing from mast to each node.
- Store in `session.era5_nodes`.
- Return: `{"nodes": [{"latitude": 52.25, "longitude": 4.75, "distance_km": 18.3, "bearing": "SW"}, ...], "grid_resolution_deg": 0.25}`

**Tool: `extract_era5_data`**
```
@mcp.tool()
def extract_era5_data(latitude: float, longitude: float, start_date: str = "2000-01-01", end_date: str = "2025-12-31") -> dict:
```
- Open Zarr store.
- Select exact grid point using `ds.sel(latitude=latitude, longitude=longitude, method="nearest")`.
- Slice time: `ds.sel(time=slice(start_date, end_date))`.
- Select variables: `["u100", "v100", "sp", "t2m", "d2m"]`. If others available (ust, blh, sshf), include them.
- `.compute()` to materialize (this triggers the actual data fetch).
- Convert to DataFrame.
- **Cache**: Save as Parquet to `data/era5_cache/ERA5_{lat}_{lon}.parquet`. If file already exists and covers the requested period, load from cache instead.
- Store in `session.era5_data[f"{latitude}_{longitude}"]`.
- Return: `{"status": "ok", "latitude": lat, "longitude": lon, "rows": N, "start": "...", "end": "...", "variables": [...], "cached": bool}`

**Tool: `compute_era5_wind_speed`**
```
@mcp.tool()
def compute_era5_wind_speed(latitude: float, longitude: float) -> dict:
```
- Require ERA5 data loaded for this node.
- `speed = sqrt(u100^2 + v100^2)`
- `direction = (270 - degrees(atan2(v100, u100))) % 360`  (meteorological convention: direction wind is blowing FROM)
- Add columns `Spd_100m` and `Dir_100m` to the stored DataFrame.
- Return: `{"status": "ok", "mean_speed": float, "record_count": N}`

**Tool: `interpolate_era5_to_site`**
```
@mcp.tool()
def interpolate_era5_to_site() -> dict:
```
- Require `session.era5_nodes` and ERA5 data loaded for all 4 nodes.
- For each timestamp, spatially interpolate using `core.spatial.interpolate_spatial`.
- Variables to interpolate: Spd_100m, Dir_100m (vector average for direction), sp, t2m, d2m.
- For direction: decompose to u,v components, interpolate, recombine.
- Store result in `session.era5_interpolated_df`.
- Return: `{"status": "ok", "rows": N, "method": "linear|idw", "variables": [...]}`

---

### Step 3.2: LTC deterministic tools

**File: `server/tools/ltc.py`**

Implements 4 tools. Each follows the same pattern:

```
@mcp.tool()
def run_ltc_<algorithm>(short_col: str, long_col: str) -> dict:
```

**Common logic for all 4**:
1. Load `session.timeseries_df` as short-term (measured). Use `short_col` column.
2. Load `session.era5_interpolated_df` as long-term (reference). Use `long_col` column.
3. Build concurrent dataset: inner join on DatetimeIndex, drop NaN.
4. If short-term is sub-hourly (10-min), resample to hourly first: group by `pd.Grouper(freq="h")`, mean, drop hours with < 50% coverage.
5. Require ≥ 10 concurrent data points.
6. Run algorithm → get `result_df` (with columns Timestamp, ERA5_original, corrected_wind_speed) and `metrics` dict.
7. Save result CSV to `data/ltc_results/ltc_{algorithm}_{timestamp}.csv`.
8. Store in `session.ltc_results[algorithm] = {"df": result_df, "metrics": metrics, "file": path}`.
9. Return: `{"status": "ok", "algorithm": "...", "metrics": {...}, "result_file": "..."}`

**Tool: `run_ltc_linear_least_squares`**
- Use `core.regression.robust_huber_fit(reference, measured)`.
- Apply `corrected = reference * slope + intercept`, clip ≥ 0.
- Metrics: algorithm, slope, intercept, r², RMSE, MAE, MBE, std_residuals, concurrent points, total corrected points.

**Tool: `run_ltc_total_least_squares`**
- Use `core.regression.total_least_squares_fit(reference, measured)`.
- Same correction and metrics pattern.

**Tool: `run_ltc_speedsort`**
- Sort reference ascending. Threshold = min(4.0, 0.5 × mean_reference_speed).
- Above threshold: fit TLS. Below: dog-leg slope = (slope × threshold + intercept) / threshold.
- Apply piecewise. Additional metrics: threshold, dog_leg_slope.

**Tool: `run_ltc_variance_ratio`**
- `corrected = measured_mean + (measured_std / reference_std) * (long_term_reference - reference_mean)`.
- Metrics: measured_mean, reference_mean, measured_std, reference_std, variance_ratio, correlation.

---

### Step 3.3: LTC machine learning tool (XGBoost)

**File: `server/tools/ltc_ml.py`**

Implements 1 tool:

**Tool: `run_ltc_xgboost`**
```
@mcp.tool()
def run_ltc_xgboost(short_col: str, long_col: str, short_dir_col: str = "", long_dir_col: str = "") -> dict:
```

Steps:
1. Build concurrent dataset (same as deterministic tools).
2. Require ≥ 100 concurrent samples.
3. **Feature engineering** on the long-term (reference) data:
   - `ref_ws`: reference wind speed
   - `ref_ws_squared`: speed²
   - `ref_ws_log`: log1p(speed)
   - If direction available: `ref_wd_sin`, `ref_wd_cos`, `ws_x_wd_sin`, `ws_x_wd_cos`
   - Temporal: `hour`, `month`, `day_of_year`
   - Cyclical: `hour_sin`, `hour_cos`, `month_sin`, `month_cos`
   - Met columns if available: temperature, pressure
4. **Train/val split**: first 80% train, last 20% validation (time-ordered, no shuffle).
5. **Train XGBoost** with DMatrix, early stopping on validation set:
   - params: `objective=reg:squarederror, eta=0.05, max_depth=6, subsample=0.8, colsample_bytree=0.8, lambda=1.0, alpha=0.1, min_child_weight=3, gamma=0.1, seed=42`
   - `num_boost_round=2000`, `early_stopping_rounds=50`
6. **Predict** on full long-term reference data (same feature engineering).
7. Clip predictions ≥ 0.
8. **Metrics**: R², RMSE, MAE, MBE on concurrent period. Plus: feature importances (top 10), best iteration, train/val error.
9. Save and store (same pattern as deterministic).
10. Return metrics dict.

---

### Step 3.4: Air density tools

**File: `server/tools/air_density.py`**

Implements 2 tools:

**Tool: `compute_air_density`**
```
@mcp.tool()
def compute_air_density(pressure_pa: float, temperature_k: float, dewpoint_k: float) -> dict:
```
- Use `core.formulas.air_density_iec`.
- Return: `{"pressure_pa": ..., "temperature_k": ..., "dewpoint_k": ..., "air_density_kg_m3": float}`

**Tool: `compute_air_density_timeseries`**
```
@mcp.tool()
def compute_air_density_timeseries(pressure_col: str, temperature_col: str, dewpoint_col: str, source: str = "era5") -> dict:
```
- `source`: "era5" (use `session.era5_interpolated_df`) or "measured" (use `session.timeseries_df`).
- Vectorized: apply IEC formula to each row.
- Add column `air_density_kg_m3` to the source DataFrame.
- Return: `{"status": "ok", "mean_density": float, "min_density": float, "max_density": float, "record_count": N}`

**Update `server/main.py`** — add:
```python
import server.tools.era5  # noqa: F401
import server.tools.ltc  # noqa: F401
import server.tools.ltc_ml  # noqa: F401
import server.tools.air_density  # noqa: F401
```

---

### Step 3.5: Tests for Phase 3

**File: `tests/test_phase3.py`**

1. `test_find_era5_nodes_grid` — Mock xarray dataset with known lat/lon arrays. Verify 4 nodes returned, distances > 0.
2. `test_compute_wind_speed` — u100=5, v100=5 → speed ≈ 7.07, direction ≈ 225°.
3. `test_ltc_linear_known_relationship` — Create measured = 1.1 × reference + 0.5 + noise. Verify recovered slope ≈ 1.1, intercept ≈ 0.5.
4. `test_ltc_speedsort_threshold` — Verify threshold = min(4, 0.5*mean_ref).
5. `test_ltc_variance_ratio_identity` — If measured == reference, corrected should ≈ reference.
6. `test_ltc_xgboost_runs` — Synthetic data, verify output has correct columns and metrics keys. (requires `xgboost` installed)
7. `test_air_density_standard_atmosphere` — 101325 Pa, 288.15 K, 275 K → ρ ≈ 1.225 ± 0.01.
8. `test_ltc_determinism` — Run same algorithm twice with same input → identical output.

For ERA5 tests that need network: use `@pytest.mark.skipif` or mock xarray.

---

## PHASE 4 — Post-Processing, Visualization & Integration

**Goal**: Ensemble, clipping, homogeneity, uncertainty, all visualization tools, map tools. Full end-to-end workflow.

**Prerequisite**: Phase 3 complete and tests passing.

---

### Step 4.1: Ensemble tool

**File: `server/tools/ensemble.py`**

**Tool: `run_ensemble`**
```
@mcp.tool()
def run_ensemble(measured_col: str) -> dict:
```
- Require: `session.ltc_results` has ≥ 2 algorithms completed.
- For each LTC result:
  1. Align timestamps with measured data (inner join on overlap period).
  2. Compute bias = mean(predicted - measured), RMSE.
- Weight: w_i = (1/RMSE_i) / sum(1/RMSE_j).
- Bias-correct each series: x'_i = x_i - bias_i.
- Ensemble: y_hat = sum(w_i * x'_i).
- Store `session.ensemble_df` with columns: Timestamp, Ensemble_Speed, plus individual sources.
- Save CSV to `data/ltc_results/ensemble_{timestamp}.csv`.
- Return: `{"status": "ok", "weights": {"speedsort": 0.35, ...}, "metrics": {"rmse": ..., "r2": ..., "bias": ...}}`

---

### Step 4.2: Clipping analysis tool

**File: `server/tools/clipping.py`**

**Tool: `run_clipping_analysis`**
```
@mcp.tool()
def run_clipping_analysis(speed_col: str, source: str = "ensemble") -> dict:
```
- `source`: "ensemble" (use `session.ensemble_df`) or specific algorithm name.
- Resample to annual means.
- Compute IAV = std/mean of annual means.
- For each candidate start year:
  - n_years = years from start to end
  - historic_unc = IAV / sqrt(n_years)
  - LTA_5yr_ratio = mean(start→end) / mean(last_5_years)
  - deviation_term = |1 - 2*Φ(LTA_ratio, 1, IAV/sqrt(5))|
  - climate_unc = 0.005 + 0.01 * exp(-1 + (1 + ln(0.035/0.01)) * deviation^5)
  - combined = sqrt(historic² + climate²)
- Optimal start year = argmin(combined).
- Return: `{"optimal_start_year": 2003, "min_uncertainty": 0.023, "iav": 0.06, "analysis_data": [...]}`

---

### Step 4.3: Homogeneity tools

**File: `server/tools/homogeneity.py`**

**Tool: `analyze_homogeneity`**
```
@mcp.tool()
def analyze_homogeneity(method: str = "annual") -> dict:
```
- Require: ERA5 data loaded for at least 1 node.
- For each ERA5 node dataset:
  - Find wind speed column, resample to annual (or monthly if method="monthly").
  - Run Pettitt test: U_k = 2*cumsum(ranks) - k*(n+1). K = max|U_k|. p ≈ 2*exp(-6K²/(n³+n²)).
  - Scan backward to find earliest homogeneous start year (p < 0.01 threshold).
- Return: `{"datasets": [{"name": "ERA5_52.25_4.75", "recommended_start_year": 2003, "pettitt_p_value": 0.08, "trend_per_year": -0.01}, ...]}`

**Tool: `apply_homogeneity_cutoff`**
```
@mcp.tool()
def apply_homogeneity_cutoff(cutoff_year: int) -> dict:
```
- Trim `session.era5_interpolated_df` to only include data from cutoff_year onwards.
- Return: `{"status": "ok", "rows_before": N, "rows_after": M, "cutoff_year": cutoff_year}`

---

### Step 4.4: Uncertainty tool

**File: `server/tools/uncertainty.py`**

**Tool: `calculate_uncertainty`**
```
@mcp.tool()
def calculate_uncertainty(
    measurement_uncertainty_pct: float,
    measurement_height_m: float,
    hub_height_m: float,
    shear_method: str,
    mcp_r_squared: float,
    concurrent_hours: float,
    algorithm: str = "speedsort",
    iav_pct: float = 6.0,
    shear_std: float = 0.0,
    is_interpolation: bool = False,
) -> dict:
```
- Implement exactly as in `logic/uncertainty.py` (already verified):
  - u_meas = measurement_uncertainty_pct
  - u_vert: if interpolation → 1.0, else k_shear × |ln(h_hub/h_meas)| × 100
  - u_mcp = u_base/sqrt(min(N_months, 12)) + (1 - r²) × C_algo
  - u_future = iav / sqrt(20)
  - u_total = sqrt(sum of squares)
  - P-factors: P50=1.0, P75=1-0.674×u/100, P90=1-1.282×u/100, P99=1-2.326×u/100
- Return: `{"total_uncertainty_pct": float, "components": {...}, "p_factors": {...}, "inputs": {...}}`

---

### Step 4.5: Visualization tools

**File: `server/tools/visualization.py`**

Every plot tool returns: `{"plotly_json": str, "png_base64": str | None, "title": str}`.

Use Plotly `go.Figure` to build figures programmatically, then:
```python
plotly_json = fig.to_json()
# For PNG fallback:
png_bytes = fig.to_image(format="png", width=900, height=500)
png_base64 = base64.b64encode(png_bytes).decode()
```

If `kaleido` is not installed (needed for `to_image`), set `png_base64 = None`.

Implements 11 tools:

**Tool: `plot_windrose`**
```
@mcp.tool()
def plot_windrose(speed_sensor: str, direction_sensor: str) -> dict:
```
- Use Plotly `go.Barpolar` to create wind rose.
- Bin directions into 16 sectors. Stack speed bins (0-5, 5-10, 10-15, 15-20, 20+).

**Tool: `plot_weibull`**
```
@mcp.tool()
def plot_weibull(sensor_name: str) -> dict:
```
- Histogram of wind speed + fitted Weibull PDF overlay.
- `go.Histogram(histnorm='probability density')` + `go.Scatter` for PDF curve.
- Annotate with k, A, mean in legend.

**Tool: `plot_diurnal`**
```
@mcp.tool()
def plot_diurnal(sensor_names: str) -> dict:
```
- `sensor_names` is comma-separated. Plot each as a line on the same axes.
- X = hour (0-23), Y = mean speed.

**Tool: `plot_scatter`**
```
@mcp.tool()
def plot_scatter(sensor_a: str, sensor_b: str) -> dict:
```
- Scatter plot with OLS regression line. Annotate R², RMSE, slope in title/subtitle.
- Subsample to 10000 points if larger.

**Tool: `plot_timeseries`**
```
@mcp.tool()
def plot_timeseries(sensor_names: str) -> dict:
```
- Comma-separated sensors. Overlay on same time axis.
- Downsample to daily means if > 50000 points (for rendering performance).

**Tool: `plot_data_coverage`**
```
@mcp.tool()
def plot_data_coverage() -> dict:
```
- One horizontal bar per sensor. Color where data exists, gap where NaN.
- Use `go.Heatmap` or `go.Bar` horizontal.

**Tool: `plot_shear_table`**
```
@mcp.tool()
def plot_shear_table(table_type: str = "shear") -> dict:
```
- `table_type`: "shear" or "roughness".
- Plotly `go.Heatmap` with 12 rows (months) × 24 columns (hours).
- Color scale: viridis for shear, earth for roughness.

**Tool: `plot_monthly_means`**
```
@mcp.tool()
def plot_monthly_means(sensor_names: str) -> dict:
```
- Grouped bar chart: X = month (Jan-Dec), each sensor is a group.

**Tool: `plot_ltc_comparison`**
```
@mcp.tool()
def plot_ltc_comparison() -> dict:
```
- Require: ≥ 1 LTC result in session.
- Multi-subplot figure:
  1. Monthly mean comparison (measured vs each corrected)
  2. Scatter: measured vs corrected per algorithm
- Use `make_subplots(rows=2, cols=1)`.

**Tool: `plot_annual_means`**
```
@mcp.tool()
def plot_annual_means() -> dict:
```
- Plot annual mean wind speed for each LTC result and ensemble over the full long-term period.

**Tool: `plot_uncertainty_breakdown`**
```
@mcp.tool()
def plot_uncertainty_breakdown(total_pct: float, measurement_pct: float, vertical_pct: float, mcp_pct: float, future_pct: float) -> dict:
```
- Stacked horizontal bar showing RSS components.

---

### Step 4.6: Map tools

**File: `server/tools/map.py`**

Implements 3 tools. All return GeoJSON.

**Tool: `get_mast_marker`**
```
@mcp.tool()
def get_mast_marker() -> dict:
```
- Require: `session.coordinate`.
- Return GeoJSON Feature:
```json
{
  "type": "Feature",
  "geometry": {"type": "Point", "coordinates": [lon, lat]},
  "properties": {"name": "Measurement Mast", "type": "mast", "marker-color": "#083434"}
}
```

**Tool: `get_era5_node_markers`**
```
@mcp.tool()
def get_era5_node_markers() -> dict:
```
- Require: `session.era5_nodes`.
- Return GeoJSON FeatureCollection with 4 point features. Each has distance_km and bearing in properties.

**Tool: `get_site_overview_map`**
```
@mcp.tool()
def get_site_overview_map() -> dict:
```
- Combine mast + ERA5 nodes into one FeatureCollection.

**Update `server/main.py`** — add all remaining imports:
```python
import server.tools.ensemble  # noqa: F401
import server.tools.clipping  # noqa: F401
import server.tools.homogeneity  # noqa: F401
import server.tools.uncertainty  # noqa: F401
import server.tools.visualization  # noqa: F401
import server.tools.map  # noqa: F401
```

---

### Step 4.7: Tests for Phase 4

**File: `tests/test_phase4.py`**

1. `test_ensemble_weights_sum_to_one` — Create 2 fake LTC results, run ensemble, verify weights sum ≈ 1.0.
2. `test_clipping_returns_optimal_year` — Synthetic annual means with known changepoint. Optimal start year should be after changepoint.
3. `test_pettitt_detects_shift` — Create series with mean shift at known point. Verify p < 0.01.
4. `test_uncertainty_components` — Known inputs → verify total = sqrt(sum of squares).
5. `test_uncertainty_p_factors_ordering` — P50 > P75 > P90 > P99.
6. `test_plot_weibull_returns_plotly_json` — Verify output has `plotly_json` key and it parses as valid JSON.
7. `test_geojson_mast_marker` — Verify returned dict has `type: Feature`, valid coordinates.
8. `test_all_tools_registered` — Load server, call `tools/list`, verify count matches expected.

---

## PHASE 5 — Integration & Deployment

**Goal**: Full end-to-end test, LibreChat configuration, Docker packaging.

**Prerequisite**: Phase 4 complete and tests passing.

---

### Step 5.1: End-to-end integration test

**File: `tests/test_e2e.py`**

Write a single test that executes the full workflow programmatically (no LLM, direct function calls):

```python
def test_full_wra_workflow(sample_timeseries_df, tmp_path):
    """Simulate complete wind resource assessment pipeline."""
    # 1. Save sample data to CSV
    csv_path = tmp_path / "test_data.csv"
    sample_timeseries_df.to_csv(csv_path)

    # 2. Parse timeseries
    result = parse_timeseries(str(csv_path))
    assert result["status"] == "ok"

    # 3. Set site coordinates
    update_run_config("location.latitude", "52.4")
    update_run_config("location.longitude", "4.8")
    update_run_config("hub_height_m", "150")

    # 4. List sensors
    sensors = list_sensors()
    assert len(sensors["sensors"]) >= 3

    # 5. Apply cleaning
    apply_cleaning_rule("range_check", "Spd_100m", '{"min": 0.3, "max": 40.0}')
    log = get_cleaning_log()
    assert len(log["entries"]) == 1

    # 6. Calculate shear
    height_sensors = json.dumps({"100": "Spd_100m", "80": "Spd_80m", "60": "Spd_60m"})
    calculate_shear_timeseries(height_sensors)
    build_shear_table("momm")

    # 7. Extrapolate to hub height
    result = extrapolate_to_hub_height(150.0)
    assert "Spd_150m_hub" in session.timeseries_df.columns

    # 8. (Skip ERA5 in unit test — would need network)

    # 9. Compute statistics
    weibull = compute_weibull_params("Spd_100m")
    assert weibull["k"] > 0

    # 10. Save config
    save_run_config()
    assert os.path.exists("data/runconfig.json")
```

---

### Step 5.2: LibreChat MCP configuration

Create a configuration guide for connecting LibreChat to GoKaatru:

**File: `.env.example`**
```dotenv
# Copy this file to .env for local Docker Compose overrides.
# Replace these example values before using LibreChat outside local-only development.

EARTHDATAHUB_TOKEN=
OPENAI_API_KEY=user_provided

LIBRECHAT_CREDS_KEY=replace_with_64_hex_chars
LIBRECHAT_CREDS_IV=replace_with_32_hex_chars
LIBRECHAT_JWT_SECRET=replace_with_64_hex_chars
LIBRECHAT_JWT_REFRESH_SECRET=replace_with_64_hex_chars
```

**File: `librechat_config.yaml`** (example config snippet)
```yaml
# Add to LibreChat's librechat.yaml under mcpServers.
# Use `http://gokaatru:8080/sse` when LibreChat runs in the same Docker Compose stack.
# Use `http://localhost:8080/sse` when LibreChat runs outside Docker on the host machine.
# The `version` field and `allowedDomains` list are required for current LibreChat builds.
version: "1.3.6"

mcpSettings:
  allowedDomains:
    - http://gokaatru:8080
    - http://localhost:8080

mcpServers:
  gokaatru:
    type: sse
    url: http://gokaatru:8080/sse
    timeout: 120000
```

**File: `docker-compose.yml`**
```yaml
services:
  gokaatru:
    build: .
    ports:
      - "8080:8080"
    environment:
      - EARTHDATAHUB_TOKEN=${EARTHDATAHUB_TOKEN:-}
    volumes:
      - ./data:/app/data

  mongodb:
    image: mongo:7
    ports:
      - "27017:27017"
    volumes:
      - librechat_mongo_data:/data/db
    healthcheck:
      test: ["CMD", "mongosh", "--quiet", "--eval", "db.adminCommand('ping').ok"]
      interval: 10s
      timeout: 5s
      retries: 10

  librechat:
    image: ghcr.io/danny-avila/librechat:latest
    environment:
      - HOST=0.0.0.0
      - PORT=3080
      - MONGO_URI=mongodb://mongodb:27017/LibreChat
      - DOMAIN_CLIENT=http://localhost:3080
      - DOMAIN_SERVER=http://localhost:3080
      - CONFIG_PATH=/app/librechat.yaml
      - CREDS_KEY=${LIBRECHAT_CREDS_KEY:-f34be427ebb29de8d88c107a71546019685ed8b241d8f2ed00c3df97ad2566f0}
      - CREDS_IV=${LIBRECHAT_CREDS_IV:-e2341419ec3dd3d19b13a1a87fafcbfb}
      - JWT_SECRET=${LIBRECHAT_JWT_SECRET:-16f8c0ef4a5d391b26034086c628469d3f9f497f08163ab9b40137092f2909ef}
      - JWT_REFRESH_SECRET=${LIBRECHAT_JWT_REFRESH_SECRET:-eaa5191f2914e30b9387fd84e254e4ba6fc51b4654968a9b0803b456a54b8418}
      - OPENAI_API_KEY=${OPENAI_API_KEY:-user_provided}
      - ALLOW_EMAIL_LOGIN=true
      - ALLOW_REGISTRATION=true
      - ALLOW_SOCIAL_LOGIN=false
      - ALLOW_SOCIAL_REGISTRATION=false
      - NO_INDEX=true
    ports:
      - "3080:3080"
    volumes:
      - ./librechat_config.yaml:/app/librechat.yaml:ro
    depends_on:
      mongodb:
        condition: service_healthy
      gokaatru:
        condition: service_started

volumes:
  librechat_mongo_data:
```

---

### Step 5.3: Dockerfile

**File: `Dockerfile`**
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml .
COPY server/ server/
COPY data/ data/

RUN pip install --no-cache-dir ".[ml]"

EXPOSE 8080
CMD ["python", "-m", "server.main", "--transport", "sse", "--host", "0.0.0.0", "--port", "8080"]
```

---

### Step 5.4: README

**File: `README.md`**

Write a README with:
1. One-paragraph description
2. Quick start (local): `conda activate gokaatru && pip install -e ".[ml,dev]" && python -m server.main`
3. Quick start (Docker): `docker compose up --build`
4. LibreChat setup instructions
5. List of all available tools (grouped by domain)
6. Link to BUILD_SPECIFICATION.md for details

---

### Step 5.5: Final validation checklist

Before declaring the build complete, verify:

- [ ] `ruff check server/ tests/` — zero warnings
- [ ] `python -m pytest tests/ -v` — all tests pass
- [ ] `python -m server.main --help` — CLI help renders without errors
- [ ] `python -c "import asyncio, json; from server.main import mcp; print(json.dumps([tool.name for tool in asyncio.run(mcp.list_tools())], indent=2))"` — lists all registered tools
- [ ] Tool count matches spec: 59 tools total
- [ ] Every tool has a docstring
- [ ] No `Any` types anywhere in `server/`
- [ ] No `**kwargs` anywhere in `server/`
- [ ] All Pydantic models use v2 syntax
- [ ] `data/` directory is gitignored
- [ ] Docker build succeeds: `docker build -t gokaatru .`
- [ ] Docker Compose config renders cleanly: `docker compose config`
- [ ] Docker Compose runtime starts cleanly: `docker compose up -d` then `docker compose ps`

---

## PHASE 6 — Workflow Web App

**Goal**: Build a simple analyst-facing web app over the existing backend. The browser must use a thin HTTP API, while MCP remains available for AI clients, automation, and debugging.

**Prerequisite**: Phase 5 complete and validated.

---

### Phase 6 Architecture Rules

These rules are non-negotiable for the UI phase:

1. The browser does **not** talk to MCP directly. It talks to a small FastAPI app.
2. The FastAPI app does **not** duplicate analytics. It calls the same helper functions used by MCP tools.
3. Session state becomes **workspace-scoped**, not a single global singleton for all browser users.
4. The UI is **route-based and workflow-driven**, not chat-driven.
5. Plotly JSON and GeoJSON remain the canonical visualization payloads.

Target runtime topology:

```text
Browser UI (React/Vite)
        |
        v
FastAPI Web API (/api)
        |
        v
Shared session-aware analytics helpers
        |
        +--> FastMCP wrappers (SSE/stdio)
```

---

### Step 6.1: Python dependencies for the web API

**Update `pyproject.toml`**

Add these runtime dependencies:

```toml
"fastapi>=0.115",
"uvicorn[standard]>=0.30",
"python-multipart>=0.0.9",
"orjson>=3.10",
```

Add these dev dependencies:

```toml
"httpx>=0.28",
```

Reasoning:
- `fastapi` gives a thin typed HTTP layer for the browser.
- `uvicorn` runs the API in development and production.
- `python-multipart` is required for file upload forms.
- `orjson` keeps API responses fast for large tables and plot payloads.
- `httpx` is used by API tests via FastAPI's test client stack.

---

### Step 6.2: Session registry instead of a single global browser workspace

**Create file: `server/state/manager.py`**

Implement:

```python
class SessionManager:
    """Registry for browser workspaces keyed by session_id."""

    def create_session(self) -> SessionState: ...
    def get_session(self, session_id: str) -> SessionState: ...
    def reset_session(self, session_id: str) -> SessionState: ...
    def delete_session(self, session_id: str) -> None: ...
    def list_sessions(self) -> list[dict]: ...
```

Rules:
- Use `uuid4().hex` as the session id.
- Each session gets a directory: `data/sessions/<session_id>/`
- Inside that folder create:
  - `uploads/`
  - `era5_cache/`
  - `ltc_results/`
  - `runconfig.json`
- Keep the existing module-level `session = SessionState()` for MCP compatibility, but treat it as the default MCP session only.

**Update file: `server/state/session.py`**

Add fields:
- `session_id: str | None`
- `workspace_dir: Path | None`
- `created_at: datetime | None`
- `updated_at: datetime | None`

Update methods:
- `reset()` should preserve `session_id` and `workspace_dir` if explicitly requested by the manager
- `get_data_dir()` should return the session-specific directory when `workspace_dir` is set
- `to_runconfig()` must remain backward compatible

The point of this step is to remove the hidden assumption that one Python process has only one user workflow.

---

### Step 6.3: Shared helper pattern for MCP + API reuse

Do **not** copy tool logic into the API layer.

For every tool exposed in the web app, move the actual implementation into an internal helper that accepts a `SessionState` instance explicitly.

Pattern:

```python
def _parse_timeseries(state: SessionState, file_path: str) -> dict:
    ...

@mcp.tool()
def parse_timeseries(file_path: str) -> dict:
    return _parse_timeseries(session, file_path)
```

The FastAPI routes then call `_parse_timeseries(manager.get_session(session_id), file_path)`.

Apply this pattern to the modules needed by the browser workflow first:
- `server/tools/data_io.py`
- `server/tools/config.py`
- `server/tools/cleaning.py`
- `server/tools/shear.py`
- `server/tools/extrapolation.py`
- `server/tools/era5.py`
- `server/tools/ltc.py`
- `server/tools/ensemble.py`
- `server/tools/clipping.py`
- `server/tools/homogeneity.py`
- `server/tools/uncertainty.py`
- `server/tools/visualization.py`
- `server/tools/map.py`

This is the most important Phase 6 constraint. If analytics are duplicated, the UI and MCP server will drift.

---

### Step 6.4: FastAPI scaffold

**Create files:**

```text
server/api/__init__.py
server/api/main.py
server/api/deps.py
server/api/schemas.py
server/api/routes/__init__.py
server/api/routes/health.py
server/api/routes/sessions.py
server/api/routes/uploads.py
server/api/routes/config.py
server/api/routes/analysis.py
server/api/routes/results.py
```

**File: `server/api/main.py`**

Requirements:
- Create `FastAPI(title="GoKaatru Web API", version="0.1.0")`
- Mount all routers under `/api`
- Add CORS for local dev:
  - `http://127.0.0.1:5173`
  - `http://localhost:5173`
- Add a root health endpoint or redirect to `/api/health`

**File: `server/api/deps.py`**

Implement helpers:

```python
def get_session_manager() -> SessionManager: ...
def get_session_state(session_id: str) -> SessionState: ...
```

Use header name:

```text
X-GoKaatru-Session
```

If the header is missing on routes that require a session, return `400` with a clear error.

**File: `server/api/schemas.py`**

Define request/response models for the web layer only. Keep them thin and flat. Include at least:
- `CreateSessionResponse`
- `SessionSummaryResponse`
- `UpdateRunConfigRequest`
- `ApplyCleaningRuleRequest`
- `CalculateShearRequest`
- `BuildTableRequest`
- `ExtrapolateHubRequest`
- `FindEra5NodesRequest`
- `ExtractEra5Request`
- `RunLtcRequest`
- `CalculateUncertaintyRequest`
- `PlotRequest`

Do not put pandas objects in API schemas.

---

### Step 6.5: Web API routes

Implement the routes below. Keep them thin wrappers around the shared helpers.

**File: `server/api/routes/health.py`**

Provide:
- `GET /api/health`

Return:

```json
{"status": "ok", "service": "gokaatru-web-api"}
```

**File: `server/api/routes/sessions.py`**

Provide:
- `POST /api/sessions` → create a new session
- `GET /api/sessions/{session_id}` → summary of workflow state
- `POST /api/sessions/{session_id}/reset` → clear workflow data but keep session id
- `DELETE /api/sessions/{session_id}` → delete session and workspace directory

Return for create:

```json
{
  "session_id": "...",
  "workspace_dir": "data/sessions/...",
  "created_at": "...",
  "completed_steps": []
}
```

**File: `server/api/routes/uploads.py`**

Provide:
- `POST /api/sessions/{session_id}/uploads/timeseries`
- `POST /api/sessions/{session_id}/uploads/datamodel`
- `GET /api/sessions/{session_id}/sensors`
- `GET /api/sessions/{session_id}/coverage/{sensor_name}`

Rules:
- Save uploaded files into `data/sessions/<id>/uploads/`
- Then call the shared parsing helpers
- Return the same flat payloads as the tool wrappers where possible

**File: `server/api/routes/config.py`**

Provide:
- `GET /api/sessions/{session_id}/config`
- `PUT /api/sessions/{session_id}/config`
- `GET /api/sessions/{session_id}/summary`

`PUT` body should support batched updates:

```json
{
  "updates": [
    {"key": "project_name", "value": "North Ridge"},
    {"key": "location.latitude", "value": 52.4},
    {"key": "location.longitude", "value": 4.8},
    {"key": "hub_height_m", "value": 150}
  ]
}
```

**File: `server/api/routes/analysis.py`**

Provide workflow endpoints for the web app MVP:
- `POST /api/sessions/{session_id}/cleaning/apply`
- `POST /api/sessions/{session_id}/cleaning/undo`
- `GET /api/sessions/{session_id}/cleaning/log`
- `POST /api/sessions/{session_id}/shear/calculate`
- `POST /api/sessions/{session_id}/shear/table`
- `POST /api/sessions/{session_id}/roughness/calculate`
- `POST /api/sessions/{session_id}/roughness/table`
- `POST /api/sessions/{session_id}/extrapolation/hub`
- `POST /api/sessions/{session_id}/era5/nodes`
- `POST /api/sessions/{session_id}/era5/extract`
- `POST /api/sessions/{session_id}/era5/interpolate`
- `POST /api/sessions/{session_id}/ltc/{algorithm}` where algorithm is one of:
  - `linear_least_squares`
  - `total_least_squares`
  - `speedsort`
  - `variance_ratio`
  - `xgboost`
- `POST /api/sessions/{session_id}/ensemble`
- `POST /api/sessions/{session_id}/clipping`
- `POST /api/sessions/{session_id}/homogeneity/analyze`
- `POST /api/sessions/{session_id}/homogeneity/apply`
- `POST /api/sessions/{session_id}/uncertainty`

**File: `server/api/routes/results.py`**

Provide:
- `GET /api/sessions/{session_id}/results/ltc`
- `GET /api/sessions/{session_id}/results/ensemble`
- `POST /api/sessions/{session_id}/plots/{plot_name}`
- `GET /api/sessions/{session_id}/map/site`
- `GET /api/sessions/{session_id}/runconfig/export`

The route `POST /api/sessions/{session_id}/plots/{plot_name}` should support the plot tools already implemented in Phase 4 and return the standard `PlotResult` shape.

---

### Step 6.6: Frontend scaffold

Create a dedicated frontend workspace.

**Create files:**

```text
frontend/package.json
frontend/tsconfig.json
frontend/vite.config.ts
frontend/index.html
frontend/src/main.tsx
frontend/src/App.tsx
frontend/src/router.tsx
frontend/src/styles.css
frontend/src/lib/api.ts
frontend/src/lib/types.ts
frontend/src/lib/queryClient.ts
frontend/src/stores/workspaceStore.ts
```

**Recommended dependencies**

Runtime:
- `react`
- `react-dom`
- `react-router-dom`
- `@tanstack/react-query`
- `zustand`
- `react-hook-form`
- `zod`
- `react-plotly.js`
- `plotly.js-dist-min`
- `react-leaflet`
- `leaflet`
- `clsx`

Dev:
- `typescript`
- `vite`
- `@vitejs/plugin-react`
- `vitest`
- `jsdom`
- `@testing-library/react`

**File: `frontend/vite.config.ts`**

Requirements:
- Proxy `/api` to `http://127.0.0.1:8000`
- Optionally proxy `/sse` to `http://127.0.0.1:8080` for debugging only

Do **not** make the browser depend on MCP transport for core functionality.

**Styling rule**

Keep styling simple:
- Use one CSS variables file in `styles.css`
- Avoid large UI frameworks in Phase 6
- Build a small in-repo component library instead of pulling in a full design system

---

### Step 6.7: Frontend shell and routing

**Create files:**

```text
frontend/src/components/layout/AppShell.tsx
frontend/src/components/layout/StepNav.tsx
frontend/src/components/common/PageHeader.tsx
frontend/src/components/common/MetricCard.tsx
frontend/src/components/common/StatusBadge.tsx
frontend/src/components/common/ErrorBanner.tsx
frontend/src/components/common/EmptyState.tsx
frontend/src/components/common/FileDropzone.tsx
frontend/src/components/common/DataTable.tsx
frontend/src/components/common/PlotlyFigure.tsx
frontend/src/components/common/GeoJsonMap.tsx
frontend/src/components/common/LoadingState.tsx
frontend/src/pages/OverviewPage.tsx
frontend/src/pages/DataPage.tsx
frontend/src/pages/SitePage.tsx
frontend/src/pages/ReanalysisPage.tsx
frontend/src/pages/LtcPage.tsx
frontend/src/pages/ResultsPage.tsx
```

Route tree:

```text
/
  /overview
  /data
  /site
  /reanalysis
  /ltc
  /results
```

Shell requirements:
- Left sidebar with workflow steps and completion state
- Header with project name, session id, reset action, API health state
- Main content panel for forms, charts, and tables
- Right-side inspector for summary cards, warnings, and current runconfig snapshot

Persist `session_id` in local storage using `workspaceStore`.

---

### Step 6.8: Page-by-page UI contract

Do **not** build a generic chat screen. Build workflow pages with explicit actions.

**OverviewPage**
- Show API health
- Show current project summary from `/summary`
- Show completed workflow steps
- Provide buttons to jump to the next missing step

**DataPage**
- Upload timeseries file
- Upload data model file
- Show detected sensors and coverage table
- Provide cleaning rule form and cleaning log table

**SitePage**
- Edit project metadata: project name, measurement type, coordinates, hub height
- Trigger shear and roughness calculations
- Render month-hour heatmaps from shear/roughness tables
- Trigger hub-height extrapolation and show method counts

**ReanalysisPage**
- Find ERA5 nodes from current site coordinates
- Show mast and node markers on a map
- Trigger ERA5 extraction for the selected date range
- Trigger site interpolation and show row counts and variables

**LtcPage**
- Run deterministic LTC algorithms and XGBoost
- Show metrics comparison table
- Run ensemble
- Run clipping analysis and homogeneity analysis
- Run uncertainty calculation from an explicit form

**ResultsPage**
- Render Plotly figures from plot endpoints
- Render the site overview map
- Show annual means, LTC comparison, and uncertainty outputs
- Show raw runconfig export and generated result file paths

Each page should have:
- one primary action area
- one metrics summary row
- one results region
- one visible error banner when the latest request fails

---

### Step 6.9: Frontend data flow rules

Use state libraries deliberately:

**TanStack Query** for:
- session summary
- sensors and coverage
- cleaning log
- ERA5 node list
- LTC results
- plot payloads

**Zustand** for:
- `sessionId`
- selected sensors
- currently selected LTC source
- active date ranges
- unsaved form drafts

**API client rules**

In `frontend/src/lib/api.ts`:
- Centralize all fetch logic
- Always send `X-GoKaatru-Session`
- Throw typed errors on non-2xx responses
- Keep one helper per route group: `sessionsApi`, `uploadsApi`, `configApi`, `analysisApi`, `resultsApi`

Do not scatter `fetch()` calls directly inside page components.

---

### Step 6.10: API and UI tests

**Create files:**

```text
tests/test_api_sessions.py
tests/test_api_workflow.py
frontend/src/components/layout/AppShell.test.tsx
frontend/src/pages/DataPage.test.tsx
```

**`tests/test_api_sessions.py`**

Cover:
1. create session
2. get session summary
3. reset session
4. delete session
5. missing session header returns 400 where required

**`tests/test_api_workflow.py`**

Using `sample_timeseries_df`, cover this browser-oriented flow:
1. create session
2. upload timeseries
3. upload datamodel or seed sensor mapping
4. update runconfig with location and hub height
5. calculate shear
6. build shear table
7. extrapolate to hub height
8. run at least one LTC algorithm on seeded or mocked reference data
9. request one plot endpoint and validate `plotly_json`

**Frontend tests**

Minimal but useful:
- `AppShell` renders step navigation and outlet region
- `DataPage` shows uploader and reacts to a mocked sensor response

---

### Step 6.11: Local development commands

Backend API:

```bash
python -m uvicorn server.api.main:app --reload --port 8000
```

MCP server for debug/AI clients:

```bash
python -m server.main --transport sse --host 0.0.0.0 --port 8080
```

Frontend:

```bash
npm --prefix frontend install
npm --prefix frontend run dev
npm --prefix frontend run test -- --run
```

Production frontend build:

```bash
npm --prefix frontend run build
```

---

### Step 6.12: Phase 6 validation checklist

Before declaring Phase 6 complete, verify:

- [ ] `python -m pytest tests/test_api_sessions.py tests/test_api_workflow.py -v` passes
- [ ] `python -m uvicorn server.api.main:app --host 127.0.0.1 --port 8000` starts cleanly
- [ ] `python -m server.main --transport sse --host 0.0.0.0 --port 8080` still starts cleanly
- [ ] `npm --prefix frontend run build` passes
- [ ] `npm --prefix frontend run test -- --run` passes
- [ ] Browser workflow works for: upload → shear → extrapolation → result plot
- [ ] Frontend never calls MCP directly for core workflow actions
- [ ] No duplicated analytics logic between `server/api/` and `server/tools/`

---

## Summary: File Creation Order

| Phase | Files | Tool Count |
|-------|-------|------------|
| 1 | pyproject.toml, .gitignore, server/main.py, server/state/session.py, server/schemas/common.py, server/core/validators.py, server/core/spatial.py, server/core/momm.py, server/tools/data_io.py, server/tools/statistics.py, server/tools/config.py, tests/conftest.py, tests/test_phase1.py | 17 tools |
| 2 | server/core/regression.py, server/core/formulas.py, server/tools/shear.py, server/tools/extrapolation.py, server/tools/cleaning.py, tests/test_phase2.py | 12 tools |
| 3 | server/tools/era5.py, server/tools/ltc.py, server/tools/ltc_ml.py, server/tools/air_density.py, tests/test_phase3.py | 11 tools |
| 4 | server/tools/ensemble.py, server/tools/clipping.py, server/tools/homogeneity.py, server/tools/uncertainty.py, server/tools/visualization.py, server/tools/map.py, tests/test_phase4.py | 19 tools |
| 5 | tests/test_e2e.py, Dockerfile, docker-compose.yml, .env.example, librechat_config.yaml, README.md | — |
| 6 | server/api/*, server/state/manager.py, frontend/*, tests/test_api_sessions.py, tests/test_api_workflow.py | — |
| **Current built total through Phase 6** | **37 files** | **59 tools** |

---

## PHASE 7 — Data Explorer & Inline Visualization

**Goal**: Transform the Data and Site pages from form-only admin panels into interactive data exploration workspaces. A wind specialist uploads data and instantly *sees* it — time-series charts, coverage heatmaps, before/after cleaning overlays. Every chart is interactive Plotly with zoom, pan, hover, and data selection.

**Prerequisite**: Phase 6 complete and all existing tests passing.

---

### Phase 7 Design Principles

1. **Charts live where decisions are made.** Do not banish visualization to the Results page. Every page that takes analytical action must show the output inline.
2. **Backend returns Plotly JSON; frontend renders it.** Reuse `PlotlyFigure` and the existing `_plot_result()` pipeline. New backend helpers follow the same `_plot_*()` / `_plot_result()` convention.
3. **No new UI frameworks.** Extend the existing CSS design system (`.content-card`, `.metric-grid`, `.plot-card`, `.panel-grid` classes).
4. **Responsive drill-down.** Every table row should be clickable to show the underlying data in a chart or detail panel.

---

### Step 7.1: New backend endpoints — Data page visualizations

**Update file: `server/tools/visualization.py`**

Add 3 new helpers:

**Helper: `_plot_timeseries_preview`**
```python
def _plot_timeseries_preview(state: SessionState, max_sensors: int = 5) -> dict:
    """Plot the first 7 days of all speed sensors for at-a-glance data quality review after upload.

    Auto-selects the top `max_sensors` wind_speed columns by height (tallest first).
    Uses 10-min native resolution for the preview window.
    Shows NaN gaps as interrupted lines.
    """
```
- Select first 7 days from `state.timeseries_df`.
- Filter to columns matching the speed sensors in `state.sensor_mapping` (sorted by height descending), limit to `max_sensors`.
- Plot each as `go.Scattergl` (WebGL for performance) with `connectgaps=False`.
- Add range slider to x-axis: `fig.update_xaxes(rangeslider_visible=True)`.
- Return via `_plot_result(fig, "Data Preview — First 7 Days")`.

**Helper: `_plot_cleaning_overlay`**
```python
def _plot_cleaning_overlay(state: SessionState, sensor_name: str) -> dict:
    """Overlay raw vs cleaned timeseries for a single sensor, highlighting removed data points.

    Shows:
    - Blue line: current (cleaned) data
    - Red semi-transparent markers: data points removed by cleaning rules
    Uses daily means if > 50000 rows for rendering performance.
    """
```
- Compare `state.raw_timeseries_df[sensor_name]` vs `state.timeseries_df[sensor_name]`.
- Compute `removed = raw.notna() & cleaned.isna()`.
- Plot cleaned as `go.Scattergl(mode='lines')` and removed as `go.Scattergl(mode='markers', marker_color='red', opacity=0.4)`.
- Downsample both to daily means if len > 50000.
- Return via `_plot_result(fig, f"Cleaning Overlay — {sensor_name}")`.

**Helper: `_plot_coverage_timeline`**
```python
def _plot_coverage_timeline(state: SessionState) -> dict:
    """Plot per-sensor data availability as a horizontal timeline with gap shading.

    Each sensor is a row. Valid periods are solid bars, gaps are transparent.
    Color-coded by sensor type: wind_speed=teal, wind_direction=amber, temperature=slate.
    """
```
- For each sensor column, compute monthly availability (count non-null / expected).
- Use `go.Heatmap` with x=months, y=sensor names, z=availability fraction.
- Color scale: `[[0, '#f3efe6'], [0.5, '#e5dbc5'], [1, '#0b7a6f']]`.
- Return via `_plot_result(fig, "Data Coverage Timeline")`.

**Update file: `server/api/routes/results.py`**

Add to `plot_dispatch` dict in the `get_plot` route handler:

```python
"timeseries_preview": lambda: _plot_timeseries_preview(state),
"cleaning_overlay": lambda: _plot_cleaning_overlay(state, body.sensor_name),
"coverage_timeline": lambda: _plot_coverage_timeline(state),
```

Import the 3 new helpers from `server.tools.visualization`.

---

### Step 7.2: New backend endpoints — Turbulence intensity

**Update file: `server/tools/visualization.py`**

**Helper: `_plot_turbulence_intensity`**
```python
def _plot_turbulence_intensity(state: SessionState, speed_sensor: str, sd_sensor: str) -> dict:
    """Plot IEC 61400-1 turbulence intensity profile with characteristic TI and reference curves.

    X-axis: wind speed bins (1 m/s width)
    Y-axis: TI value
    Shows:
    - Scatter of individual TI values (downsampled, semi-transparent)
    - Mean TI per bin (solid line)
    - Representative TI = mean + 1.28σ per bin (dashed line, IEC 61400-1 Ed.4 §6.3)
    - IEC Class A, B, C reference curves as horizontal dashed lines
    """
```
- Compute TI = sd / speed for each 10-min record where speed > 3.0.
- Bin by 1 m/s (centers: 3.5, 4.5, ..., up to max speed).
- For each bin: mean TI, std TI, representative TI = mean + 1.28 × std.
- Plot scatter of raw TI values (max 8000 points, `go.Scattergl`), mean line, representative line.
- Add horizontal dashed references: IEC Class A (Iref=0.16), B (0.14), C (0.12).
- Return via `_plot_result(fig, f"Turbulence Intensity — {speed_sensor}")`.

Add to `plot_dispatch`:
```python
"turbulence_intensity": lambda: _plot_turbulence_intensity(state, body.speed_sensor or body.sensor_name, body.sensor_b),
```

---

### Step 7.3: New backend endpoint — Sector-wise statistics

**Update file: `server/api/routes/analysis.py`**

Add new route:
```python
@router.get("/statistics/{sensor_name}")
def get_sensor_statistics(
    session_id: str,
    sensor_name: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
```
- Return comprehensive stats for one sensor:
  - `mean`, `median`, `std`, `min`, `max`, `count`, `coverage_pct`
  - `weibull_k`, `weibull_A`
  - `monthly_means`: list of 12 floats
  - `diurnal_means`: list of 24 floats
  - `percentiles`: {p10, p25, p50, p75, p90, p99}
- Calls existing statistics helpers from `server/tools/statistics.py`.

**Update file: `server/api/schemas.py`**

Add:
```python
class SensorStatisticsResponse(BaseModel):
    sensor_name: str
    mean: float
    median: float
    std: float
    min_value: float
    max_value: float
    count: int
    coverage_pct: float
    weibull_k: float
    weibull_A: float
    monthly_means: list[float]
    diurnal_means: list[float]
    percentiles: dict[str, float]
```

---

### Step 7.4: DataPage redesign — Inline charts after upload

**Update file: `frontend/src/pages/DataPage.tsx`**

Restructure the page layout into 3 vertical sections:

**Section 1: Upload + Metrics (existing, keep as-is)**
Keep the existing `FileDropzone`, `MetricCard` grid, and `ErrorBanner`.

**Section 2: Data Preview (new)**
After successful upload, add a new section below the metrics:

```tsx
{sensorsQuery.data?.length ? (
  <div className="panel-grid panel-grid-two">
    <PlotlyFigure
      plot={previewPlotQuery.data}
      emptyTitle="Upload data to preview"
      emptyDetail="The first 7 days of wind speed sensors will appear here."
    />
    <PlotlyFigure
      plot={coveragePlotQuery.data}
      emptyTitle="Coverage unavailable"
      emptyDetail="Upload both timeseries and datamodel to see the availability timeline."
    />
  </div>
) : null}
```

Add React Query hooks:
```tsx
const previewPlotQuery = useQuery({
  queryKey: ["timeseries-preview", sessionId],
  queryFn: () => resultsApi.getPlot(sessionId ?? "", "timeseries_preview", {}),
  enabled: sessionId !== null && (sensorsQuery.data?.length ?? 0) > 0,
  staleTime: 15_000,
});

const coveragePlotQuery = useQuery({
  queryKey: ["coverage-timeline", sessionId],
  queryFn: () => resultsApi.getPlot(sessionId ?? "", "coverage_timeline", {}),
  enabled: sessionId !== null && (sensorsQuery.data?.length ?? 0) > 0,
  staleTime: 15_000,
});
```

Add import for `PlotlyFigure` from `../components/common/PlotlyFigure` and `resultsApi` from `../lib/api`.

**Section 3: Cleaning + Coverage (existing, restructure)**

After applying a cleaning rule, replace the static cleaning log table with:
```tsx
<div className="panel-grid panel-grid-two">
  <article className="content-card stack-gap">
    {/* existing cleaning rule form — but redesigned per Step 7.5 */}
  </article>
  <PlotlyFigure
    plot={cleaningOverlayQuery.data}
    emptyTitle="Apply a cleaning rule to compare"
    emptyDetail="The overlay shows raw vs cleaned data for the selected sensor."
  />
</div>
```

Add:
```tsx
const cleaningOverlayQuery = useQuery({
  queryKey: ["cleaning-overlay", sessionId, sensorName, cleaningLogQuery.data?.entries.length],
  queryFn: () => resultsApi.getPlot(sessionId ?? "", "cleaning_overlay", { sensor_name: sensorName }),
  enabled: sessionId !== null && (cleaningLogQuery.data?.entries.length ?? 0) > 0 && sensorName !== "",
  staleTime: 10_000,
});
```

**Section 4: Sensor detail panel (new)**

Add a clickable coverage table — clicking a row shows per-sensor stats in a slide-out:
```tsx
const [selectedSensor, setSelectedSensor] = useState<string | null>(null);

const sensorStatsQuery = useQuery({
  queryKey: ["sensor-stats", sessionId, selectedSensor],
  queryFn: () => analysisApi.getSensorStatistics(sessionId ?? "", selectedSensor ?? ""),
  enabled: sessionId !== null && selectedSensor !== null,
  staleTime: 15_000,
});
```

When `selectedSensor` is set, render a detail card below the table:
```tsx
{selectedSensor && sensorStatsQuery.data ? (
  <article className="content-card stack-gap sensor-detail-card">
    <span className="eyebrow">Sensor detail — {selectedSensor}</span>
    <div className="metric-grid">
      <MetricCard label="Mean" value={sensorStatsQuery.data.mean.toFixed(2)} />
      <MetricCard label="Weibull k" value={sensorStatsQuery.data.weibull_k.toFixed(2)} />
      <MetricCard label="Weibull A" value={sensorStatsQuery.data.weibull_A.toFixed(2)} />
      <MetricCard label="Coverage" value={`${sensorStatsQuery.data.coverage_pct.toFixed(1)}%`} tone="accent" />
    </div>
  </article>
) : null}
```

---

### Step 7.5: Cleaning rule form redesign — No more raw JSON

**Update file: `frontend/src/pages/DataPage.tsx`**

Replace the single `<textarea>` for `paramsText` with rule-specific field groups. Remove the `cleaningRuleHelp` object.

Implement a `CleaningRuleParams` component (inline or extract to `frontend/src/components/common/CleaningRuleParams.tsx`):

```tsx
type CleaningRuleParamsProps = {
  ruleType: string;
  params: Record<string, JsonValue>;
  onParamsChange: (params: Record<string, JsonValue>) => void;
  sensors: SensorRecord[];
};

function CleaningRuleParams({ ruleType, params, onParamsChange, sensors }: CleaningRuleParamsProps) {
  switch (ruleType) {
    case "range_check":
      return (
        <div className="form-grid two-col">
          <label className="form-field">
            <span>Minimum (m/s)</span>
            <input type="number" step="0.1" value={params.min ?? 0} onChange={...} />
          </label>
          <label className="form-field">
            <span>Maximum (m/s)</span>
            <input type="number" step="0.1" value={params.max ?? 50} onChange={...} />
          </label>
        </div>
      );
    case "icing_filter":
      return (
        <label className="form-field">
          <span>Temperature threshold (°C)</span>
          <input type="number" step="0.5" value={params.temp_threshold_c ?? 2} onChange={...} />
          <small className="field-help">Records with SD=0 AND temperature below this threshold will be flagged as icing.</small>
        </label>
      );
    case "stuck_sensor":
      return (
        <label className="form-field">
          <span>Consecutive identical readings</span>
          <input type="number" min="2" step="1" value={params.consecutive_count ?? 6} onChange={...} />
        </label>
      );
    case "tower_shadow":
      return (
        <div className="form-grid two-col">
          <label className="form-field">
            <span>Exclude from (°)</span>
            <input type="number" min="0" max="360" value={(params.exclude_sectors as number[])?.[0] ?? 170} onChange={...} />
          </label>
          <label className="form-field">
            <span>Exclude to (°)</span>
            <input type="number" min="0" max="360" value={(params.exclude_sectors as number[])?.[1] ?? 190} onChange={...} />
          </label>
          <small className="field-help full-width">Wind direction sector to exclude due to mast wake (boom orientation ± shadow angle).</small>
        </div>
      );
    case "spike_filter":
      return (
        <div className="form-grid two-col">
          <label className="form-field">
            <span>Window size (records)</span>
            <input type="number" min="2" value={params.window_size ?? 6} onChange={...} />
          </label>
          <label className="form-field">
            <span>Sigma threshold</span>
            <input type="number" step="0.5" value={params.sigma_threshold ?? 4} onChange={...} />
          </label>
        </div>
      );
    case "timestamp_gap_fill":
      return <p className="muted-text">No parameters required. Missing timestamps will be filled with NaN rows.</p>;
    case "custom_period_exclude":
      return <p className="muted-text">Use the Start date and End date fields above to define the exclusion period.</p>;
  }
}
```

Replace the params `<textarea>` with:
```tsx
<CleaningRuleParams
  ruleType={ruleType}
  params={cleaningParams}
  onParamsChange={setCleaningParams}
  sensors={sensorsQuery.data ?? []}
/>
```

Store `cleaningParams` as `Record<string, JsonValue>` in state instead of a text string. Convert to JSON only when calling the API:
```tsx
const applyCleaningMutation = useMutation({
  mutationFn: () =>
    analysisApi.applyCleaning(sessionId ?? "", {
      rule_type: ruleType,
      sensor: sensorName,
      params: cleaningParams,
      start_date: startDate,
      end_date: endDate,
    }),
  // ... onSuccess: also invalidate ["cleaning-overlay", sessionId, ...] and ["timeseries-preview", sessionId]
});
```

---

### Step 7.6: SitePage inline charts

**Update file: `frontend/src/pages/SitePage.tsx`**

The Site page already shows shear/roughness heatmaps via `PlotlyFigure` — this is good. Add:

**1. Extrapolation result chart (new)**

After `extrapolate_to_hub_height` succeeds, show a comparison of measured heights and the extrapolated hub-height column:

Add a new query:
```tsx
const extrapolationPlotQuery = useQuery({
  queryKey: ["extrapolation-preview", sessionId],
  queryFn: () => {
    const hubHeight = Number(hubHeight);
    const sensorList = selectedSensors.concat([`Spd_${hubHeight}m_hub`]).join(",");
    return resultsApi.getPlot(sessionId ?? "", "timeseries", { sensor_names: sensorList });
  },
  enabled: sessionId !== null && latestExtrapolation !== null,
  staleTime: 15_000,
});
```

Add below the existing shear/roughness heatmaps:
```tsx
{latestExtrapolation ? (
  <article className="content-card stack-gap">
    <span className="eyebrow">Hub-height extrapolation result</span>
    <div className="metric-grid">
      <MetricCard label="Column" value={latestExtrapolation.column_name} />
      <MetricCard label="Extrapolated" value={String(latestExtrapolation.method_counts.extrapolated)} />
      <MetricCard label="Interpolated" value={String(latestExtrapolation.method_counts.interpolated)} />
      <MetricCard label="Direct" value={String(latestExtrapolation.method_counts.direct)} />
    </div>
    <PlotlyFigure plot={extrapolationPlotQuery.data} emptyTitle="Loading" emptyDetail="" />
  </article>
) : null}
```

**2. Shear profile plot (new backend helper)**

**Update file: `server/tools/visualization.py`**

Add helper:
```python
def _plot_shear_profile(state: SessionState) -> dict:
    """Plot the average wind speed profile across measurement heights.

    X-axis: mean wind speed (m/s)
    Y-axis: height (m)
    Shows measured mean speeds at each height as markers, connected by a fitted power-law curve.
    Annotates with the fitted shear exponent α.
    """
```
- For each height in `state.sensor_mapping`, compute mean speed.
- Fit power law: log-linear regression on ln(speed) vs ln(height).
- Plot measured points as markers, fitted curve as a smooth line from min to max height.
- Annotate: `α = {fitted_shear:.3f}`.

Add to `plot_dispatch`:
```python
"shear_profile": lambda: _plot_shear_profile(state),
```

Render on the Site page alongside the heatmaps:
```tsx
const shearProfileQuery = useQuery({
  queryKey: ["shear-profile", sessionId],
  queryFn: () => resultsApi.getPlot(sessionId ?? "", "shear_profile", {}),
  enabled: sessionId !== null && summaryQuery.data?.shear_table_ready === true,
  staleTime: 15_000,
});
```

---

### Step 7.7: Contextual help tooltips

**Create file: `frontend/src/components/common/HelpTooltip.tsx`**

```tsx
type HelpTooltipProps = {
  text: string;
};

export function HelpTooltip({ text }: HelpTooltipProps) {
  return (
    <span className="help-tooltip" title={text}>
      <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
        <circle cx="8" cy="8" r="7" stroke="currentColor" strokeWidth="1.5" fill="none" />
        <text x="8" y="12" textAnchor="middle" fontSize="10" fill="currentColor">?</text>
      </svg>
    </span>
  );
}
```

**Update: `frontend/src/styles.css`**

Add:
```css
.help-tooltip {
  cursor: help;
  color: var(--text-muted);
  margin-left: 6px;
  vertical-align: middle;
}

.help-tooltip:hover {
  color: var(--accent);
}

.field-help {
  display: block;
  margin-top: 4px;
  font-size: 0.78rem;
  color: var(--text-muted);
  line-height: 1.4;
}

.full-width {
  grid-column: 1 / -1;
}
```

Add tooltips to critical form fields across all pages. Key placements:

- **DataPage** cleaning rule dropdown: `"Select a data quality rule. Each rule targets a specific data issue — range violations, sensor icing, stuck values, tower wake, or statistical spikes."`
- **SitePage** shear aggregation: `"MoMM (Mean of Monthly Means) accounts for seasonal and diurnal data gaps. Use 'mean' for well-covered datasets, 'momm' for partial years."`
- **SitePage** hub height: `"The target turbine hub height for extrapolation. Values between measured heights use interpolation; values above use power-law or log-law extrapolation."`
- **LtcPage** algorithm selector: Add help text per algorithm (see Step 9.4 for full text).
- **LtcPage** uncertainty R²: `"R-squared from the MCP concurrent regression. Higher R² reduces the MCP uncertainty component."`

---

### Step 7.8: `analysisApi` extension for sensor statistics

**Update file: `frontend/src/lib/api.ts`**

Add to `analysisApi`:
```typescript
getSensorStatistics: (sessionId: string, sensorName: string) =>
  requestJson<SensorStatisticsResponse>(
    `/sessions/${sessionId}/statistics/${encodeURIComponent(sensorName)}`,
    {},
    sessionId,
  ),
```

**Update file: `frontend/src/lib/types.ts`**

Add:
```typescript
export interface SensorStatisticsResponse {
  sensor_name: string;
  mean: number;
  median: number;
  std: number;
  min_value: number;
  max_value: number;
  count: number;
  coverage_pct: number;
  weibull_k: number;
  weibull_A: number;
  monthly_means: number[];
  diurnal_means: number[];
  percentiles: Record<string, number>;
}
```

---

### Step 7.9: Tests for Phase 7

**Update file: `tests/test_phase4.py`** (or create `tests/test_phase7.py`)

1. `test_plot_timeseries_preview_returns_plotly_json` — Load sample data, call `_plot_timeseries_preview`, verify `plotly_json` parses and has ≥1 trace.
2. `test_plot_cleaning_overlay_shows_removed` — Load data, apply range_check, call `_plot_cleaning_overlay`, verify 2 traces (cleaned + removed).
3. `test_plot_coverage_timeline_dimensions` — Verify heatmap has y-axis entries matching sensor count.
4. `test_plot_turbulence_intensity_bins` — Verify output has scatter + mean + representative traces.
5. `test_plot_shear_profile_annotation` — Verify returned figure JSON contains α annotation.
6. `test_sensor_statistics_endpoint` — API test: upload data, GET `/statistics/{sensor}`, verify all fields present.

**Update file: `frontend/src/pages/DataPage.test.tsx`**

1. `test_shows_preview_plots_after_upload` — Mock sensors response, verify `PlotlyFigure` components mount.
2. `test_cleaning_form_shows_typed_inputs` — Select "range_check", verify numeric inputs render (not textarea).
3. `test_sensor_row_click_shows_detail` — Click sensor row, verify stats card appears.

---

### Step 7.10: Phase 7 validation checklist

- [ ] `python -m pytest tests/ -v` — all tests pass including new Phase 7 tests
- [ ] `npm --prefix frontend run build` — passes
- [ ] DataPage: upload CSV → see timeseries preview chart + coverage timeline within 2 seconds
- [ ] DataPage: apply range_check → see red removed-points overlay
- [ ] DataPage: click sensor row → see Weibull k/A, mean, coverage in detail card
- [ ] DataPage: cleaning form shows typed inputs, not JSON textarea
- [ ] SitePage: shear profile plot visible after shear calculation
- [ ] SitePage: hub-height extrapolation shows timeseries overlay
- [ ] All HelpTooltip placements render on hover
- [ ] No new `Any` types in Python code
- [ ] `ruff check server/ --select E,F,I,W` — zero warnings

---

## PHASE 8 — LTC Analysis Workbench

**Goal**: Transform the LTC page from a table-only form into an interactive analysis workbench. Wind specialists must see algorithm comparison charts, scatter diagnostics, residual analysis, and uncertainty tornado charts — all inline, all updating live as they run algorithms.

**Prerequisite**: Phase 7 complete and tests passing.

---

### Phase 8 Design Principles

1. **Run → See → Compare.** Running an LTC algorithm immediately renders its diagnostic chart on the same page. No page navigation needed.
2. **Side-by-side comparison is the default.** The LTC comparison panel shows all completed algorithms overlaid on one chart.
3. **Uncertainty is visual, not numeric.** The tornado chart is the primary uncertainty output, not a definition list.

---

### Step 8.1: New backend helpers — LTC diagnostic plots

**Update file: `server/tools/visualization.py`**

Add 5 new helpers:

**Helper: `_plot_ltc_scatter`**
```python
def _plot_ltc_scatter(state: SessionState, algorithm: str) -> dict:
    """Plot measured vs corrected scatter for a single LTC algorithm with regression line and 1:1 reference.

    Shows:
    - Scatter points (downsampled to 6000 max)
    - OLS regression line with equation
    - 1:1 reference diagonal (dashed gray)
    - Annotated R², RMSE, MBE in subtitle
    """
```
- Load `state.ltc_results[algorithm]["df"]` and the preferred measured column.
- Align on timestamp, downsample if needed.
- Compute R², RMSE, MBE from the overlap period.
- Plot scatter + OLS fit + 1:1 line.
- Return via `_plot_result(fig, f"LTC Scatter — {algorithm}")`.

**Helper: `_plot_ltc_residuals`**
```python
def _plot_ltc_residuals(state: SessionState, algorithm: str) -> dict:
    """Plot residual diagnostics (corrected − measured) for one algorithm.

    Top subplot: Residuals vs predicted (detect heteroscedasticity)
    Bottom subplot: Residual histogram with normal fit overlay
    """
```
- Compute residuals = corrected − measured on concurrent period.
- Top: scatter of residuals vs predicted values with horizontal zero reference.
- Bottom: histogram + fitted normal curve `scipy.stats.norm.fit(residuals)`.
- Return via `_plot_result(fig, f"LTC Residuals — {algorithm}")`.

**Helper: `_plot_ltc_monthly_comparison`**
```python
def _plot_ltc_monthly_comparison(state: SessionState) -> dict:
    """Plot grouped bar chart of monthly long-term corrected means across all algorithms.

    Each algorithm is a bar group. Measured MoMM shown as line overlay.
    X-axis: Jan-Dec. Y-axis: Mean speed (m/s).
    """
```
- For each completed algorithm, compute monthly means of corrected_wind_speed.
- Plot as grouped bars using `go.Bar` per algorithm.
- Overlay measured monthly means as `go.Scatter(mode='lines+markers')`.
- Return via `_plot_result(fig, "Monthly LTC Comparison")`.

**Helper: `_plot_ltc_annual_convergence`**
```python
def _plot_ltc_annual_convergence(state: SessionState) -> dict:
    """Plot cumulative running annual mean convergence for all LTC algorithms and ensemble.

    Shows how the long-term estimate converges as more years of reference data are included.
    X-axis: years included (expanding window from start).
    Y-axis: running mean wind speed (m/s).
    Horizontal dashed line at the final long-term mean.
    """
```
- For each algorithm's corrected timeseries, compute expanding annual mean.
- Plot each as a line. Add ensemble if present.
- Add final mean as horizontal dashed reference.
- Return via `_plot_result(fig, "Annual Convergence")`.

**Helper: `_plot_uncertainty_tornado`**
```python
def _plot_uncertainty_tornado(
    _state: SessionState,
    total_pct: float,
    measurement_pct: float,
    vertical_pct: float,
    mcp_pct: float,
    future_pct: float,
) -> dict:
    """Plot a tornado chart of uncertainty components ranked by magnitude.

    Horizontal bars sorted largest-to-smallest.
    Color: component bars in accent, total bar in warning.
    RSS annotation: 'Total = √(Σ uᵢ²) = X.XX%'.
    """
```
- Create 4 component bars sorted by magnitude (descending).
- Add total bar with different color at the top.
- Annotate RSS formula.
- Return via `_plot_result(fig, "Uncertainty Tornado")`.

**Update `plot_dispatch` in `server/api/routes/results.py`:**

```python
"ltc_scatter": lambda: _plot_ltc_scatter(state, body.algorithm or "linear_least_squares"),
"ltc_residuals": lambda: _plot_ltc_residuals(state, body.algorithm or "linear_least_squares"),
"ltc_monthly": lambda: _plot_ltc_monthly_comparison(state),
"ltc_convergence": lambda: _plot_ltc_annual_convergence(state),
"uncertainty_tornado": lambda: _plot_uncertainty_tornado(
    state, body.total_pct, body.measurement_pct, body.vertical_pct, body.mcp_pct, body.future_pct,
),
```

**Update file: `server/api/schemas.py`**

Extend `PlotRequest`:
```python
class PlotRequest(BaseModel):
    # ... existing fields ...
    algorithm: str = ""
```

**Update file: `frontend/src/lib/types.ts`**

The `PlotResult` type already supports this — no change needed. The `analysisApi.getPlot` call already passes arbitrary body params.

---

### Step 8.2: LtcPage redesign — Analysis workbench layout

**Update file: `frontend/src/pages/LtcPage.tsx`**

Restructure into 5 major sections:

**Section 1: Metrics bar + Algorithm controls (existing, refined)**
Keep the metric cards and the LTC run form. Improvements:
- Change the "Long reference column" `<input>` to a `<select>` dropdown. Populate from ERA5 interpolated columns:

```tsx
const era5ColumnsQuery = useQuery({
  queryKey: ["era5-columns", sessionId],
  queryFn: async () => {
    const ensemble = await resultsApi.getEnsembleResults(sessionId ?? "");
    return ensemble.columns ?? ["Spd_100m", "Dir_100m", "sp", "t2m", "d2m"];
  },
  enabled: sessionId !== null,
  staleTime: 30_000,
});
```

Replace `<input value={longCol}>` with:
```tsx
<select value={longCol} onChange={(event) => setLongCol(event.target.value)}>
  {(era5ColumnsQuery.data ?? ["Spd_100m"]).filter(col => col.startsWith("Spd_")).map((col) => (
    <option key={col} value={col}>{col}</option>
  ))}
</select>
```

Same for `longDirCol` — filter to columns starting with `Dir_`.

**Section 2: Live diagnostic panel (new)**

After running any LTC algorithm, immediately show its diagnostic plots:

```tsx
const latestAlgorithm = ltcResultsQuery.data?.results[ltcResultsQuery.data.results.length - 1]?.algorithm;

const ltcScatterQuery = useQuery({
  queryKey: ["ltc-scatter", sessionId, latestAlgorithm],
  queryFn: () => resultsApi.getPlot(sessionId ?? "", "ltc_scatter", { algorithm: latestAlgorithm }),
  enabled: sessionId !== null && latestAlgorithm !== undefined,
  staleTime: 10_000,
});

const ltcResidualsQuery = useQuery({
  queryKey: ["ltc-residuals", sessionId, latestAlgorithm],
  queryFn: () => resultsApi.getPlot(sessionId ?? "", "ltc_residuals", { algorithm: latestAlgorithm }),
  enabled: sessionId !== null && latestAlgorithm !== undefined,
  staleTime: 10_000,
});
```

Layout:
```tsx
{latestAlgorithm ? (
  <>
    <span className="eyebrow">Latest run — {latestAlgorithm}</span>
    <div className="panel-grid panel-grid-two">
      <PlotlyFigure plot={ltcScatterQuery.data} emptyTitle="Scatter loading" emptyDetail="" />
      <PlotlyFigure plot={ltcResidualsQuery.data} emptyTitle="Residuals loading" emptyDetail="" />
    </div>
  </>
) : null}
```

**Section 3: Comparison panel (new)**

After ≥2 algorithms are run:

```tsx
const ltcMonthlyQuery = useQuery({
  queryKey: ["ltc-monthly", sessionId, ltcResultsQuery.data?.results.length],
  queryFn: () => resultsApi.getPlot(sessionId ?? "", "ltc_monthly", {}),
  enabled: sessionId !== null && (ltcResultsQuery.data?.results.length ?? 0) >= 1,
  staleTime: 10_000,
});

const ltcConvergenceQuery = useQuery({
  queryKey: ["ltc-convergence", sessionId, ltcResultsQuery.data?.results.length],
  queryFn: () => resultsApi.getPlot(sessionId ?? "", "ltc_convergence", {}),
  enabled: sessionId !== null && (ltcResultsQuery.data?.results.length ?? 0) >= 1,
  staleTime: 10_000,
});
```

Layout:
```tsx
<div className="panel-grid panel-grid-two">
  <PlotlyFigure plot={ltcMonthlyQuery.data} emptyTitle="Monthly comparison" emptyDetail="Run at least 1 algorithm." />
  <PlotlyFigure plot={ltcConvergenceQuery.data} emptyTitle="Convergence" emptyDetail="Run at least 1 algorithm." />
</div>
```

**Section 4: LTC Metrics Table (existing, enhanced)**

Keep the existing `DataTable` but add a column with a "View Scatter" button per algorithm:

```tsx
{
  key: "scatter",
  header: "Diagnostics",
  cell: (row) => (
    <button className="ghost-button table-action" type="button" onClick={() => setFocusedAlgorithm(row.algorithm)}>
      View
    </button>
  ),
}
```

When `focusedAlgorithm` is set, the diagnostic panel (Section 2) updates to show that algorithm's scatter and residuals instead of the latest.

**Section 5: Uncertainty tornado (replaces the definition list)**

After running `calculateUncertainty`:

```tsx
const uncertaintyTornadoQuery = useQuery({
  queryKey: ["uncertainty-tornado", sessionId, latestUncertainty?.total_uncertainty_pct],
  queryFn: () => resultsApi.getPlot(sessionId ?? "", "uncertainty_tornado", {
    total_pct: latestUncertainty?.total_uncertainty_pct ?? 0,
    measurement_pct: latestUncertainty?.components.measurement ?? 0,
    vertical_pct: latestUncertainty?.components.vertical_extrapolation ?? 0,
    mcp_pct: latestUncertainty?.components.mcp ?? 0,
    future_pct: latestUncertainty?.components.future_variability ?? 0,
  }),
  enabled: sessionId !== null && latestUncertainty !== null,
  staleTime: 10_000,
});
```

Alongside the uncertainty form, replace the `definition-list` output with:

```tsx
<div className="panel-grid panel-grid-two">
  <article className="content-card stack-gap">
    {/* ... existing uncertainty form fields ... */}
  </article>
  <article className="content-card stack-gap">
    <PlotlyFigure plot={uncertaintyTornadoQuery.data} emptyTitle="Run uncertainty first" emptyDetail="" />
    {latestUncertainty ? (
      <div className="metric-grid">
        <MetricCard label="Total" value={`${latestUncertainty.total_uncertainty_pct.toFixed(2)}%`} tone="accent" />
        <MetricCard label="P75" value={latestUncertainty.p_factors.p75.toFixed(4)} />
        <MetricCard label="P90" value={latestUncertainty.p_factors.p90.toFixed(4)} />
        <MetricCard label="P99" value={latestUncertainty.p_factors.p99.toFixed(4)} />
      </div>
    ) : null}
  </article>
</div>
```

---

### Step 8.3: Uncertainty form UX improvements

In the existing uncertainty form on `LtcPage.tsx`:

1. **Replace `shear_method` text input** with a `<select>`:
```tsx
<select value={uncShearMethod} onChange={(event) => setUncShearMethod(event.target.value)}>
  <option value="simple_power_law">Simple Power Law</option>
  <option value="log_law">Log Law</option>
  <option value="momm_power_law">MoMM Power Law</option>
</select>
```

2. **Auto-populate from session state** where possible:
- `uncMeasurementHeight`: default from the tallest speed sensor height
- `uncHubHeight`: default from `configQuery.data?.hub_height_m`
- `uncRsq`: auto-fill from the latest LTC result's metrics `r_squared` if available
- `uncHours`: auto-fill from concurrent data point count in latest LTC result

Add a `useEffect` that populates these when LTC results change:

```tsx
useEffect(() => {
  const latest = ltcResultsQuery.data?.results[ltcResultsQuery.data.results.length - 1];
  if (latest?.metrics) {
    const r2 = latest.metrics.r_squared ?? latest.metrics.r2;
    if (typeof r2 === "number") setUncRsq(String(r2.toFixed(4)));
    const concurrent = latest.metrics.concurrent_points ?? latest.metrics.n_concurrent;
    if (typeof concurrent === "number") setUncHours(String(concurrent));
  }
}, [ltcResultsQuery.data]);
```

3. **Show which algorithm's metrics are being used** as a hint:
```tsx
<small className="field-help">
  Auto-populated from {latestAlgorithm ?? "latest"} LTC result. Override to customize.
</small>
```

---

### Step 8.4: Algorithm help panel

Add inline help descriptions for each algorithm. Create a constant map:

**Create or update file: `frontend/src/lib/algorithmHelp.ts`**

```typescript
export const algorithmHelp: Record<string, { label: string; description: string; recommended: string }> = {
  linear_least_squares: {
    label: "Linear Least Squares (Robust Huber)",
    description: "Iteratively reweighted least squares using Huber loss. Down-weights outlier residuals while preserving the linear relationship. Preferred when the measurement period contains anomalous readings.",
    recommended: "General purpose. Good when R² > 0.85.",
  },
  total_least_squares: {
    label: "Total Least Squares (Orthogonal)",
    description: "Fits the line minimizing perpendicular distance to all points, accounting for measurement error in both the measured and reference datasets.",
    recommended: "Use when both measured and reference data have comparable noise levels.",
  },
  speedsort: {
    label: "SpeedSort",
    description: "Piecewise linear: TLS fit above a threshold, dog-leg fit below. Industry standard for its stability at low wind speeds where regression bias is highest.",
    recommended: "Industry standard. Recommended for bankable WRA.",
  },
  variance_ratio: {
    label: "Variance Ratio",
    description: "Distribution-matching method. Adjusts the reference data by matching the measured and reference standard deviations. Preserves the measured wind speed distribution shape.",
    recommended: "Use when maintaining distribution shape matters more than point prediction accuracy.",
  },
  xgboost: {
    label: "XGBoost (Machine Learning)",
    description: "Gradient boosted decision trees with temporal and directional features. Captures non-linear patterns and interactions. Uses time-ordered cross-validation to prevent temporal leakage.",
    recommended: "Use as a secondary check or when non-linear patterns exist. Not IEC-standard for standalone use.",
  },
};
```

Show below the algorithm dropdown on the LTC page:
```tsx
<small className="field-help">
  {algorithmHelp[selectedLtcAlgorithm]?.description}
  <br />
  <strong>When to use:</strong> {algorithmHelp[selectedLtcAlgorithm]?.recommended}
</small>
```

---

### Step 8.5: Tests for Phase 8

**Create file: `tests/test_phase8.py`**

1. `test_plot_ltc_scatter_traces` — Run linear_least_squares on synthetic data, call `_plot_ltc_scatter`, verify figure has ≥2 traces (scatter + regression + 1:1 line).
2. `test_plot_ltc_residuals_subplots` — Verify returned figure has 2 subplots.
3. `test_plot_ltc_monthly_bar_count` — Run 2 algorithms, verify monthly chart has bar traces for each.
4. `test_plot_ltc_convergence_lines` — Verify convergence plot has one line per algorithm.
5. `test_plot_uncertainty_tornado_sorted` — Verify bars are sorted by magnitude.
6. `test_plot_dispatch_new_names` — Verify `ltc_scatter`, `ltc_residuals`, `ltc_monthly`, `ltc_convergence`, `uncertainty_tornado` are all valid plot names via the API.

**Update file: `frontend/src/pages/LtcPage.test.tsx`**

1. `test_shows_diagnostic_panel_after_run` — Mock LTC results, verify scatter/residual containers mount.
2. `test_algorithm_help_text_updates` — Change algorithm dropdown, verify help text changes.
3. `test_uncertainty_tornado_renders` — Mock uncertainty result, verify PlotlyFigure mounts.

---

### Step 8.6: Phase 8 validation checklist

- [ ] `python -m pytest tests/ -v` — all tests pass
- [ ] `npm --prefix frontend run build` — passes
- [ ] LtcPage: run linear_least_squares → scatter & residual plots appear inline within 3s
- [ ] LtcPage: run 2 algorithms → monthly comparison & convergence charts appear
- [ ] LtcPage: click "View" on metrics table row → diagnostic panel switches to that algorithm
- [ ] LtcPage: run uncertainty → tornado chart renders sorted by magnitude with RSS annotation
- [ ] LtcPage: algorithm dropdown shows help text per algorithm
- [ ] LtcPage: long_col and long_dir_col are dropdown selects, not free-text inputs
- [ ] LtcPage: uncertainty form auto-fills R² and concurrent hours from latest LTC result
- [ ] No loose `<input>` where a `<select>` would be more appropriate

---

## PHASE 9 — Enhanced Map, Export & Reanalysis Page

**Goal**: Professional-grade map with distance rings and terrain context; data export capabilities (CSV, runconfig JSON); improved Reanalysis page with ERA5 comparison charts.

**Prerequisite**: Phase 8 complete and tests passing.

---

### Step 9.1: Enhanced Leaflet map

**Update file: `frontend/src/components/common/GeoJsonMapRuntime.tsx`**

Enhance the map with:

**1. Distance rings from mast**

After the `FitBounds` component, add a `DistanceRings` component:

```tsx
import { Circle } from "react-leaflet";

function DistanceRings({ center }: { center: [number, number] }) {
  const rings = [10, 25, 50]; // km
  return (
    <>
      {rings.map((radiusKm) => (
        <Circle
          key={radiusKm}
          center={center}
          radius={radiusKm * 1000}
          pathOptions={{
            color: "var(--accent)",
            weight: 1,
            opacity: 0.35,
            dashArray: "6 4",
            fill: false,
          }}
        />
      ))}
    </>
  );
}
```

Detect the mast feature and extract its coordinates:
```tsx
const mastFeature = featureCollection.features.find(
  (f) => f.properties.type === "mast"
);
const mastCenter: [number, number] | null = mastFeature
  ? [mastFeature.geometry.coordinates[1] as number, mastFeature.geometry.coordinates[0] as number]
  : null;
```

Render inside `MapContainer`:
```tsx
{mastCenter ? <DistanceRings center={mastCenter} /> : null}
```

**2. Terrain/topographic tile layer option**

Add a layer toggle using React Leaflet's `LayersControl`:

```tsx
import { LayersControl, TileLayer } from "react-leaflet";

<LayersControl position="topright">
  <LayersControl.BaseLayer checked name="Street">
    <TileLayer
      attribution='...'
      url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
    />
  </LayersControl.BaseLayer>
  <LayersControl.BaseLayer name="Terrain">
    <TileLayer
      attribution='Map data © OpenStreetMap, Tiles © Stamen'
      url="https://tiles.stadiamaps.com/tiles/stamen_terrain/{z}/{x}/{y}.png"
    />
  </LayersControl.BaseLayer>
  <LayersControl.BaseLayer name="Satellite">
    <TileLayer
      attribution='© Esri'
      url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
    />
  </LayersControl.BaseLayer>
</LayersControl>
```

**3. Always-visible labels for ERA5 nodes**

Replace plain popups with `Tooltip` that shows by default:

```tsx
import { Tooltip } from "react-leaflet";

// Inside the GeoJSON onEachFeature callback:
onEachFeature={(feature, layer) => {
  const props = feature.properties as Record<string, unknown>;
  const type = props.type;
  if (type === "era5_node") {
    layer.bindTooltip(
      `${props.distance_km} km ${props.bearing}`,
      { permanent: true, direction: "top", className: "map-node-label" }
    );
  }
  layer.bindPopup(/* existing popup code */);
}}
```

**4. Differentiated markers**

Use different colors for mast vs ERA5 nodes:
```tsx
pointToLayer={(feature, latlng) => {
  const isMast = (feature.properties as Record<string, unknown>).type === "mast";
  return circleMarker(latlng, {
    radius: isMast ? 10 : 6,
    color: isMast ? "#c86a2a" : "#0b7a6f",
    weight: isMast ? 3 : 2,
    fillColor: isMast ? "#fffaf0" : "#f3efe3",
    fillOpacity: 0.95,
  });
}}
```

**Add CSS for map labels:**

**Update: `frontend/src/styles.css`**
```css
.map-node-label {
  font-family: var(--mono);
  font-size: 0.72rem;
  padding: 2px 6px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.1);
}
```

---

### Step 9.2: New backend endpoints — Data export

**Create file: `server/api/routes/exports.py`**

```python
router = APIRouter(prefix="/sessions/{session_id}/exports", tags=["exports"])
```

**Endpoint: `GET /api/sessions/{session_id}/exports/timeseries`**
```python
@router.get("/timeseries")
def export_timeseries_csv(
    session_id: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> Response:
    """Export the current (cleaned) timeseries as a CSV download."""
```
- Convert `state.timeseries_df` to CSV.
- Return as `StreamingResponse` with `Content-Disposition: attachment; filename="timeseries_cleaned.csv"`.
- Use `media_type="text/csv"`.

**Endpoint: `GET /api/sessions/{session_id}/exports/ltc/{algorithm}`**
```python
@router.get("/ltc/{algorithm}")
def export_ltc_csv(
    session_id: str,
    algorithm: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> Response:
    """Export one LTC result as a CSV download."""
```
- Load from `state.ltc_results[algorithm]["df"]`.
- Return as CSV attachment.

**Endpoint: `GET /api/sessions/{session_id}/exports/ensemble`**
```python
@router.get("/ensemble")
def export_ensemble_csv(
    session_id: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> Response:
    """Export ensemble result as a CSV download."""
```

**Endpoint: `GET /api/sessions/{session_id}/exports/runconfig`**
```python
@router.get("/runconfig")
def export_runconfig_json(
    session_id: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> Response:
    """Export the full runconfig JSON as a file attachment download."""
```

**Register the router in `server/api/main.py`:**
```python
from server.api.routes.exports import router as exports_router
app.include_router(exports_router, prefix="/api")
```

---

### Step 9.3: Frontend export buttons

**Update file: `frontend/src/lib/api.ts`**

Add `exportsApi`:
```typescript
export const exportsApi = {
  downloadTimeseries: (sessionId: string) =>
    `${API_BASE}/sessions/${sessionId}/exports/timeseries`,
  downloadLtc: (sessionId: string, algorithm: string) =>
    `${API_BASE}/sessions/${sessionId}/exports/ltc/${algorithm}`,
  downloadEnsemble: (sessionId: string) =>
    `${API_BASE}/sessions/${sessionId}/exports/ensemble`,
  downloadRunconfig: (sessionId: string) =>
    `${API_BASE}/sessions/${sessionId}/exports/runconfig`,
};
```

These return URL strings for direct browser download (no fetch needed — use `<a href>` or `window.open`).

**Update file: `frontend/src/pages/DataPage.tsx`**

Add export button in the metrics bar area:
```tsx
<button
  className="secondary-button"
  type="button"
  disabled={!sensorsQuery.data?.length}
  onClick={() => window.open(exportsApi.downloadTimeseries(sessionId ?? ""), "_blank")}
>
  Export Cleaned CSV
</button>
```

**Update file: `frontend/src/pages/LtcPage.tsx`**

Add export buttons per algorithm in the metrics table:
```tsx
{
  key: "export",
  header: "Export",
  cell: (row) => (
    <button
      className="ghost-button table-action"
      type="button"
      onClick={() => window.open(exportsApi.downloadLtc(sessionId ?? "", row.algorithm), "_blank")}
    >
      CSV
    </button>
  ),
}
```

Add ensemble export button:
```tsx
{ensembleQuery.data?.available ? (
  <button
    className="secondary-button"
    type="button"
    onClick={() => window.open(exportsApi.downloadEnsemble(sessionId ?? ""), "_blank")}
  >
    Export Ensemble CSV
  </button>
) : null}
```

**Update file: `frontend/src/pages/ResultsPage.tsx`**

Add runconfig JSON download alongside the existing "Export Runconfig" button:
```tsx
<button
  className="secondary-button"
  type="button"
  onClick={() => window.open(exportsApi.downloadRunconfig(sessionId ?? ""), "_blank")}
>
  Download Runconfig JSON
</button>
```

---

### Step 9.4: Reanalysis page — ERA5 comparison charts

**Update file: `server/tools/visualization.py`**

Add 2 new helpers:

**Helper: `_plot_era5_comparison`**
```python
def _plot_era5_comparison(state: SessionState) -> dict:
    """Plot monthly mean wind speed for all 4 ERA5 nodes vs the interpolated site estimate.

    X-axis: Jan-Dec
    Y-axis: mean speed (m/s)
    One line per node + one line for interpolated site.
    """
```
- For each node key in `state.era5_data`, compute monthly mean of Spd_100m.
- Plot each as `go.Scatter(mode='lines+markers')`.
- Add interpolated as a thicker line.
- Return via `_plot_result(fig, "ERA5 Annual Profile — Nodes vs Site")`.

**Helper: `_plot_era5_measured_overlay`**
```python
def _plot_era5_measured_overlay(state: SessionState) -> dict:
    """Plot concurrent measured vs ERA5 interpolated monthly means for correlation assessment before LTC.

    X-axis: months (full overlap period)
    Y-axis: mean speed (m/s)
    Two lines: measured hub height, ERA5 at site.
    Annotate concurrent R², data overlap period.
    """
```
- Join measured hub-height column with ERA5 interpolated Spd_100m.
- Resample to monthly means on the overlap period.
- Plot both as lines.
- Compute R² and annotate.
- Return via `_plot_result(fig, "Measured vs ERA5 — Concurrent Period")`.

Add to `plot_dispatch`:
```python
"era5_comparison": lambda: _plot_era5_comparison(state),
"era5_measured_overlay": lambda: _plot_era5_measured_overlay(state),
```

**Update file: `frontend/src/pages/ReanalysisPage.tsx`**

After ERA5 extraction + interpolation completes, add:

```tsx
const era5ComparisonQuery = useQuery({
  queryKey: ["era5-comparison", sessionId],
  queryFn: () => resultsApi.getPlot(sessionId ?? "", "era5_comparison", {}),
  enabled: sessionId !== null && latestInterpolation !== null,
  staleTime: 15_000,
});

const era5OverlayQuery = useQuery({
  queryKey: ["era5-overlay", sessionId],
  queryFn: () => resultsApi.getPlot(sessionId ?? "", "era5_measured_overlay", {}),
  enabled: sessionId !== null && latestInterpolation !== null,
  staleTime: 15_000,
});
```

Layout below the map:
```tsx
{latestInterpolation ? (
  <div className="panel-grid panel-grid-two">
    <PlotlyFigure
      plot={era5ComparisonQuery.data}
      emptyTitle="ERA5 node comparison"
      emptyDetail="Loading node annual profiles."
    />
    <PlotlyFigure
      plot={era5OverlayQuery.data}
      emptyTitle="Measured vs ERA5"
      emptyDetail="Overlay concurrent measured and ERA5 monthly means."
    />
  </div>
) : null}
```

---

### Step 9.5: Tests for Phase 9

**Create file: `tests/test_phase9.py`**

1. `test_export_timeseries_csv_response` — Upload data, GET `/exports/timeseries`, verify response has `text/csv` content type.
2. `test_export_ltc_csv_response` — Run LTC, GET `/exports/ltc/linear_least_squares`, verify CSV headers match expected columns.
3. `test_export_runconfig_json_response` — GET `/exports/runconfig`, verify parseable JSON.
4. `test_plot_era5_comparison_traces` — Load 4 ERA5 nodes, call helper, verify 5 traces (4 nodes + interpolated).
5. `test_plot_era5_measured_overlay` — Verify 2 traces and R² annotation.

**Frontend tests:**

1. `test_export_buttons_have_correct_urls` — Verify export button href contains correct session id and path.
2. `test_map_renders_distance_rings` — Mock GeoJSON with mast feature, verify `Circle` components mount (3 rings at 10/25/50 km).

---

### Step 9.6: Phase 9 validation checklist

- [ ] `python -m pytest tests/ -v` — all tests pass
- [ ] `npm --prefix frontend run build` — passes
- [ ] Map: mast shows orange marker, ERA5 nodes show teal markers with permanent distance labels
- [ ] Map: 3 distance rings visible (10, 25, 50 km dashed circles)
- [ ] Map: layer switcher offers Street/Terrain/Satellite tiles
- [ ] DataPage: "Export Cleaned CSV" downloads a valid CSV file
- [ ] LtcPage: per-algorithm CSV export buttons work
- [ ] LtcPage: ensemble CSV export works
- [ ] ResultsPage: download runconfig JSON works
- [ ] ReanalysisPage: ERA5 comparison and measured overlay charts appear after interpolation
- [ ] All downloads include proper Content-Disposition headers

---

## PHASE 10 — Scenario Management & Results Dashboard

**Goal**: Enable wind specialists to run multiple analysis scenarios (different shear methods, sensor choices, hub heights), compare them side by side, and get a comprehensive results dashboard. This is the capstone phase that transforms GoKaatru from a linear workflow into a true analytical workbench.

**Prerequisite**: Phase 9 complete and tests passing.

---

### Phase 10 Design Principles

1. **Scenarios are named snapshots.** A scenario captures a set of choices (shear method, sensor selection, hub height, LTC algorithm) and the resulting output (long-term mean, uncertainty, P-factors).
2. **Compare without re-running.** Once scenarios are stored, comparison is instant — no recomputation needed.
3. **The Results page becomes a dashboard.** All key outputs visible at a glance: annual means, uncertainty breakdown, P-factors, and a comparison table.

---

### Step 10.1: Backend — Scenario storage

**Update file: `server/state/session.py`**

Add to `SessionState`:
```python
scenarios: list[dict] = field(default_factory=list)
```

Each scenario dict has the shape:
```python
{
    "name": str,               # user-provided label
    "created_at": str,         # ISO timestamp
    "config": {                # snapshot of choices
        "shear_method": str,
        "shear_aggregation": str,
        "hub_height_m": float,
        "sensors_used": list[str],
        "ltc_algorithm": str,
        "ltc_source": str,
        "cutoff_year": int | None,
    },
    "results": {               # snapshot of outputs
        "long_term_mean_speed": float,
        "ensemble_mean_speed": float | None,
        "total_uncertainty_pct": float,
        "p50": float,
        "p75": float,
        "p90": float,
        "p99": float,
        "measurement_uncertainty_pct": float,
        "vertical_uncertainty_pct": float,
        "mcp_uncertainty_pct": float,
        "future_uncertainty_pct": float,
    },
}
```

**Update `reset()`** to clear `scenarios`.

---

### Step 10.2: Backend — Scenario API endpoints

**Update file: `server/api/routes/analysis.py`**

Add:

```python
@router.post("/scenarios")
def save_scenario(
    session_id: str,
    body: SaveScenarioRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Capture the current analysis configuration and results as a named scenario snapshot."""
```
- Read current config values from `state.runconfig`, latest LTC results, and latest uncertainty.
- Build the scenario dict per the schema above.
- Append to `state.scenarios`.
- Return `{"status": "ok", "scenario_index": len-1, "name": body.name}`.

```python
@router.get("/scenarios")
def list_scenarios(
    session_id: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Return all saved scenarios for the session."""
```
- Return `{"scenarios": state.scenarios}`.

```python
@router.delete("/scenarios/{scenario_index}")
def delete_scenario(
    session_id: str,
    scenario_index: int,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Remove one scenario by index."""
```

**Update file: `server/api/schemas.py`**

Add:
```python
class SaveScenarioRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
```

---

### Step 10.3: Backend — Scenario comparison plot

**Update file: `server/tools/visualization.py`**

**Helper: `_plot_scenario_comparison`**
```python
def _plot_scenario_comparison(state: SessionState) -> dict:
    """Plot scenario comparison as a grouped bar chart with P-factor lines.

    X-axis: scenario names
    Y-axis (left): mean wind speed (m/s) — grouped bars for LT mean, P75, P90
    Y-axis (right): total uncertainty (%) — line overlay
    """
```
- Skip if `state.scenarios` is empty.
- For each scenario, extract `long_term_mean_speed`, P75 × mean, P90 × mean, `total_uncertainty_pct`.
- Plot bars for mean/P75/P90 per scenario.
- Overlay uncertainty % as a line on secondary y-axis.
- Return via `_plot_result(fig, "Scenario Comparison")`.

Add to `plot_dispatch`:
```python
"scenario_comparison": lambda: _plot_scenario_comparison(state),
```

---

### Step 10.4: Frontend — Scenario management

**Update file: `frontend/src/lib/api.ts`**

Add to `analysisApi`:
```typescript
saveScenario: (sessionId: string, name: string) =>
  requestJson<ApiStatusResponse>(
    `/sessions/${sessionId}/scenarios`,
    { method: "POST", body: JSON.stringify({ name }) },
    sessionId,
  ),
listScenarios: (sessionId: string) =>
  requestJson<ScenarioListResponse>(`/sessions/${sessionId}/scenarios`, {}, sessionId),
deleteScenario: (sessionId: string, index: number) =>
  requestJson<ApiStatusResponse>(
    `/sessions/${sessionId}/scenarios/${index}`,
    { method: "DELETE" },
    sessionId,
  ),
```

**Update file: `frontend/src/lib/types.ts`**

Add:
```typescript
export interface ScenarioConfig {
  shear_method: string;
  shear_aggregation: string;
  hub_height_m: number;
  sensors_used: string[];
  ltc_algorithm: string;
  ltc_source: string;
  cutoff_year: number | null;
}

export interface ScenarioResults {
  long_term_mean_speed: number;
  ensemble_mean_speed: number | null;
  total_uncertainty_pct: number;
  p50: number;
  p75: number;
  p90: number;
  p99: number;
  measurement_uncertainty_pct: number;
  vertical_uncertainty_pct: number;
  mcp_uncertainty_pct: number;
  future_uncertainty_pct: number;
}

export interface Scenario {
  name: string;
  created_at: string;
  config: ScenarioConfig;
  results: ScenarioResults;
}

export interface ScenarioListResponse {
  scenarios: Scenario[];
}
```

---

### Step 10.5: ResultsPage redesign — Full dashboard

**Update file: `frontend/src/pages/ResultsPage.tsx`**

Restructure into a comprehensive results dashboard:

**Section 1: Key metrics bar**
```tsx
<div className="metric-grid">
  <MetricCard label="LT Mean Speed" value={bestLtMean ? `${bestLtMean.toFixed(2)} m/s` : "—"} tone="accent" />
  <MetricCard label="Total Uncertainty" value={latestUncertainty ? `${latestUncertainty.total_uncertainty_pct.toFixed(2)}%` : "—"} />
  <MetricCard label="P90 Factor" value={latestUncertainty ? latestUncertainty.p_factors.p90.toFixed(4) : "—"} />
  <MetricCard label="Scenarios" value={String(scenariosQuery.data?.scenarios.length ?? 0)} />
</div>
```

**Section 2: Scenario management (new)**
```tsx
<article className="content-card stack-gap">
  <div className="split-header-row">
    <span className="eyebrow">Scenario comparison</span>
    <div className="button-row">
      <input
        type="text"
        className="scenario-name-input"
        placeholder="Scenario name"
        value={scenarioName}
        onChange={(e) => setScenarioName(e.target.value)}
      />
      <button
        className="primary-button"
        type="button"
        disabled={!scenarioName.trim() || !latestUncertainty}
        onClick={() => saveScenarioMutation.mutate(scenarioName)}
      >
        Save Current as Scenario
      </button>
    </div>
  </div>

  {scenariosQuery.data?.scenarios.length ? (
    <>
      <PlotlyFigure
        plot={scenarioComparisonQuery.data}
        emptyTitle="Scenarios saved"
        emptyDetail="Save at least 2 scenarios to see the comparison chart."
      />
      <DataTable
        columns={[
          { key: "name", header: "Scenario", cell: (row) => row.name },
          { key: "lt_mean", header: "LT Mean (m/s)", cell: (row) => row.results.long_term_mean_speed.toFixed(2) },
          { key: "unc", header: "Uncertainty %", cell: (row) => row.results.total_uncertainty_pct.toFixed(2) },
          { key: "p75", header: "P75", cell: (row) => row.results.p75.toFixed(4) },
          { key: "p90", header: "P90", cell: (row) => row.results.p90.toFixed(4) },
          { key: "shear", header: "Shear Method", cell: (row) => row.config.shear_method },
          { key: "ltc", header: "LTC Algorithm", cell: (row) => row.config.ltc_algorithm },
          { key: "hub", header: "Hub Height", cell: (row) => `${row.config.hub_height_m} m` },
          {
            key: "delete",
            header: "",
            cell: (row, index) => (
              <button className="ghost-button table-action" onClick={() => deleteScenarioMutation.mutate(index)}>
                Remove
              </button>
            ),
          },
        ]}
        rows={scenariosQuery.data.scenarios}
        getRowKey={(row, index) => `${row.name}-${index}`}
        emptyTitle="No scenarios saved"
        emptyDetail=""
      />
    </>
  ) : (
    <EmptyState
      title="No scenarios yet"
      detail="Complete the LTC workflow with uncertainty, then save the current result as a named scenario. Save multiple scenarios to compare shear methods, algorithms, or hub heights."
    />
  )}
</article>
```

**Section 3: Analysis charts (existing, kept)**
Keep the existing annual means, LTC comparison, uncertainty, and site map panels.

**Section 4: Custom plots + Exports (existing, kept)**
Keep the existing custom plot requestor and runconfig export.

**Add the scenario queries and mutations:**
```tsx
const scenariosQuery = useQuery({
  queryKey: ["scenarios", sessionId],
  queryFn: () => analysisApi.listScenarios(sessionId ?? ""),
  enabled: sessionId !== null,
  staleTime: 10_000,
});

const scenarioComparisonQuery = useQuery({
  queryKey: ["scenario-comparison", sessionId, scenariosQuery.data?.scenarios.length],
  queryFn: () => resultsApi.getPlot(sessionId ?? "", "scenario_comparison", {}),
  enabled: sessionId !== null && (scenariosQuery.data?.scenarios.length ?? 0) >= 2,
  staleTime: 10_000,
});

const saveScenarioMutation = useMutation({
  mutationFn: (name: string) => analysisApi.saveScenario(sessionId ?? "", name),
  onSuccess: () => {
    setScenarioName("");
    void queryClient.invalidateQueries({ queryKey: ["scenarios", sessionId] });
  },
});

const deleteScenarioMutation = useMutation({
  mutationFn: (index: number) => analysisApi.deleteScenario(sessionId ?? "", index),
  onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["scenarios", sessionId] }),
});
```

---

### Step 10.6: OverviewPage — Project scorecard (enhanced)

**Update file: `frontend/src/pages/OverviewPage.tsx`**

Add a "Data Quality Scorecard" section if timeseries is loaded:

```tsx
{projectSummary?.timeseries_loaded ? (
  <article className="content-card stack-gap">
    <span className="eyebrow">Data quality scorecard</span>
    <div className="metric-grid">
      <MetricCard
        label="Sensors"
        value={String(projectSummary?.sensor_count ?? 0)}
      />
      <MetricCard
        label="Average coverage"
        value={projectSummary?.avg_coverage_pct ? `${Number(projectSummary.avg_coverage_pct).toFixed(1)}%` : "—"}
        tone={Number(projectSummary?.avg_coverage_pct ?? 0) > 90 ? "accent" : "warn"}
      />
      <MetricCard
        label="Cleaning rules"
        value={String(projectSummary?.cleaning_rules_applied ?? 0)}
      />
      <MetricCard
        label="LTC algorithms"
        value={String(projectSummary?.ltc_algorithms_run?.length ?? 0)}
      />
    </div>
  </article>
) : null}
```

This requires the `/summary` endpoint to return a few more fields.

**Update file: `server/api/routes/config.py`** (the `get_summary` handler)

Add to the summary response:
```python
"sensor_count": len(state.sensor_mapping) if state.sensor_mapping else 0,
"avg_coverage_pct": _avg_coverage(state),
"ltc_algorithms_run": list(state.ltc_results.keys()),
"scenario_count": len(state.scenarios),
```

Where `_avg_coverage` computes the mean non-null fraction across all mapped speed sensors.

---

### Step 10.7: CSS additions for new components

**Update file: `frontend/src/styles.css`**

Add:
```css
.scenario-name-input {
  padding: 0.6rem 1rem;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface-strong);
  font-family: var(--display);
  min-width: 200px;
}

.scenario-name-input:focus {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}

.sensor-detail-card {
  border-left: 3px solid var(--accent);
}

.split-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}
```

Note: if `.split-header-row` already exists in the CSS (it is used on ResultsPage), skip that addition.

---

### Step 10.8: Tests for Phase 10

**Create file: `tests/test_phase10.py`**

1. `test_save_scenario_captures_state` — Configure session with LTC results + uncertainty, POST `/scenarios`, verify scenario contains expected config and results keys.
2. `test_list_scenarios_returns_all` — Save 3 scenarios, GET `/scenarios`, verify 3 returned.
3. `test_delete_scenario_removes_entry` — Save 2, delete index 0, verify 1 remains.
4. `test_scenario_comparison_plot` — Save 2 scenarios, call `_plot_scenario_comparison`, verify figure has bar traces.
5. `test_scenario_without_uncertainty_fails` — Attempt to save scenario without running uncertainty first → expect 400 error.
6. `test_summary_includes_scenario_count` — Save scenario, GET `/summary`, verify `scenario_count` = 1.

**Frontend tests:**

1. `test_save_scenario_button_disabled_without_name` — Verify button is disabled when scenario name is empty.
2. `test_scenario_table_renders_rows` — Mock 2 scenarios, verify table shows 2 rows.

---

### Step 10.9: Phase 10 validation checklist

- [ ] `python -m pytest tests/ -v` — all tests pass
- [ ] `npm --prefix frontend run build` — passes
- [ ] ResultsPage: type scenario name → click "Save Current" → scenario appears in table
- [ ] ResultsPage: save 2+ scenarios → comparison bar chart renders with P-factor lines
- [ ] ResultsPage: delete scenario → table updates, chart re-renders if ≥2 remain
- [ ] ResultsPage: scenario table shows all config columns (shear method, algorithm, hub height)
- [ ] OverviewPage: scorecard shows sensor count, coverage, cleaning rules, LTC count
- [ ] Full workflow: upload → clean → shear → ERA5 → LTC → uncertainty → save scenario → change shear → re-run → save second scenario → compare both
- [ ] No scenarios have null/undefined fields in the results section

---

## Updated Summary: File Creation Order

| Phase | Files | Tool Count |
|-------|-------|------------|
| 1 | pyproject.toml, .gitignore, server/main.py, server/state/session.py, server/schemas/common.py, server/core/validators.py, server/core/spatial.py, server/core/momm.py, server/tools/data_io.py, server/tools/statistics.py, server/tools/config.py, tests/conftest.py, tests/test_phase1.py | 17 tools |
| 2 | server/core/regression.py, server/core/formulas.py, server/tools/shear.py, server/tools/extrapolation.py, server/tools/cleaning.py, tests/test_phase2.py | 12 tools |
| 3 | server/tools/era5.py, server/tools/ltc.py, server/tools/ltc_ml.py, server/tools/air_density.py, tests/test_phase3.py | 11 tools |
| 4 | server/tools/ensemble.py, server/tools/clipping.py, server/tools/homogeneity.py, server/tools/uncertainty.py, server/tools/visualization.py, server/tools/map.py, tests/test_phase4.py | 19 tools |
| 5 | tests/test_e2e.py, Dockerfile, docker-compose.yml, .env.example, librechat_config.yaml, README.md | — |
| 6 | server/api/*, server/state/manager.py, frontend/*, tests/test_api_sessions.py, tests/test_api_workflow.py | — |
| 7 | Update: visualization.py (+5 helpers), results.py (+3 dispatches), analysis.py (+1 endpoint), schemas.py (+1 model), DataPage.tsx (redesign), SitePage.tsx (inline charts), HelpTooltip.tsx, styles.css, api.ts, types.ts, tests/test_phase7.py | — |
| 8 | Update: visualization.py (+5 helpers), results.py (+5 dispatches), schemas.py (+1 field), LtcPage.tsx (workbench redesign), algorithmHelp.ts, tests/test_phase8.py | — |
| 9 | New: server/api/routes/exports.py. Update: GeoJsonMapRuntime.tsx (rings, terrain, labels), ReanalysisPage.tsx (charts), visualization.py (+2 helpers), api.ts (exportsApi), DataPage/LtcPage/ResultsPage (export buttons), styles.css, tests/test_phase9.py | — |
| 10 | Update: session.py (+scenarios), analysis.py (+3 endpoints), schemas.py (+1 model), visualization.py (+1 helper), ResultsPage.tsx (dashboard + scenarios), OverviewPage.tsx (scorecard), config.py (summary fields), api.ts, types.ts, styles.css, tests/test_phase10.py | — |
| **Total through Phase 10** | **~50 files modified/created** | **59 MCP tools + 20 new plot helpers + 8 new API endpoints** |
