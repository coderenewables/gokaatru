"""Energy and advanced measured-wind diagnostics for the Sensor Overview."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import genextreme, gumbel_r

from server.core.validators import detect_timestep_minutes
from server.main import mcp
from server.state.session import SessionState, session
from server.tools.atmosphere import _atmospheric_series

COMPASS_16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def _require_speed_series(state: SessionState, speed_sensor: str) -> pd.Series:
    """Return a selected measured wind-speed series from the loaded session data."""
    if state.timeseries_df is None:
        raise ValueError("Timeseries data is not loaded")
    if speed_sensor not in state.timeseries_df.columns:
        raise ValueError(f"Sensor column '{speed_sensor}' not found in loaded timeseries")
    return state.timeseries_df[speed_sensor].astype(float)


ISA_SEA_LEVEL_DENSITY = 1.225


def _density_for_energy(state: SessionState, speed: pd.Series) -> tuple[float, str, pd.Series | None]:
    """Return (mean density, source, aligned density series) for energy calculations.

    The series is returned alongside the scalar because the monthly breakdown needs it:
    density varies by about 9% between winter and summer at a temperate site, and
    applying a single annual mean to every month misstated monthly power density by
    -4.3% in January and +4.5% in July while cancelling almost exactly in the annual
    total, so the error was invisible in the headline number.
    """
    try:
        density, _temperature, _pressure, _humidity = _atmospheric_series(state)
        concurrent = pd.concat([speed, density], axis=1, sort=False).dropna()
        if not concurrent.empty:
            aligned = concurrent.iloc[:, 1]
            return float(aligned.mean()), "measured", aligned
    except ValueError:
        pass
    return ISA_SEA_LEVEL_DENSITY, "standard", None


def _compute_energy_metrics(state: SessionState, speed_sensor: str, direction_sensor: str = "") -> dict:
    """Compute wind-power density and optional directional energy contribution from measured speeds."""
    speed = _require_speed_series(state, speed_sensor)
    valid = speed[speed >= 0].dropna()
    if valid.empty:
        raise ValueError(f"Sensor '{speed_sensor}' has no non-negative values for energy analysis")
    air_density, density_source, density_series = _density_for_energy(state, valid)
    if density_series is None:
        # No measured density: a single standard value is all there is, so the monthly
        # profile carries no density seasonality and says so.
        monthly = 0.5 * air_density * valid.pow(3).groupby(valid.index.month).mean().reindex(range(1, 13))
        monthly_density_basis = "constant"
    else:
        # Pair each record with its own density before averaging, so the monthly profile
        # carries the real seasonal density signal rather than an annual mean.
        paired = pd.concat([valid.rename("speed"), density_series.rename("density")], axis=1).dropna()
        monthly = (0.5 * paired["density"] * paired["speed"].pow(3)).groupby(
            paired.index.month
        ).mean().reindex(range(1, 13))
        monthly_density_basis = "per_record"
    result: dict[str, object] = {
        "speed_sensor": speed_sensor,
        "record_count": int(valid.count()),
        "air_density_kg_m3": air_density,
        "density_source": density_source,
        "monthly_density_basis": monthly_density_basis,
        "density_height_basis": "pressure_sensor_height",
        "wind_power_density_w_m2": float(
            0.5 * air_density * valid.pow(3).mean()
            if density_series is None
            else (0.5 * density_series.reindex(valid.index) * valid.pow(3)).dropna().mean()
        ),
        "mean_cube_speed_m_s": float(np.cbrt(valid.pow(3).mean())),
        "monthly_power_density_w_m2": [float(value) if pd.notna(value) else None for value in monthly],
        "sectors": [],
    }
    if direction_sensor:
        if state.timeseries_df is None or direction_sensor not in state.timeseries_df.columns:
            raise ValueError(f"Direction sensor '{direction_sensor}' not found in loaded timeseries")
        aligned = pd.concat([speed, state.timeseries_df[direction_sensor].astype(float)], axis=1).dropna()
        aligned.columns = [speed_sensor, direction_sensor]
        if aligned.empty:
            raise ValueError("Energy rose requires concurrent non-null speed and direction values")
        sector_index = (((np.mod(aligned[direction_sensor], 360.0) + 11.25) % 360.0) // 22.5).astype(int)
        cube_speed = aligned[speed_sensor].pow(3)
        total_cube_speed = float(cube_speed.sum())
        result["sectors"] = [
            {
                "label": COMPASS_16[index],
                "power_density_w_m2": float(0.5 * air_density * cube_speed[sector_index == index].mean()) if (sector_index == index).any() else 0.0,
                "energy_pct": 0.0 if total_cube_speed == 0 else float(cube_speed[sector_index == index].sum() / total_cube_speed * 100.0),
            }
            for index in range(16)
        ]
    return result


def _annual_maxima(speed: pd.Series) -> pd.Series:
    """Return valid annual wind-speed maxima, excluding empty calendar years."""
    maxima = speed.dropna().resample("YE").max().dropna()
    maxima.index = maxima.index.year
    return maxima


def _compute_extremes(state: SessionState, speed_sensor: str) -> dict:
    """Fit annual-maxima GEV and Gumbel models and estimate 50/100-year wind speeds."""
    maxima = _annual_maxima(_require_speed_series(state, speed_sensor))
    if len(maxima) < 2:
        raise ValueError("Extreme-wind analysis requires at least two calendar years with valid observations")
    values = maxima.to_numpy(dtype=float)
    gev_shape, gev_loc, gev_scale = genextreme.fit(values)
    gumbel_loc, gumbel_scale = gumbel_r.fit(values)
    return {
        "speed_sensor": speed_sensor,
        "sample_years": int(len(maxima)),
        "minimum_recommended_years": 5,
        "screening_only": bool(len(maxima) < 5),
        "annual_maxima": [{"year": int(year), "max_speed": float(value)} for year, value in maxima.items()],
        "gev": {
            "shape": float(gev_shape),
            "location": float(gev_loc),
            "scale": float(gev_scale),
            "wind_50_year": float(genextreme.isf(1.0 / 50.0, gev_shape, loc=gev_loc, scale=gev_scale)),
            "wind_100_year": float(genextreme.isf(1.0 / 100.0, gev_shape, loc=gev_loc, scale=gev_scale)),
        },
        "gumbel": {
            "location": float(gumbel_loc),
            "scale": float(gumbel_scale),
            "wind_50_year": float(gumbel_r.isf(1.0 / 50.0, loc=gumbel_loc, scale=gumbel_scale)),
            "wind_100_year": float(gumbel_r.isf(1.0 / 100.0, loc=gumbel_loc, scale=gumbel_scale)),
        },
    }


def _consecutive_ramps(speed: pd.Series) -> tuple[pd.Series, int]:
    """Calculate signed ramps only across consecutive timestamps at the inferred measurement interval."""
    timestep_minutes = detect_timestep_minutes(speed.to_frame())
    expected = pd.Timedelta(minutes=timestep_minutes)
    consecutive = speed.index.to_series().diff().eq(expected)
    ramps = speed.diff().where(consecutive & speed.notna() & speed.shift().notna()).dropna()
    return ramps, timestep_minutes


def _compute_ramps(state: SessionState, speed_sensor: str, event_threshold_m_s: float = 3.0) -> dict:
    """Summarize consecutive-record wind-speed changes and threshold ramp events."""
    if event_threshold_m_s <= 0:
        raise ValueError("Ramp-event threshold must be positive")
    ramps, timestep_minutes = _consecutive_ramps(_require_speed_series(state, speed_sensor))
    if ramps.empty:
        raise ValueError("No consecutive valid records are available for ramp analysis")
    absolute = ramps.abs()
    events = ramps[absolute >= event_threshold_m_s]
    largest = events.abs().sort_values(ascending=False).head(10)
    return {
        "speed_sensor": speed_sensor,
        "timestep_minutes": timestep_minutes,
        "record_count": int(len(ramps)),
        "mean_absolute_ramp_m_s": float(absolute.mean()),
        "p95_absolute_ramp_m_s": float(absolute.quantile(0.95)),
        "event_threshold_m_s": event_threshold_m_s,
        "event_count": int(len(events)),
        "largest_events": [
            {"timestamp": timestamp.isoformat(), "ramp_m_s": float(ramps.loc[timestamp])}
            for timestamp in largest.index
        ],
    }


def _duration_periods(mask: pd.Series, timestep_minutes: int) -> list[float]:
    """Measure contiguous true-mask durations while breaking periods across missing time intervals."""
    periods: list[float] = []
    start: pd.Timestamp | None = None
    previous: pd.Timestamp | None = None
    expected = pd.Timedelta(minutes=timestep_minutes)
    for timestamp, active in mask.items():
        contiguous = previous is not None and timestamp - previous == expected
        if bool(active) and (start is None or not contiguous):
            if start is not None and previous is not None:
                periods.append((previous - start).total_seconds() / 60.0 + timestep_minutes)
            start = timestamp
        elif not bool(active) and start is not None and previous is not None:
            periods.append((previous - start).total_seconds() / 60.0 + timestep_minutes)
            start = None
        previous = timestamp
    if start is not None and previous is not None:
        periods.append((previous - start).total_seconds() / 60.0 + timestep_minutes)
    return periods


def _compute_persistence(
    state: SessionState,
    speed_sensor: str,
    calm_threshold_m_s: float = 3.0,
    high_wind_threshold_m_s: float = 15.0,
) -> dict:
    """Quantify calm and persistent-high-wind periods using consecutive valid samples only."""
    if calm_threshold_m_s < 0 or high_wind_threshold_m_s <= calm_threshold_m_s:
        raise ValueError("Persistence thresholds must satisfy 0 <= calm < high wind")
    speed = _require_speed_series(state, speed_sensor).dropna()
    timestep_minutes = detect_timestep_minutes(speed.to_frame())
    calm_periods = _duration_periods(speed <= calm_threshold_m_s, timestep_minutes)
    high_periods = _duration_periods(speed >= high_wind_threshold_m_s, timestep_minutes)
    return {
        "speed_sensor": speed_sensor,
        "timestep_minutes": timestep_minutes,
        "calm_threshold_m_s": calm_threshold_m_s,
        "high_wind_threshold_m_s": high_wind_threshold_m_s,
        "calm_pct": float((speed <= calm_threshold_m_s).mean() * 100.0),
        "high_wind_pct": float((speed >= high_wind_threshold_m_s).mean() * 100.0),
        "calm_period_count": len(calm_periods),
        "high_wind_period_count": len(high_periods),
        "max_calm_duration_minutes": float(max(calm_periods, default=0.0)),
        "max_high_wind_duration_minutes": float(max(high_periods, default=0.0)),
        "calm_durations_minutes": calm_periods,
        "high_wind_durations_minutes": high_periods,
    }


@mcp.tool()
def compute_energy_metrics(speed_sensor: str, direction_sensor: str = "") -> dict:
    """Compute measured wind-power density, cube-mean speed, and optional sector energy contribution."""
    return _compute_energy_metrics(session, speed_sensor, direction_sensor)


@mcp.tool()
def compute_extreme_winds(speed_sensor: str) -> dict:
    """Fit GEV and Gumbel annual-maxima models for measured extreme-wind estimates."""
    return _compute_extremes(session, speed_sensor)


@mcp.tool()
def compute_wind_ramps(speed_sensor: str, event_threshold_m_s: float = 3.0) -> dict:
    """Summarize consecutive wind-speed ramp magnitudes and threshold events."""
    return _compute_ramps(session, speed_sensor, event_threshold_m_s)


@mcp.tool()
def compute_wind_persistence(speed_sensor: str, calm_threshold_m_s: float = 3.0, high_wind_threshold_m_s: float = 15.0) -> dict:
    """Summarize calm and high-wind duration statistics from consecutive measured records."""
    return _compute_persistence(session, speed_sensor, calm_threshold_m_s, high_wind_threshold_m_s)