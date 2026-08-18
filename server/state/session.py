"""session — In-memory session state for Phase 1 workflows.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from server.core.runconfig import strip_mirrors
from server.schemas.common import Coordinate


def _utcnow() -> datetime:
    """Return a timezone-aware UTC timestamp for session lifecycle tracking."""
    return datetime.now(timezone.utc)


class SessionState:
    """Store the active project state following the GoKaatru session contract."""

    session_id: str | None
    workspace_dir: Path | None
    created_at: datetime | None
    updated_at: datetime | None
    project_name: str | None
    coordinate: Coordinate | None
    measurement_type: str | None
    hub_height_m: float | None
    timeseries_df: pd.DataFrame | None
    raw_timeseries_df: pd.DataFrame | None
    sensor_mapping: dict[float, dict[str, str | None]]
    sensor_inventory: dict[str, dict[str, object]]
    cleaning_log: list[dict[str, object]]
    shear_timeseries_df: pd.DataFrame | None
    shear_clamp_stats: dict[str, object] | None
    roughness_timeseries_df: pd.DataFrame | None
    shear_table: pd.DataFrame | None
    roughness_table: pd.DataFrame | None
    brighthub_token: str | None
    era5_nodes: list[dict[str, object]] | None
    era5_data: dict[str, pd.DataFrame]
    era5_interpolated_df: pd.DataFrame | None
    merra_nodes: list[dict[str, object]] | None
    merra_data: dict[str, pd.DataFrame]
    reanalysis_cache_identity: dict[str, object] | None
    ltc_results: dict[str, dict[str, object]]
    ensemble_df: pd.DataFrame | None
    clipping_result: dict[str, object] | None
    # How the measured series was aligned and resampled for the most recent LTC match
    # (F-07 interval labelling, F-66 hourly coverage gate).
    ltc_matching_disclosure: dict[str, object]
    data_version: int
    derived_versions: dict[str, int]
    latest_uncertainty: dict[str, object] | None
    scenarios: list[dict[str, object]]
    runconfig: dict[str, object]
    timezone: object | None  # datetime.timezone or ZoneInfo — set from datamodel
    windkit_data: dict[str, object]
    executed_nodes: set[str]
    workflow_execution: dict[str, object]
    workflow_runs: list[dict[str, object]]

    def __init__(self) -> None:
        """Initialize the singleton session state per the GoKaatru build spec."""
        self.session_id = None
        self.workspace_dir = None
        self.created_at = None
        self.updated_at = None
        self.reset()

    def reset(self, preserve_workspace: bool = False) -> None:
        """Reset session fields while optionally preserving workspace metadata for managed sessions."""
        preserved_session_id = self.session_id if preserve_workspace else None
        preserved_workspace_dir = self.workspace_dir if preserve_workspace else None
        preserved_created_at = self.created_at if preserve_workspace else None
        self.project_name = None
        self.coordinate = None
        self.measurement_type = None
        self.hub_height_m = None
        self.timeseries_df = None
        self.raw_timeseries_df = None
        self.sensor_mapping = {}
        self.sensor_inventory = {}
        self.cleaning_log = []
        self.shear_timeseries_df = None
        self.shear_clamp_stats = None
        self.roughness_timeseries_df = None
        self.shear_table = None
        self.roughness_table = None
        self.brighthub_token = None
        self.era5_nodes = None
        self.era5_data = {}
        self.era5_interpolated_df = None
        self.merra_nodes = None
        self.merra_data = {}
        self.reanalysis_cache_identity = None
        self.ltc_results = {}
        self.ensemble_df = None
        self.clipping_result = None
        self.ltc_matching_disclosure = {}
        self.data_version = 0
        self.derived_versions = {}
        self.latest_uncertainty = None
        self.scenarios = []
        self.runconfig = {}
        self.timezone = None
        self.windkit_data = {}
        # Node ids this session actually executed, so a client-supplied "done" can be
        # corroborated instead of taken on trust (F-10).
        self.executed_nodes = set()
        self.workflow_execution = {
            "run_id": None,
            "is_running": False,
            "cancel_requested": False,
            "node_statuses": {},
            "events": [],
        }
        self.workflow_runs = []
        self.session_id = preserved_session_id
        self.workspace_dir = preserved_workspace_dir
        self.created_at = preserved_created_at
        self.updated_at = _utcnow() if preserve_workspace else None

    def touch(self) -> None:
        """Update the last-modified timestamp for managed sessions after state mutations."""
        if self.workspace_dir is None and self.session_id is None:
            return
        if self.created_at is None:
            self.created_at = _utcnow()
        self.updated_at = _utcnow()

    def clone_for_transaction(self) -> SessionState:
        """Return an isolated snapshot for all-or-nothing session mutations."""
        return copy.deepcopy(self)

    def commit_transaction(self, staged: SessionState) -> None:
        """Replace this session's state with a successfully staged snapshot."""
        self.__dict__.update(staged.__dict__)

    def set_project_name(self, project_name: str | None) -> None:
        """Persist project name in runconfig while retaining a mirrored session convenience field."""
        self.project_name = project_name
        if project_name is None:
            self.runconfig.pop("project_name", None)
            self.touch()
            return
        self.runconfig["project_name"] = project_name
        self.touch()

    def set_coordinate(self, coordinate: Coordinate | None) -> None:
        """Persist site location in runconfig while retaining a mirrored session convenience field."""
        self.coordinate = coordinate
        if coordinate is None:
            self.runconfig.pop("location", None)
            self.touch()
            return
        self.runconfig["location"] = coordinate.model_dump()
        self.touch()

    def set_measurement_type(self, measurement_type: str | None) -> None:
        """Persist measurement type in runconfig while retaining a mirrored session convenience field."""
        self.measurement_type = measurement_type
        if measurement_type is None:
            self.runconfig.pop("measurement_type", None)
            self.touch()
            return
        self.runconfig["measurement_type"] = measurement_type
        self.touch()

    def set_hub_height_m(self, hub_height_m: float | None) -> None:
        """Persist hub height in runconfig while retaining a mirrored session convenience field."""
        self.hub_height_m = hub_height_m
        if hub_height_m is None:
            self.runconfig.pop("hub_height_m", None)
            self.touch()
            return
        self.runconfig["hub_height_m"] = float(hub_height_m)
        self.touch()

    def get_coordinate(self) -> Coordinate | None:
        """Return the site coordinate from runconfig when available, else the mirrored session field."""
        location = self.runconfig.get("location")
        if isinstance(location, dict) and {"latitude", "longitude"}.issubset(location):
            return Coordinate(
                latitude=float(location["latitude"]),
                longitude=float(location["longitude"]),
                elevation_m=float(location.get("elevation_m", 0.0)),
            )
        return self.coordinate

    def get_project_name(self) -> str | None:
        """Return the project name from runconfig when available, else the mirrored session field."""
        value = self.runconfig.get("project_name")
        return str(value) if isinstance(value, str) else self.project_name

    def get_measurement_type(self) -> str | None:
        """Return the measurement type from runconfig when available, else the mirrored session field."""
        value = self.runconfig.get("measurement_type")
        return str(value) if isinstance(value, str) else self.measurement_type

    def get_hub_height_m(self) -> float | None:
        """Return the hub height from runconfig when available, else the mirrored session field."""
        value = self.runconfig.get("hub_height_m")
        if isinstance(value, (int, float)):
            return float(value)
        return self.hub_height_m

    def bump_data_version(self) -> int:
        """Record that the measured working data changed, invalidating anything derived from it.

        Session state is long-lived and mutable: cleaning rewrites ``timeseries_df`` in place,
        undo rebuilds it from raw, and a sensor-selection change removes columns outright.
        Every derived artifact — the shear timeseries and table, the hub-height column, the
        LTC results, the ensemble, the uncertainty — was left untouched and unmarked by all
        three, so a session could report a long-term mean derived from data that no longer
        existed.  Recomputing after the same cleaning gives a different answer, so the stale
        value was materially wrong rather than merely old.

        A monotonic counter is enough to make that visible: derived artifacts record the
        version they were built from, and any consumer can compare.
        """
        self.data_version += 1
        self.touch()
        return self.data_version

    def stamp_derived(self, name: str) -> None:
        """Record which version of the measured data a derived artifact was built from."""
        self.derived_versions[name] = self.data_version

    def derived_is_stale(self, name: str) -> bool:
        """Return whether a derived artifact predates the current measured data."""
        stamped = self.derived_versions.get(name)
        return stamped is not None and stamped < self.data_version

    def stale_artifacts(self) -> list[str]:
        """List every derived artifact built from an older version of the measured data."""
        return sorted(name for name in self.derived_versions if self.derived_is_stale(name))

    def staleness_report(self) -> dict[str, object]:
        """Summarize derived artifacts that no longer match the measured data.

        Included in the responses of the tools that consume derived artifacts, so a stale
        input is visible at the point it is used rather than inferred later.
        """
        stale = self.stale_artifacts()
        report: dict[str, object] = {
            "data_version": self.data_version,
            "stale_artifacts": stale,
        }
        if stale:
            report["warning"] = (
                f"{len(stale)} derived artifact(s) were built from an earlier version of the "
                f"measured data and no longer match it: {', '.join(stale)}. Re-run those stages "
                "before trusting any number that depends on them."
            )
        return report

    def get_measured_iav_pct(self) -> float | None:
        """Return the IAV of the clipping-selected window, when a clipping run exists.

        The uncertainty model's ``u_future`` term is ``iav_pct / sqrt(20)``.  Its
        ``iav_pct`` argument defaults to a generic 6%, and the site's measured value was
        previously only ever displayed — an analyst had to notice it in the clipping view
        and retype it in the ensemble view.  This lets the caller default to the measured
        figure, and to the window actually selected rather than the full series.
        """
        result = self.clipping_result
        if not isinstance(result, dict):
            return None
        for key in ("selected_iav_pct", "iav_pct"):
            value = result.get(key)
            if isinstance(value, (int, float)) and value > 0.0:
                return float(value)
        return None

    def long_term_speed_series(self) -> tuple["pd.Series | None", str]:
        """Return the best available long-term corrected speed series, and where it came from.

        Preference order matches the pipeline: the ensemble blend, then any single LTC
        result, then the measured hub-height column.  Anything quoted against the long-term
        climate — the energy sensitivity factor, the extreme wind — should describe the
        distribution the P-values will actually be quoted against, and every consumer should
        agree about which series that is.
        """
        if self.ensemble_df is not None:
            frame = pd.DataFrame(self.ensemble_df)
            if "Ensemble_Speed" in frame.columns:
                series = frame["Ensemble_Speed"].dropna()
                if not series.empty:
                    return self._timestamped(frame, series), "ensemble"
        for algorithm in sorted(self.ltc_results):
            payload = self.ltc_results.get(algorithm)
            if isinstance(payload, dict) and "df" in payload:
                frame = pd.DataFrame(payload["df"])
                if "corrected_wind_speed" in frame.columns:
                    series = frame["corrected_wind_speed"].dropna()
                    if not series.empty:
                        return self._timestamped(frame, series), f"ltc:{algorithm}"
        hub_height = self.get_hub_height_m()
        if self.timeseries_df is not None and hub_height is not None:
            column = f"Spd_{int(hub_height) if float(hub_height).is_integer() else hub_height}m_hub"
            if column in self.timeseries_df.columns:
                series = self.timeseries_df[column].dropna()
                if not series.empty:
                    return series, f"measured:{column}"
        return None, "unavailable"

    @staticmethod
    def _timestamped(frame: pd.DataFrame, series: pd.Series) -> pd.Series:
        """Attach the frame's Timestamp column as the series index, when it carries one.

        LTC and ensemble results are stored with Timestamp as an ordinary column rather than
        as the index.  A consumer that only needs the distribution can ignore that; one that
        needs to group by year cannot, so the index is restored here rather than in each
        caller.
        """
        if "Timestamp" not in frame.columns:
            return series
        stamps = pd.to_datetime(frame.loc[series.index, "Timestamp"], errors="coerce")
        indexed = series.copy()
        indexed.index = pd.DatetimeIndex(stamps)
        return indexed[indexed.index.notna()]

    def clock_disclosure(self) -> dict[str, object]:
        """Describe which clock hour-of-day bins are counted on, and the site offset (F-02).

        Ingest converts every index to UTC (D8) and nothing converts back, so all
        hour-of-day binning — diurnal profiles, the 12x24 shear and roughness tables, MoMM —
        counts UTC hours.  That is physically self-consistent, because a table and its
        lookup share the clock, and it is why the binning is left alone.  What was wrong is
        that the hours are analyst-facing: a 14:00 local peak at UTC+5:30 was reported at
        08:00 or 09:00 with nothing saying so.

        The offset is reported when the datamodel declared a timezone, so a reader can map
        the reported hour onto site local time.  Where the zone observes DST the offset is
        the standard-time one, which is the clock a logger runs on.
        """
        disclosure: dict[str, object] = {
            "hour_basis": "utc",
            "hour_note": (
                "Hour-of-day bins count UTC hours, not site local time. Bins and lookups "
                "share this clock so the physics is self-consistent, but a diurnal peak "
                "appears at its UTC hour."
            ),
        }
        offset = self.site_utc_offset_hours()
        if offset is not None:
            disclosure["site_utc_offset_hours"] = offset
            disclosure["local_hour_note"] = (
                f"Add {offset:+g} h to a reported hour to read it as site local time."
            )
        else:
            disclosure["site_utc_offset_hours"] = None
            disclosure["local_hour_note"] = (
                "No timezone was declared in the datamodel, so the UTC hours cannot be "
                "mapped to site local time. Declare offset_from_utc_hrs or an IANA zone."
            )
        return disclosure

    def site_utc_offset_hours(self) -> float | None:
        """Return the site's standard-time UTC offset in hours, when a timezone is known."""
        if self.timezone is None:
            return None
        # Midwinter in either hemisphere: probing both and taking the smaller magnitude
        # yields standard time rather than whichever season happens to be summer.
        probes = [datetime(2021, 1, 15, 12), datetime(2021, 7, 15, 12)]
        offsets = []
        for probe in probes:
            try:
                delta = probe.replace(tzinfo=self.timezone).utcoffset()  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None
            if delta is not None:
                offsets.append(delta.total_seconds() / 3600.0)
        if not offsets:
            return None
        return float(min(offsets, key=abs))

    def local_hours_for(self, hours: list[int]) -> list[int] | None:
        """Map UTC hour-of-day bins onto site local hours, when the offset is known."""
        offset = self.site_utc_offset_hours()
        if offset is None:
            return None
        return [int((hour + offset) % 24) for hour in hours]

    def get_shear_min_speed_mps(self, default: float) -> float:
        """Return the shear valid-record speed gate from runconfig, else ``default`` (D3)."""
        shear = self.runconfig.get("shear")
        if isinstance(shear, dict):
            value = shear.get("minSpeedMps")
            if isinstance(value, (int, float)):
                return float(value)
        return float(default)

    def set_shear_min_speed_mps(self, min_speed_mps: float) -> None:
        """Persist the shear speed gate so the value used is reproducible and visible (D3)."""
        shear = self.runconfig.get("shear")
        if not isinstance(shear, dict):
            shear = {}
            self.runconfig["shear"] = shear
        shear["minSpeedMps"] = float(min_speed_mps)
        self.touch()

    def to_runconfig(self) -> dict[str, object]:
        """Serialize current state into a run configuration dictionary for GoKaatru tools."""
        config: dict[str, object] = dict(self.runconfig)
        if "project_name" not in config and self.project_name is not None:
            config["project_name"] = self.project_name
        if "location" not in config and self.coordinate is not None:
            config["location"] = self.coordinate.model_dump()
        if "measurement_type" not in config and self.measurement_type is not None:
            config["measurement_type"] = self.measurement_type
        if "hub_height_m" not in config and self.hub_height_m is not None:
            config["hub_height_m"] = self.hub_height_m
        if self.sensor_mapping:
            config["sensor_mapping"] = {
                str(height): mapping.copy() for height, mapping in self.sensor_mapping.items()
            }
        if self.timezone is not None:
            config.setdefault("site", {})["timezone"] = str(self.timezone)
        excluded = self.runconfig.get("excluded_sensors")
        if isinstance(excluded, list) and excluded:
            config["excluded_sensors"] = [str(name) for name in excluded]
        if self.cleaning_log:
            config["cleaning_log"] = [entry.copy() for entry in self.cleaning_log]
        if self.shear_table is not None:
            config["shear_table_shape"] = list(self.shear_table.shape)
        if self.roughness_table is not None:
            config["roughness_table_shape"] = list(self.roughness_table.shape)
        # Mirrored keys are derived on the frontend from the canonical values
        # above, so they are never persisted. The mapping lives in
        # server/core/runconfig.py (D20) — shared with _normalize_runconfig so
        # the two strippers cannot drift.
        return strip_mirrors(config)

    def get_data_dir(self) -> str:
        """Return the runtime data directory, preferring the session workspace when configured."""
        data_dir = self.workspace_dir if self.workspace_dir is not None else Path("data")
        data_dir.mkdir(parents=True, exist_ok=True)
        return str(data_dir)


_default_session = SessionState()
_bound_session: ContextVar[SessionState | None] = ContextVar("gokaatru_bound_session", default=None)


def get_active_session() -> SessionState:
    """Return the request-bound SessionState when available, else the legacy singleton."""
    state = _bound_session.get()
    return _default_session if state is None else state


@contextmanager
def bind_session(state: SessionState):
    """Bind a managed SessionState to the current execution context for MCP tool calls."""
    token: Token[SessionState | None] = _bound_session.set(state)
    try:
        yield state
    finally:
        _bound_session.reset(token)


class SessionProxy:
    """Proxy the exported `session` object to a request-bound SessionState when present."""

    def __getattr__(self, name: str):
        return getattr(get_active_session(), name)

    def __setattr__(self, name: str, value: object) -> None:
        setattr(get_active_session(), name, value)

    def __delattr__(self, name: str) -> None:
        delattr(get_active_session(), name)

    def __dir__(self) -> list[str]:
        return sorted(set(dir(type(self)) + dir(get_active_session())))

    def __repr__(self) -> str:
        state = get_active_session()
        return f"SessionProxy(session_id={state.session_id!r}, workspace_dir={state.workspace_dir!r})"


session = SessionProxy()
