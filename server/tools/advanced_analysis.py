"""Energy and advanced measured-wind diagnostics for the Sensor Overview."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import genextreme, gumbel_r

from server.core.validators import detect_timestep_minutes
from server.main import mcp
from server.state.session import SessionState, session
from server.core.formulas import adjust_density_to_height
from server.tools.atmosphere import _atmospheric_series, _sensor_height

COMPASS_16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def _require_speed_series(state: SessionState, speed_sensor: str) -> pd.Series:
    """Return a selected measured wind-speed series from the loaded session data."""
    if state.timeseries_df is None:
        raise ValueError("Timeseries data is not loaded")
    if speed_sensor not in state.timeseries_df.columns:
        raise ValueError(f"Sensor column '{speed_sensor}' not found in loaded timeseries")
    return state.timeseries_df[speed_sensor].astype(float)


ISA_SEA_LEVEL_DENSITY = 1.225
# Layer temperature used for the density height correction when the measured temperature
# is unavailable; the correction is worth ~1.2% per 100 m and is insensitive to this.
ISA_SEA_LEVEL_TEMPERATURE_K = 288.15


def _density_temperature_kelvin(state: SessionState) -> float:
    """Return the campaign mean temperature in Kelvin for the density height correction."""
    try:
        from server.tools.atmosphere import _find_sensor, _temperature_kelvin

        frame = state.timeseries_df
        if frame is not None:
            name = _find_sensor(state, "temperature")
            valid = _temperature_kelvin(frame[name]).dropna()
            if not valid.empty:
                return float(valid.mean())
    except (ValueError, KeyError):
        pass
    return ISA_SEA_LEVEL_TEMPERATURE_K


def _density_for_energy(
    state: SessionState, speed: pd.Series
) -> tuple[float, str, pd.Series | None, str | None]:
    """Return (mean density, source, aligned density series) for energy calculations.

    The series is returned alongside the scalar because the monthly breakdown needs it:
    density varies by about 9% between winter and summer at a temperate site, and
    applying a single annual mean to every month misstated monthly power density by
    -4.3% in January and +4.5% in July while cancelling almost exactly in the annual
    total, so the error was invisible in the headline number.
    """
    try:
        density, _temperature, pressure_name, _humidity = _atmospheric_series(state)
        concurrent = pd.concat([speed, density], axis=1, sort=False).dropna()
        if not concurrent.empty:
            aligned = concurrent.iloc[:, 1]
            return float(aligned.mean()), "measured", aligned, pressure_name
    except ValueError:
        pass
    return ISA_SEA_LEVEL_DENSITY, "standard", None, None


def _compute_energy_metrics(state: SessionState, speed_sensor: str, direction_sensor: str = "") -> dict:
    """Compute wind-power density and optional directional energy contribution from measured speeds."""
    speed = _require_speed_series(state, speed_sensor)
    valid = speed[speed >= 0].dropna()
    if valid.empty:
        raise ValueError(f"Sensor '{speed_sensor}' has no non-negative values for energy analysis")
    air_density, density_source, density_series, pressure_name = _density_for_energy(state, valid)

    # Match the density to the height of the speed series it multiplies.  Density derived
    # from a 2 m pressure sensor and applied at a 150 m hub overstates it by about 1.8%, and
    # power density scales linearly with density, so that was a direct overstatement of the
    # resource.  Both heights are reported so the adjustment is auditable.
    speed_height = _sensor_height(state, speed_sensor)
    pressure_height = _sensor_height(state, pressure_name) if pressure_name else None
    height_adjustment = 1.0
    height_basis = "uncorrected_pressure_sensor_height"
    if speed_height is not None and pressure_height is not None and density_series is not None:
        temperatures = _density_temperature_kelvin(state)
        height_adjustment = float(
            adjust_density_to_height(1.0, temperatures, pressure_height, speed_height)
        )
        density_series = density_series * height_adjustment
        air_density = float(density_series.mean())
        height_basis = "corrected_to_speed_sensor_height"

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
        "density_height_basis": height_basis,
        "density_height_adjustment": height_adjustment,
        "pressure_sensor_height_m": pressure_height,
        "speed_sensor_height_m": speed_height,
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


# Extreme-wind guards (F-77, F-78).
#
# A 3-parameter GEV is not identifiable from a handful of annual maxima.  Measured across
# twelve seeds on a 14-month campaign, twelve of twelve fits were useless: ten collapsed so
# that V50 landed at or below the largest maximum already observed, and two diverged past
# 1e9 m/s.  Ten years is the point at which a three-parameter tail fit starts to mean
# something; below it only the two-parameter Gumbel is offered.
GEV_MIN_YEARS = 10
EXTREME_MIN_YEARS = 2

# A calendar year covering a fraction of the calendar is not an annual maximum.  Measured
# as the fraction of the year's DAYS holding at least one record, not as record
# completeness: the latter cannot tell a partial season from ordinary sensor downtime.
DEFAULT_EXTREME_YEAR_COVERAGE = 0.9

# No 10-minute mean wind speed above roughly 60 m/s has ever been recorded anywhere on
# Earth; the strongest surface gust on record is 113 m/s.  A fit returning more than this
# has diverged, whatever its inputs looked like.
IMPLAUSIBLE_SPEED_MPS = 120.0


def _annual_maxima(
    speed: pd.Series,
    min_year_coverage: float = 0.0,
) -> tuple[pd.Series, list[dict[str, object]]]:
    """Return annual wind-speed maxima, dropping calendar years too sparse to hold one.

    ``resample("YE").max()`` treats any calendar year with a single record as a year, so a
    campaign that starts or ends mid-year contributed a partial-season maximum to a fit
    whose whole premise is that each point is an *annual* maximum (F-78).  The effect is
    large and its sign is not predictable: a low outlier pulls the Gumbel location down but
    pushes its scale up, and at the 50-year quantile the scale dominates.  Measured on eight
    complete years with the last truncated - Jun-Dec -8.3%, May-Sep +17.5%, July only
    +40.9% on V50.

    The gate is **day coverage**: the fraction of the year's days holding at least one valid
    record.  Record completeness would be the obvious choice and is the wrong one, because it
    cannot tell a partial *season* from ordinary sensor downtime.  Measured on a 2015 series:

    ==============================  ===================  =============
    year                            record completeness  day coverage
    ==============================  ===================  =============
    complete                                    100.00%        100.00%
    85% scattered recovery                       84.93%        100.00%
    July only                                     8.49%          8.49%
    ==============================  ===================  =============

    A 90% completeness gate rejects the gappy-but-whole year, which yields a perfectly good
    annual maximum.  Day coverage keeps it and still rejects July.  Record completeness is
    reported alongside as a diagnostic.
    """
    valid = speed.dropna()
    if valid.empty:
        return valid, []
    try:
        timestep_minutes = float(detect_timestep_minutes(valid.to_frame()))
    except ValueError:
        timestep_minutes = 0.0
    kept: dict[int, float] = {}
    excluded: list[dict[str, object]] = []
    for year, group in valid.groupby(valid.index.year):
        days = 366 if pd.Timestamp(year=int(year), month=12, day=31).dayofyear == 366 else 365
        coverage = float(len(np.unique(group.index.dayofyear)) / days)
        expected = days * 24 * 60 / timestep_minutes if timestep_minutes > 0 else 0.0
        completeness = float(len(group) / expected) if expected > 0 else float("nan")
        if min_year_coverage > 0.0 and coverage < min_year_coverage:
            excluded.append({
                "year": int(year),
                "records": int(len(group)),
                "days_covered": int(len(np.unique(group.index.dayofyear))),
                "days_in_year": int(days),
                "day_coverage": round(coverage, 4),
                "record_completeness": round(completeness, 4) if np.isfinite(completeness) else None,
                "months_covered": sorted({int(month) for month in group.index.month}),
                "partial_year_max_speed": float(group.max()),
            })
            continue
        kept[int(year)] = float(group.max())
    return pd.Series(kept, dtype=float), excluded


def _return_levels(fit_isf, largest_observed: float) -> dict[str, object]:
    """Return 50- and 100-year levels plus a verdict on whether the fit is usable.

    Two things make a return level unusable, and neither depends on the record length:

    - **Divergent** — a level beyond any wind speed ever recorded, which is what the
      unidentifiable 2-point GEV produced in 2 of 12 trials (3.0e9 and 2.7e12 m/s).
    - **Collapsed** — a hundred-year level no higher than the fifty-year one, so extra
      return period buys no extra wind. That is impossible for a non-degenerate
      distribution and was the other 10 of 12.

    A 50-year level *below the largest observed maximum* is reported separately and is
    deliberately **not** treated as a failure: the largest of twenty annual maxima is
    roughly a twenty-year event and ordinary sampling variation puts it above a fitted V50
    often enough. It is worth a reader's attention, not a rejection.
    """
    wind_50 = float(fit_isf(1.0 / 50.0))
    wind_100 = float(fit_isf(1.0 / 100.0))
    problems: list[str] = []
    if not (np.isfinite(wind_50) and np.isfinite(wind_100)):
        problems.append("the fit did not converge to a finite return level")
    elif wind_50 > IMPLAUSIBLE_SPEED_MPS:
        problems.append(
            f"the 50-year level of {wind_50:,.0f} m/s exceeds any wind speed ever recorded, "
            "so the fit has diverged"
        )
    elif wind_100 <= wind_50 + 1e-6:
        problems.append(
            f"the 100-year level ({wind_100:.4f} m/s) is no higher than the 50-year level "
            f"({wind_50:.4f} m/s), so the fitted tail has collapsed onto a bound at the data "
            "and extra return period buys no extra wind speed"
        )
    levels: dict[str, object] = {
        "wind_50_year": wind_50,
        "wind_100_year": wind_100,
        "plausible": not problems,
        "below_largest_observed": bool(np.isfinite(wind_50) and wind_50 <= largest_observed),
    }
    if problems:
        levels["implausibility"] = problems[0]
    return levels


def _compute_extremes(
    state: SessionState,
    speed_sensor: str,
    source: str = "auto",
    min_year_coverage: float = DEFAULT_EXTREME_YEAR_COVERAGE,
) -> dict:
    """Fit annual-maxima Gumbel and GEV models and estimate 50/100-year wind speeds.

    ``source`` selects the series (F-79). ``"auto"`` prefers the long-term corrected series
    the pipeline exists to build — ensemble, then any LTC result — and falls back to the
    measured campaign. A 50-year level from two annual maxima extrapolates 25x beyond the
    data; from a twenty-year corrected series it extrapolates 2.5x, which is the difference
    between an estimate and a guess.
    """
    if source not in {"auto", "measured", "long_term"}:
        raise ValueError(f"source must be one of auto, measured, long_term, got '{source}'")
    if not 0.0 <= min_year_coverage <= 1.0:
        raise ValueError(f"min_year_coverage must be between 0 and 1, got {min_year_coverage}")

    series: pd.Series | None = None
    series_basis = "measured"
    if source in {"auto", "long_term"}:
        candidate, origin = state.long_term_speed_series()
        if candidate is not None and isinstance(candidate.index, pd.DatetimeIndex):
            series, series_basis = candidate, origin
        elif source == "long_term":
            raise ValueError(
                "No long-term corrected series with a usable timestamp index is available. "
                "Run the LTC and ensemble stages first, or pass source='measured'."
            )
    if series is None:
        series = _require_speed_series(state, speed_sensor)
        series_basis = f"measured:{speed_sensor}"

    maxima, excluded_years = _annual_maxima(series, min_year_coverage)
    if len(maxima) < EXTREME_MIN_YEARS:
        raise ValueError(
            f"Extreme-wind analysis requires at least {EXTREME_MIN_YEARS} calendar years "
            f"covering {min_year_coverage:.0%} of the calendar, got "
            f"{len(maxima)} ({len(excluded_years)} year(s) excluded as partial)."
        )
    values = maxima.to_numpy(dtype=float)
    largest_observed = float(values.max())
    sample_years = int(len(maxima))

    gumbel_loc, gumbel_scale = gumbel_r.fit(values)
    gumbel = {
        "location": float(gumbel_loc),
        "scale": float(gumbel_scale),
        **_return_levels(
            lambda q: gumbel_r.isf(q, loc=gumbel_loc, scale=gumbel_scale), largest_observed
        ),
    }

    # F-77: three parameters need enough points to be identifiable. Below the threshold the
    # GEV is not fitted at all rather than fitted and disclaimed, because the numbers it
    # produced were not merely uncertain - they were pinned to the data or divergent.
    if sample_years >= GEV_MIN_YEARS:
        gev_shape, gev_loc, gev_scale = genextreme.fit(values)
        gev: dict[str, object] = {
            "available": True,
            "shape": float(gev_shape),
            "location": float(gev_loc),
            "scale": float(gev_scale),
            **_return_levels(
                lambda q: genextreme.isf(q, gev_shape, loc=gev_loc, scale=gev_scale),
                largest_observed,
            ),
        }
    else:
        gev = {
            "available": False,
            "reason": (
                f"A generalised extreme value fit estimates three parameters and only "
                f"{sample_years} annual maxima are available; at least {GEV_MIN_YEARS} are "
                "needed for the fit to be identifiable. Below that it does not produce an "
                "uncertain answer, it produces a meaningless one - measured across twelve "
                "two-year campaigns, every fit either collapsed onto the observed data or "
                "diverged past 1e9 m/s. The two-parameter Gumbel fit is reported instead."
            ),
        }

    result: dict[str, object] = {
        "speed_sensor": speed_sensor,
        "series_basis": series_basis,
        "source": source,
        "sample_years": sample_years,
        "minimum_recommended_years": 5,
        "gev_minimum_years": GEV_MIN_YEARS,
        "screening_only": bool(sample_years < 5),
        "min_year_coverage": float(min_year_coverage),
        "annual_maxima": [{"year": int(year), "max_speed": float(value)} for year, value in maxima.items()],
        "years_excluded": excluded_years,
        "largest_observed_max_speed": largest_observed,
        "gev": gev,
        "gumbel": gumbel,
    }

    warnings: list[str] = []
    if series_basis.startswith("measured"):
        warnings.append(
            "Fitted to the measured campaign rather than the long-term corrected series. A "
            "50-year return period estimated from a short campaign extrapolates far beyond "
            "its data; run the LTC and ensemble stages and re-run this for a longer basis."
        )
    if excluded_years:
        years = ", ".join(str(entry["year"]) for entry in excluded_years)
        warnings.append(
            f"{len(excluded_years)} calendar year(s) ({years}) covered less than "
            f"{min_year_coverage:.0%} of the calendar and were excluded. A "
            "partial year's maximum is a partial-season maximum, and including one moved V50 "
            "by up to +40% in testing."
        )
    if sample_years < 5:
        warnings.append(
            f"{sample_years} annual maxima is a screening basis only, not a design value."
        )
    if not gumbel["plausible"]:
        warnings.append(f"The Gumbel fit is not plausible: {gumbel['implausibility']}")
    if gev.get("available") and not gev.get("plausible"):
        warnings.append(f"The GEV fit is not plausible: {gev['implausibility']}")
    below = [name for name in ("gumbel", "gev") if result[name].get("below_largest_observed")]
    if below:
        warnings.append(
            f"The {' and '.join(below)} 50-year level(s) sit below the largest annual maximum "
            f"already observed ({largest_observed:.2f} m/s). With {sample_years} maxima that "
            "can be ordinary sampling variation rather than a bad fit, but it is worth "
            "checking the largest year against the record before quoting a design value."
        )
    if warnings:
        result["warning"] = " ".join(warnings)
    return result


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
def compute_extreme_winds(
    speed_sensor: str,
    source: str = "auto",
    min_year_coverage: float = DEFAULT_EXTREME_YEAR_COVERAGE,
) -> dict:
    """Fit annual-maxima Gumbel and GEV models and estimate 50/100-year wind speeds.

    ``source`` defaults to ``"auto"``, which prefers the long-term corrected series over the
    measured campaign: a 50-year return period from a two-year campaign extrapolates 25x
    beyond its data. ``"measured"`` forces the campaign, ``"long_term"`` requires the
    corrected series and refuses without one.

    ``min_year_coverage`` drops calendar years covering too little of the calendar to hold an
    annual maximum. A
    partial year contributes a partial-season maximum, which moved V50 by up to +40% in
    testing.

    The GEV fit is only offered once enough annual maxima exist to identify its three
    parameters; below that only the two-parameter Gumbel fit is reported, and both carry a
    plausibility verdict.
    """
    return _compute_extremes(session, speed_sensor, source, min_year_coverage)


@mcp.tool()
def compute_wind_ramps(speed_sensor: str, event_threshold_m_s: float = 3.0) -> dict:
    """Summarize consecutive wind-speed ramp magnitudes and threshold events."""
    return _compute_ramps(session, speed_sensor, event_threshold_m_s)


@mcp.tool()
def compute_wind_persistence(speed_sensor: str, calm_threshold_m_s: float = 3.0, high_wind_threshold_m_s: float = 15.0) -> dict:
    """Summarize calm and high-wind duration statistics from consecutive measured records."""
    return _compute_persistence(session, speed_sensor, calm_threshold_m_s, high_wind_threshold_m_s)