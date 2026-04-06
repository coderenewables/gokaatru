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

**File: `librechat_config.yaml`** (example config snippet)
```yaml
# Add to LibreChat's librechat.yaml under mcpServers:
mcpServers:
  gokaatru:
    type: sse
    url: http://localhost:8080/sse
    timeout: 120000
```

**File: `docker-compose.yml`**
```yaml
version: '3.8'

services:
  gokaatru:
    build: .
    ports:
      - "8080:8080"
    environment:
      - EARTHDATAHUB_TOKEN=${EARTHDATAHUB_TOKEN}
    volumes:
      - ./data:/app/data

  librechat:
    image: ghcr.io/danny-avila/librechat:latest
    ports:
      - "3080:3080"
    volumes:
      - ./librechat_config.yaml:/app/librechat.yaml
    depends_on:
      - gokaatru
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
CMD ["python", "-m", "server.main", "--transport", "sse", "--port", "8080"]
```

---

### Step 5.4: README

**File: `README.md`**

Write a README with:
1. One-paragraph description
2. Quick start (local): `conda activate gokaatru && pip install -e ".[ml,dev]" && python -m server.main`
3. Quick start (Docker): `docker compose up`
4. LibreChat setup instructions
5. List of all available tools (grouped by domain)
6. Link to BUILD_SPECIFICATION.md for details

---

### Step 5.5: Final validation checklist

Before declaring the build complete, verify:

- [ ] `ruff check server/ tests/` — zero warnings
- [ ] `python -m pytest tests/ -v` — all tests pass
- [ ] `python -m server.main` — server starts without errors
- [ ] `echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python -m server.main` — lists all tools
- [ ] Tool count matches spec: 59 tools total
- [ ] Every tool has a docstring
- [ ] No `Any` types anywhere in `server/`
- [ ] No `**kwargs` anywhere in `server/`
- [ ] All Pydantic models use v2 syntax
- [ ] `data/` directory is gitignored
- [ ] Docker build succeeds: `docker build -t gokaatru .`

---

## Summary: File Creation Order

| Phase | Files | Tool Count |
|-------|-------|------------|
| 1 | pyproject.toml, .gitignore, server/main.py, server/state/session.py, server/schemas/common.py, server/core/validators.py, server/core/spatial.py, server/core/momm.py, server/tools/data_io.py, server/tools/statistics.py, server/tools/config.py, tests/conftest.py, tests/test_phase1.py | 17 tools |
| 2 | server/core/regression.py, server/core/formulas.py, server/tools/shear.py, server/tools/extrapolation.py, server/tools/cleaning.py, tests/test_phase2.py | 12 tools |
| 3 | server/tools/era5.py, server/tools/ltc.py, server/tools/ltc_ml.py, server/tools/air_density.py, tests/test_phase3.py | 11 tools |
| 4 | server/tools/ensemble.py, server/tools/clipping.py, server/tools/homogeneity.py, server/tools/uncertainty.py, server/tools/visualization.py, server/tools/map.py, tests/test_phase4.py | 19 tools |
| 5 | tests/test_e2e.py, Dockerfile, docker-compose.yml, librechat_config.yaml, README.md | — |
| **Total** | **36 files** | **59 tools** |
