"""artifacts — the named results operations read and write (decisions/0015.2).

An artifact is a piece of session state with a meaning of its own: the measured records, the
data model, the shear table, the hub-height series, one long-term correction. Operations
declare which they read and which they write; those declarations are the canvas's typed
ports, and the dependencies staleness follows.

Several artifacts share a session field. Extrapolation appends the hub-height series to the
working frame, and carries each reanalysis frame to hub height in place, as columns ending
in ``HUB_COLUMN_SUFFIX``; those columns belong to the hub series, the rest to the measured
records or the reference. Each artifact's ``digest`` reads only its own part, and ``clear``
removes only its own part, which is how ``tests/test_artifacts.py`` holds every declaration to
what the operation does.
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd
from pydantic import BaseModel

from server.core.reanalysis import DEFAULT_REFERENCE_SOURCE
from server.core.runconfig import strip_mirrors
from server.state.session import SessionState, empty_cleaning_flags

#: Extrapolation names a hub-height column ``Spd_<height>m_hub`` (``tools/extrapolation.py``).
HUB_COLUMN_SUFFIX = "_hub"

#: Each long-term correction is its own result, keyed as ``state.ltc_results`` keys it.
LTC_ALGORITHMS: tuple[str, ...] = (
    "linear_least_squares", "total_least_squares", "variance_ratio", "speedsort", "xgboost",
)

#: Run-configuration keys owned by an artifact other than ``settings``. ``sensor_mapping``,
#: ``cleaning_log`` and the table shapes are copies ``SessionState.to_runconfig`` writes from
#: the state they describe, so they belong to that state.
_SITE_KEYS = ("location", "hub_height_m", "measurement_type")
_LABEL_KEYS = ("project_name", "brighthub_uuid", "dataset_id")
_MIRRORED_STATE_KEYS = ("sensor_mapping", "cleaning_log", "shear_table_shape", "roughness_table_shape")


@dataclass(frozen=True)
class Artifact:
    name: str
    description: str
    digest: Callable[[SessionState], str]
    clear: Callable[[SessionState], None]
    #: Built by an analysis step and stamped with ``SessionState.stamp_derived`` under this
    #: name; the others are inputs, configuration and downloads.
    derived: bool = False


def _feed(hasher: Any, value: Any) -> None:
    if value is None:
        hasher.update(b"\x00none")
    elif isinstance(value, pd.DataFrame):
        hasher.update(b"\x00frame")
        hasher.update(repr([(str(name), str(dtype)) for name, dtype in value.dtypes.items()]).encode())
        hasher.update(pd.util.hash_pandas_object(value, index=True).to_numpy().tobytes())
    elif isinstance(value, pd.Series):
        hasher.update(b"\x00series" + str(value.name).encode() + str(value.dtype).encode())
        hasher.update(pd.util.hash_pandas_object(value, index=True).to_numpy().tobytes())
    elif isinstance(value, BaseModel):
        _feed(hasher, value.model_dump())
    elif isinstance(value, dict):
        hasher.update(b"\x00dict")
        for key in sorted(value, key=str):
            _feed(hasher, str(key))
            _feed(hasher, value[key])
    elif isinstance(value, (list, tuple)):
        hasher.update(b"\x00list")
        for item in value:
            _feed(hasher, item)
    elif isinstance(value, (set, frozenset)):
        _feed(hasher, sorted(map(repr, value)))
    else:
        hasher.update(b"\x00" + type(value).__name__.encode() + repr(value).encode())


def digest_of(*parts: Any) -> str:
    """A content hash of session values: frames by their records, containers by their items."""
    hasher = hashlib.sha256()
    for part in parts:
        _feed(hasher, part)
    return hasher.hexdigest()[:16]


def _hub_columns(frame: pd.DataFrame | None) -> list[str]:
    return [] if frame is None else [str(c) for c in frame.columns if str(c).endswith(HUB_COLUMN_SUFFIX)]


def _without_hub(frame: pd.DataFrame | None) -> pd.DataFrame | None:
    return None if frame is None else frame.drop(columns=_hub_columns(frame))


def _only_hub(frame: pd.DataFrame | None) -> pd.DataFrame | None:
    return None if frame is None else frame[_hub_columns(frame)]


def _reanalysis_frames(state: SessionState) -> dict[str, dict[str, pd.DataFrame]]:
    return {
        "era5": state.era5_data or {},
        "merra2": state.merra_data or {},
        "interpolated": state.reanalysis_interpolated or {},
    }


def _keep_hub_columns(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    return {key: frame[_hub_columns(frame)].copy() for key, frame in frames.items() if _hub_columns(frame)}


def _drop_hub_columns(frames: dict[str, pd.DataFrame]) -> None:
    for frame in frames.values():
        frame.drop(columns=_hub_columns(frame), inplace=True)


def _settings(state: SessionState) -> dict[str, Any]:
    return strip_mirrors({key: value for key, value in state.runconfig.items() if key not in _OWNED_KEYS})


#: ``site`` holds the declared timezone and how the data model resolved it, so it belongs to
#: the data model; ``excluded_sensors`` to the measured records it was removed from. The
#: reference source and the shear fit's settings are artifacts of their own: choosing a
#: reference must not make a shear table stale, nor a shear gate a long-term correction.
_OWNED_KEYS = frozenset(
    _SITE_KEYS + _LABEL_KEYS + _MIRRORED_STATE_KEYS + ("excluded_sensors", "site", "reference_source", "shear")
)


# Each clear removes the artifact and nothing else, so a step that does not read it gives
# the same answer without it.


def _clear_measured(state: SessionState) -> None:
    if state.timeseries_df is not None:
        state.timeseries_df = state.timeseries_df[_hub_columns(state.timeseries_df)].copy()
    state.raw_timeseries_df = None
    state.cleaning_log = []
    state.cleaning_flags = empty_cleaning_flags()
    state.removed_sensors = {}
    state.runconfig.pop("excluded_sensors", None)


def _clear_data_model(state: SessionState) -> None:
    state.sensor_mapping = {}
    state.sensor_inventory = {}
    state.timezone = None
    state.datamodel_origin = None
    state.runconfig.pop("site", None)


def _clear_site(state: SessionState) -> None:
    state.coordinate = None
    state.hub_height_m = None
    state.measurement_type = None
    for key in _SITE_KEYS:
        state.runconfig.pop(key, None)


def _clear_label(state: SessionState) -> None:
    state.project_name = None
    for key in _LABEL_KEYS:
        state.runconfig.pop(key, None)


def _clear_settings(state: SessionState) -> None:
    state.runconfig = {key: value for key, value in state.runconfig.items() if key in _OWNED_KEYS}


def _clear_reference_choice(state: SessionState) -> None:
    state.runconfig.pop("reference_source", None)
    state.active_reference_source = DEFAULT_REFERENCE_SOURCE


def _clear_shear_settings(state: SessionState) -> None:
    state.runconfig.pop("shear", None)


def _clear_credentials(state: SessionState) -> None:
    state.brighthub_token = None
    state.earthdatahub_pat = None


def _clear_nodes(state: SessionState) -> None:
    state.era5_nodes = None
    state.merra_nodes = None
    state.era5_data = _keep_hub_columns(state.era5_data or {})
    state.merra_data = _keep_hub_columns(state.merra_data or {})
    state.reanalysis_cache_identity = None


def _clear_reference(state: SessionState) -> None:
    state.reanalysis_interpolated = _keep_hub_columns(state.reanalysis_interpolated or {})


def _clear_reanalysis_hub(state: SessionState) -> None:
    for frames in _reanalysis_frames(state).values():
        _drop_hub_columns(frames)


def _clear_hub(state: SessionState) -> None:
    if state.timeseries_df is not None:
        state.timeseries_df = state.timeseries_df.drop(columns=_hub_columns(state.timeseries_df))


def _ltc(algorithm: str) -> Artifact:
    def clear(state: SessionState) -> None:
        state.ltc_results.pop(algorithm, None)

    return Artifact(
        f"ltc:{algorithm}",
        f"The {algorithm.replace('_', ' ')} long-term correction",
        lambda state: digest_of(state.ltc_results.get(algorithm)),
        clear,
        derived=True,
    )


def _setter(field: str, empty: Callable[[], Any]) -> Callable[[SessionState], None]:
    def clear(state: SessionState) -> None:
        setattr(state, field, empty())

    return clear


def _nulls(*fields: str) -> Callable[[SessionState], None]:
    def clear(state: SessionState) -> None:
        for field in fields:
            setattr(state, field, None)

    return clear


_DECLARED: tuple[Artifact, ...] = (
    Artifact(
        "measured_data",
        "The measured records, raw and working, with the cleaning log and flags",
        lambda s: digest_of(
            _without_hub(s.timeseries_df), s.raw_timeseries_df, s.cleaning_log, s.cleaning_flags,
            s.removed_sensors, s.runconfig.get("excluded_sensors"),
        ),
        _clear_measured,
    ),
    Artifact(
        "data_model",
        "Which column is which instrument at which height, and the records' timezone",
        lambda s: digest_of(
            s.sensor_mapping, s.sensor_inventory, None if s.timezone is None else str(s.timezone),
            s.datamodel_origin, s.runconfig.get("site"),
        ),
        _clear_data_model,
    ),
    Artifact(
        "site",
        "The site's coordinate, the hub height and the measurement type",
        lambda s: digest_of(
            s.coordinate, s.hub_height_m, s.measurement_type, [s.runconfig.get(key) for key in _SITE_KEYS],
        ),
        _clear_site,
    ),
    Artifact(
        "label",
        "The campaign's name and where it was imported from",
        lambda s: digest_of(s.project_name, [s.runconfig.get(key) for key in _LABEL_KEYS]),
        _clear_label,
    ),
    Artifact(
        "settings",
        "The rest of the run configuration: the power curve, timestamp labelling, method settings",
        lambda s: digest_of(_settings(s)),
        _clear_settings,
    ),
    Artifact(
        "reference_choice",
        "Which reanalysis source the long-term corrections use",
        lambda s: digest_of(s.runconfig.get("reference_source"), s.active_reference_source),
        _clear_reference_choice,
    ),
    Artifact(
        "shear_settings",
        "The shear fit's settings, such as its speed gate",
        lambda s: digest_of(s.runconfig.get("shear")),
        _clear_shear_settings,
    ),
    Artifact(
        "credentials",
        "The BrightHub and EarthDataHub logins, held in memory only",
        lambda s: digest_of(s.brighthub_token, s.earthdatahub_pat),
        _clear_credentials,
    ),
    Artifact(
        "selections", "The saved selections", lambda s: digest_of(s.selections), _setter("selections", dict),
    ),
    Artifact(
        "reanalysis_nodes",
        "The reanalysis grid nodes found and downloaded",
        lambda s: digest_of(
            s.era5_nodes, s.merra_nodes,
            {key: _without_hub(frame) for key, frame in (s.era5_data or {}).items()},
            {key: _without_hub(frame) for key, frame in (s.merra_data or {}).items()},
            s.reanalysis_cache_identity,
        ),
        _clear_nodes,
    ),
    Artifact(
        "reference_series",
        "The reanalysis interpolated to the site, for each source",
        lambda s: digest_of({key: _without_hub(frame) for key, frame in (s.reanalysis_interpolated or {}).items()}),
        _clear_reference,
    ),
    Artifact(
        "reanalysis_hub_series",
        "The reanalysis carried to hub height with the shear table",
        lambda s: digest_of(
            {
                group: {key: _only_hub(frame) for key, frame in frames.items() if _hub_columns(frame)}
                for group, frames in _reanalysis_frames(s).items()
            }
        ),
        _clear_reanalysis_hub,
    ),
    Artifact(
        "shear_timeseries",
        "The shear exponent of every record",
        lambda s: digest_of(s.shear_timeseries_df, s.shear_clamp_stats),
        _nulls("shear_timeseries_df", "shear_clamp_stats"),
        derived=True,
    ),
    Artifact(
        "roughness_timeseries",
        "The roughness length of every record",
        lambda s: digest_of(s.roughness_timeseries_df, s.roughness_clip_stats),
        _nulls("roughness_timeseries_df", "roughness_clip_stats"),
        derived=True,
    ),
    Artifact(
        "shear_table", "The month-by-hour shear exponents", lambda s: digest_of(s.shear_table),
        _nulls("shear_table"), derived=True,
    ),
    Artifact(
        "roughness_table", "The month-by-hour roughness lengths", lambda s: digest_of(s.roughness_table),
        _nulls("roughness_table"), derived=True,
    ),
    Artifact(
        "hub_height_series",
        "The measured wind speed carried to hub height",
        lambda s: digest_of(_only_hub(s.timeseries_df)),
        _clear_hub,
        derived=True,
    ),
    Artifact(
        "ltc_matching",
        "How the measured series was aligned with the reference for the latest correction",
        lambda s: digest_of(s.ltc_matching_disclosure),
        _setter("ltc_matching_disclosure", dict),
    ),
    *(_ltc(algorithm) for algorithm in LTC_ALGORITHMS),
    Artifact(
        "ltc_scenarios",
        "Long-term correction scenarios saved by the current interface",
        lambda s: digest_of(s.scenarios),
        _setter("scenarios", list),
    ),
    Artifact(
        "ensemble", "The blend of the long-term corrections", lambda s: digest_of(s.ensemble_df),
        _nulls("ensemble_df"), derived=True,
    ),
    Artifact(
        "clipping", "The selected long-term window and its inter-annual variability",
        lambda s: digest_of(s.clipping_result), _nulls("clipping_result"), derived=True,
    ),
    Artifact(
        "uncertainty", "The uncertainty budget", lambda s: digest_of(s.latest_uncertainty),
        _nulls("latest_uncertainty"), derived=True,
    ),
)

ARTIFACTS: dict[str, Artifact] = {artifact.name: artifact for artifact in _DECLARED}
LTC_ARTIFACTS: tuple[str, ...] = tuple(f"ltc:{algorithm}" for algorithm in LTC_ALGORITHMS)

#: The session fields each artifact lives in. A field shared by several (the working frame,
#: the reanalysis frames, the run configuration) is split between them as their digests say.
ARTIFACT_FIELDS: dict[str, tuple[str, ...]] = {
    "measured_data": (
        "timeseries_df", "raw_timeseries_df", "cleaning_log", "cleaning_flags", "removed_sensors", "runconfig",
    ),
    "data_model": ("sensor_mapping", "sensor_inventory", "timezone", "datamodel_origin", "runconfig"),
    "site": ("coordinate", "hub_height_m", "measurement_type", "runconfig"),
    "label": ("project_name", "runconfig"),
    "settings": ("runconfig",),
    "reference_choice": ("runconfig", "active_reference_source"),
    "shear_settings": ("runconfig",),
    "credentials": ("brighthub_token", "earthdatahub_pat"),
    "selections": ("selections",),
    "reanalysis_nodes": ("era5_nodes", "merra_nodes", "era5_data", "merra_data", "reanalysis_cache_identity"),
    "reference_series": ("reanalysis_interpolated",),
    "reanalysis_hub_series": ("era5_data", "merra_data", "reanalysis_interpolated"),
    "shear_timeseries": ("shear_timeseries_df", "shear_clamp_stats"),
    "roughness_timeseries": ("roughness_timeseries_df", "roughness_clip_stats"),
    "shear_table": ("shear_table",),
    "roughness_table": ("roughness_table",),
    "hub_height_series": ("timeseries_df",),
    "ltc_matching": ("ltc_matching_disclosure",),
    **{name: ("ltc_results",) for name in LTC_ARTIFACTS},
    "ltc_scenarios": ("scenarios",),
    "ensemble": ("ensemble_df",),
    "clipping": ("clipping_result",),
    "uncertainty": ("latest_uncertainty",),
}

#: Session fields no artifact holds, and why: identity, bookkeeping about the other fields,
#: and the current interface's own workflow records.
UNTRACKED_FIELDS: dict[str, str] = {
    "session_id": "identity",
    "workspace_dir": "identity",
    "created_at": "identity",
    "updated_at": "bookkeeping: when the session last changed",
    "project": "identity: the project the campaign belongs to",
    "persist_result_files": "a switch the sweep sets for its own leaves",
    "operation_log": "bookkeeping: the history of calls",
    "undo_stack": "bookkeeping: what was undone",
    "data_version": "bookkeeping: the measured records' version",
    "derived_versions": "bookkeeping: the data version each result was built from",
    "derived_provenance": "bookkeeping: the call that built each result",
    "artifact_clock": "bookkeeping: the clock artifact versions are read from",
    "artifact_versions": "bookkeeping: each artifact's version",
    "derived_inputs": "bookkeeping: the versions each result was built from",
    "executed_nodes": "the current interface's Canvas run state",
    "workflow_execution": "the current interface's Canvas run state",
    "workflow_runs": "the current interface's archived Canvas runs",
}


def fingerprints(state: SessionState) -> dict[str, str]:
    """The digest of every artifact, by name."""
    return {name: artifact.digest(state) for name, artifact in ARTIFACTS.items()}
