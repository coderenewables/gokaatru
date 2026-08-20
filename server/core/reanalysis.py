"""reanalysis — per-source descriptors for the long-term reference datasets.

ERA5 and MERRA-2 are both long-term references, but they are not interchangeable at
the column level: ERA5 is served at 100 m and MERRA-2 at 50 m. That difference used
to be invisible because only ERA5 was ever interpolated to site, so ``Spd_100m`` and
a default ``reference_height_m=100.0`` could be written as literals throughout the
pipeline and never contradicted.

Promoting MERRA-2 to a first-class reference (design doc §6) makes those literals
wrong. ``_BRIGHTHUB_MERRA_COLUMNS`` maps a ``Spd_100m_mps`` key that the MERRA-2
payload never contains, ``_interpolate_era5_to_site`` requires ``Spd_100m`` on every
node frame, ``_resolve_ltc_columns`` hardcodes ``long_col = "Spd_100m"``, and
``extrapolate_reanalysis_to_hub`` defaults its reference height to 100 m. Each of
those is a separate place to get MERRA-2 wrong.

This module is the single place the per-source facts are written down. Everything
that needs to know a reference's height or column names resolves it from here, so
adding a third reference is one table entry rather than an audit of the pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReferenceSource:
    """One long-term reanalysis reference and the column contract it is served under."""

    name: str
    """Canonical identifier used in the runconfig and as the session storage key."""

    label: str
    """Human-readable name for error messages and UI."""

    native_height_m: float
    """Height of the served wind field. Not a default — a property of the dataset."""

    speed_col: str
    """Wind-speed column name on node frames and on the interpolated site series."""

    dir_col: str
    """Wind-direction column name on node frames and on the interpolated site series."""

    grid_lat_deg: float
    """Grid spacing in latitude, used to size the node search box."""

    grid_lon_deg: float
    """Grid spacing in longitude. MERRA-2 is coarser in longitude than in latitude."""


ERA5 = ReferenceSource(
    name="era5",
    label="ERA5",
    native_height_m=100.0,
    speed_col="Spd_100m",
    dir_col="Dir_100m",
    grid_lat_deg=0.25,
    grid_lon_deg=0.25,
)

MERRA2 = ReferenceSource(
    name="merra2",
    label="MERRA-2",
    # MERRA-2 serves 50 m winds; it has no 100 m field at all. Treating 100 m as a
    # global default silently produced a wrong extrapolation lever for this source.
    native_height_m=50.0,
    speed_col="Spd_50m",
    dir_col="Dir_50m",
    grid_lat_deg=0.5,
    grid_lon_deg=0.625,
)

REFERENCE_SOURCES: dict[str, ReferenceSource] = {ERA5.name: ERA5, MERRA2.name: MERRA2}

DEFAULT_REFERENCE_SOURCE = ERA5.name

# Variables interpolated to site alongside the wind field. Speed and direction are
# handled separately because they are per-source and because direction is derived
# from vector-interpolated u/v rather than interpolated directly.
AUXILIARY_VARIABLES: tuple[str, ...] = ("sp", "t2m", "d2m")


def get_reference_source(name: str) -> ReferenceSource:
    """Return the descriptor for a reference source, rejecting unknown names."""
    try:
        return REFERENCE_SOURCES[name]
    except KeyError:
        valid = ", ".join(sorted(REFERENCE_SOURCES))
        raise ValueError(f"source must be one of {valid}, got '{name}'") from None


def reference_source_names() -> tuple[str, ...]:
    """Return every known reference source name in a stable order."""
    return tuple(REFERENCE_SOURCES)
