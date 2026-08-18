"""data_io — Phase 1 MCP tools for timeseries and datamodel loading.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json
import logging
import re
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from server.core.validators import (
    SENSOR_FIELDS,
    TIMESTAMP_LABEL_CONVENTION,
    TIMESTAMP_LABEL_NOTE,
    detect_timestep_minutes,
)
from server.main import mcp
from server.schemas.common import Coordinate, SensorInfo
from server.state.session import SessionState, session

logger = logging.getLogger(__name__)

TIMESTAMP_CANDIDATES = [
    "Timestamp", "timestamp", "TIMESTAMP",
    "DateTime", "datetime", "DateTime (UTC)",
    "Date/Time", "Date", "date",
    "Time", "time",
    "TmStamp",
]

# A year-first date is ISO 8601 and unambiguous; only day/month-first formats can swap.
_ISO_DATE_PREFIX = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}")

# Epoch-second range for plausible wind-campaign data (1990-01-01 .. 2050-01-01).
_EPOCH_SECOND_MIN = 631_152_000.0
_EPOCH_SECOND_MAX = 2_524_608_000.0
CANONICAL_SENSOR_TYPES = {
    "air_temperature": "temperature",
    "air_pressure": "pressure",
    "relative_humidity": "humidity",
}


def _resolve_duplicate_timestamps(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    """Collapse repeated timestamps to one record each, and report what was collapsed.

    Loggers produce duplicates routinely - a restart, an overlapping export, a manual file
    concatenation - and ingest sorted the index without ever checking for them (F-65). The
    duplicate survived into ``timeseries_df``, so every downstream ``groupby`` over the
    index (MoMM, diurnal profiles, monthly statistics, coverage) counted that interval
    twice. The cadence detector could not catch it either, because zero diffs are filtered
    out before the modal spacing is taken.

    Duplicates are averaged rather than dropped: where the repeats disagree, neither copy
    has a better claim than the other, and the mean is the only choice that does not depend
    on file order. Identical repeats are unaffected by that either way.
    """
    index = pd.DatetimeIndex(frame.index)
    duplicated = index.duplicated(keep=False)
    if not bool(duplicated.any()):
        return frame, {"duplicate_timestamps": 0}
    affected_index = index[duplicated]
    distinct = int(pd.Index(affected_index).nunique())
    collapsed = frame.groupby(level=0).mean(numeric_only=True)
    # Non-numeric columns cannot be averaged; keep the first record for those.
    non_numeric = [column for column in frame.columns if column not in collapsed.columns]
    if non_numeric:
        collapsed = collapsed.join(frame[non_numeric].groupby(level=0).first())
        collapsed = collapsed[[column for column in frame.columns if column in collapsed.columns]]
    removed = int(len(frame) - len(collapsed))
    return collapsed.sort_index(), {
        "duplicate_timestamps": removed,
        "duplicate_timestamps_distinct": distinct,
        "duplicate_resolution": "averaged",
        "warning": (
            f"{removed:,} duplicate timestamp record(s) across {distinct:,} distinct "
            "timestamps were collapsed by averaging. Duplicates usually mean a logger "
            "restart or an overlapping export; left in place they would have been counted "
            "twice by every month-hour grouping downstream."
        ),
    }


def _extract_boom_orientation(point: dict[str, object]) -> float | None:
    """Read the boom bearing from a Task 43 measurement point, if it declares one.

    Task 43 records this under ``mounting_arrangement``; some exports flatten it onto the
    point itself.  Both are accepted.  The value matters because the tower sits opposite
    the boom, so it is the only recorded geometry that says where the shadow actually
    falls — previously nothing read it and the tower-shadow rule fell back to a fixed
    20-degree guess (F-71).
    """
    direct = _first_numeric(point, ["boom_orientation_deg", "boom_orientation"])
    if direct is not None:
        return direct % 360.0
    arrangements = point.get("mounting_arrangement")
    if isinstance(arrangements, dict):
        arrangements = [arrangements]
    if isinstance(arrangements, list):
        for arrangement in arrangements:
            if not isinstance(arrangement, dict):
                continue
            value = _first_numeric(arrangement, ["boom_orientation_deg", "boom_orientation"])
            if value is not None:
                return value % 360.0
    return None


def _build_sensor_inventory(points: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    """Capture every named Task 43 measurement point for inventory presentation."""
    inventory: dict[str, dict[str, object]] = {}
    for point in points:
        sensor_name = point.get("name")
        height_m = _coerce_float(point.get("height_m"))
        sensor_type = str(point.get("measurement_type_id", "")).strip()
        if not isinstance(sensor_name, str) or not sensor_name.strip() or height_m is None:
            continue
        entry: dict[str, object] = {
            "height_m": height_m,
            "sensor_type": CANONICAL_SENSOR_TYPES.get(sensor_type, sensor_type or "unknown"),
        }
        boom_orientation = _extract_boom_orientation(point)
        if boom_orientation is not None:
            entry["boom_orientation_deg"] = boom_orientation
        inventory[sensor_name] = entry
    return inventory


def _confined_file_path(state: SessionState, filename: str, subdir: str = "") -> Path:
    """Resolve *filename* within the session data directory, rejecting traversal.

    Mirrors the ``windkit_file_path`` pattern: resolve the base, then join +
    resolve the candidate and verify containment via ``is_relative_to``.
    Absolute paths are accepted only if they resolve inside the base directory.
    """
    base = Path(state.get_data_dir())
    if subdir:
        base = (base / subdir).resolve()
    else:
        base = base.resolve()
    base.mkdir(parents=True, exist_ok=True)
    candidate = Path(filename)
    if candidate.is_absolute():
        path = candidate.resolve()
    else:
        path = (base / candidate).resolve()
    if not path.is_relative_to(base):
        raise ValueError("Input file is not available")
    return path


def _read_tabular_file(state: SessionState, file_path: str) -> pd.DataFrame:
    """Load CSV, TSV, or Excel input according to the GoKaatru Phase 1 file-ingest spec."""
    try:
        path = _confined_file_path(state, file_path, subdir="uploads")
    except (OSError, RuntimeError) as exc:
        raise ValueError("Input file is not available") from exc
    if not path.exists():
        raise ValueError("Input file is not available")
    if not path.is_file():
        raise ValueError("Input file is not available")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".tsv", ".txt"}:
        return pd.read_csv(path, sep="\t")
    if suffix in {".xls", ".xlsx"}:
        return pd.read_excel(path)
    raise ValueError("Input file is not available")


def _to_datetime(column: pd.Series, dayfirst: bool) -> pd.Series:
    """Parse a column at one fixed day/month order, without pandas' inference warning."""
    with warnings.catch_warnings():
        # pandas warns when its inferred order disagrees with `dayfirst`; that disagreement
        # is what the checks here are measuring, so it is not news.
        warnings.simplefilter("ignore", UserWarning)
        return pd.to_datetime(column, errors="coerce", dayfirst=dayfirst)


def _parse_datetime_column(column: pd.Series, dayfirst: bool | None) -> pd.Series:
    """Parse one candidate column, honouring a declared day/month order.

    ``dayfirst=None`` means undeclared, in which case the order the **data determines** is
    used: a column containing any day above 12 parses more rows one way than the other, and
    the reading that parses more rows is the right one.  Previously the default order was
    taken regardless, so a DD/MM column with days up to 25 lost more than half its rows to
    coercion and was discarded as "not a timestamp column" without ever saying why.

    Where neither order parses more rows the column is genuinely ambiguous, and
    :func:`_date_order_is_ambiguous` refuses it rather than guessing.
    """
    if dayfirst is not None:
        return _to_datetime(column, dayfirst)
    month_first = _to_datetime(column, False)
    day_first = _to_datetime(column, True)
    if int(day_first.notna().sum()) > int(month_first.notna().sum()):
        return day_first
    return month_first


def _date_order_is_ambiguous(column: pd.Series) -> bool:
    """Return True when a column parses equally well as DD/MM and as MM/DD (F-67).

    ``pd.to_datetime`` with no ``dayfirst`` and no format reads ``01/03/2021`` as 3 January.
    A DD/MM/YYYY column whose days all fall on or below 12 therefore parses **100%
    successfully** with day and month transposed, and a 12-day March campaign becomes a
    series spanning January to December.

    The audit recorded this as caught incidentally by the cadence whitelist. Measured, it is
    not caught at all for the most common data shape: a 12-day March campaign at 10-minute
    cadence keeps a 10-minute modal spacing after the swap, because the spacing *within* each
    day is untouched. Only the span changes, from 12 days to 12 months, and nothing checks
    the span.

    Ambiguity means both readings are equally valid: they parse the same number of rows and
    disagree about at least one of them. A column containing any day above 12 is determined
    by the data - one reading produces more failures - and is not ambiguous.
    """
    # pandas 3 gives strings their own dtype, so `is_object_dtype` is not the test here.
    # What matters is that the column is textual: a numeric or already-datetime column has
    # no day/month order to confuse.
    if pd.api.types.is_numeric_dtype(column) or pd.api.types.is_datetime64_any_dtype(column):
        return False
    month_first = _to_datetime(column, False)
    day_first = _to_datetime(column, True)

    # ISO 8601 puts the year first and is unambiguous by definition. pandas nevertheless
    # honours `dayfirst` on it — `2021-01-02` becomes 1 February — so year-first values have
    # to be excluded here or every ISO campaign would be refused.
    #
    # Only rows that actually parse are examined: a Campbell logger file carries occasional
    # junk rows ("BAD", "NAN"), and judging the format on those would let two bad rows in a
    # thousand defeat the check.
    parseable = column[month_first.notna() | day_first.notna()]
    text = parseable.dropna().astype(str).str.strip()
    if text.empty:
        return False
    if bool(text.str.match(_ISO_DATE_PREFIX).all()):
        return False
    if int(month_first.notna().sum()) != int(day_first.notna().sum()):
        return False
    both_valid = month_first.notna() & day_first.notna()
    if not bool(both_valid.any()):
        return False
    return bool((month_first[both_valid] != day_first[both_valid]).any())


def _detect_timestamp_column(df: pd.DataFrame, dayfirst: bool | None = None) -> tuple[str, pd.Series]:
    """Select the timestamp column with the most valid parses per the Phase 1 ingestion rule.

    Hardening (D6): skip numeric columns unless their range is plausible for
    epoch seconds, require valid-parse fraction >= 0.5 and a sane span
    (> 1 day, < 100 years), and match candidate names case-insensitively.
    """
    # Priority 1: exact name match
    exact = [column for column in TIMESTAMP_CANDIDATES if column in df.columns]
    # Priority 2: case-insensitive match against candidate set
    ci_lower = {c.lower() for c in TIMESTAMP_CANDIDATES}
    ci_match = [col for col in df.columns if col not in exact and col.lower() in ci_lower]
    # Priority 3: all remaining columns (scored below)
    candidates = exact + ci_match if (exact or ci_match) else list(df.columns)

    best_name = ""
    best_series = pd.Series(dtype="datetime64[ns]")
    best_count = -1
    named_candidates = set(exact + ci_match)
    for column in candidates:
        # Skip numeric-dtype columns unless values are plausible epoch seconds.
        if pd.api.types.is_numeric_dtype(df[column]):
            col_min = float(df[column].min())
            col_max = float(df[column].max())
            if not (col_min >= _EPOCH_SECOND_MIN and col_max <= _EPOCH_SECOND_MAX):
                continue

        parsed = _parse_datetime_column(df[column], dayfirst)
        valid_count = int(parsed.notna().sum())
        n_rows = len(df[column])
        if n_rows == 0:
            continue
        fraction = valid_count / n_rows
        if fraction < 0.5:
            continue
        # Span check: name-matched candidates are trusted (exact or
        # case-insensitive), but scored fallback columns must demonstrate a
        # plausible temporal range to guard against numeric false-positives.
        if column not in named_candidates:
            span = parsed.max() - parsed.min()
            if pd.isna(span) or span <= pd.Timedelta(days=1) or span > pd.Timedelta(days=36500):
                continue

        if valid_count > best_count:
            best_name = str(column)
            best_series = parsed
            best_count = valid_count

    if best_count <= 0:
        raise ValueError("Could not detect a timestamp column with any valid datetime values")
    if dayfirst is None and _date_order_is_ambiguous(df[best_name]):
        raise ValueError(
            f"Timestamp column '{best_name}' is ambiguous: every date parses equally well as "
            "DD/MM/YYYY and as MM/DD/YYYY, because no day exceeds 12. Reading it the wrong "
            "way round silently relabels the campaign - a 12-day March campaign becomes a "
            "series spanning January to December, at an unchanged 10-minute cadence, so "
            "nothing downstream detects it. Set 'dayfirst' true or false on the run "
            "configuration, or supply ISO-8601 timestamps."
        )
    return best_name, best_series


def _format_timestamp(value: pd.Timestamp) -> str:
    """Format timestamps consistently for Phase 1 tool responses."""
    return pd.Timestamp(value).isoformat()


def _extract_measurement_points(node: object) -> list[dict[str, object]]:
    """Recursively collect Task 43 measurement_point records from a JSON tree."""
    if isinstance(node, dict):
        points = node.get("measurement_point", [])
        collected = [item for item in points if isinstance(item, dict)]
        for value in node.values():
            collected.extend(_extract_measurement_points(value))
        return collected
    if isinstance(node, list):
        collected: list[dict[str, object]] = []
        for item in node:
            collected.extend(_extract_measurement_points(item))
        return collected
    return []


def _extract_measurement_locations(node: object) -> list[dict[str, object]]:
    """Recursively collect Task 43 measurement_location records from a JSON tree."""
    if isinstance(node, dict):
        locations = node.get("measurement_location", [])
        collected = [item for item in locations if isinstance(item, dict)]
        for value in node.values():
            collected.extend(_extract_measurement_locations(value))
        return collected
    if isinstance(node, list):
        collected: list[dict[str, object]] = []
        for item in node:
            collected.extend(_extract_measurement_locations(item))
        return collected
    return []


def _coerce_float(value: object) -> float | None:
    """Convert numeric-like datamodel fields into floats when possible."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _first_numeric(record: dict[str, object], keys: list[str]) -> float | None:
    """Return the first numeric value found among the provided datamodel keys."""
    for key in keys:
        value = _coerce_float(record.get(key))
        if value is not None:
            return value
    return None


def _normalize_measurement_type(value: object) -> str | None:
    """Map Task 43 station types onto the workflow UI's measurement-type choices."""
    if not isinstance(value, str):
        return None
    lowered = value.strip().lower()
    if not lowered:
        return None
    if "lidar" in lowered:
        return "lidar"
    if "sodar" in lowered:
        return "sodar"
    if "mast" in lowered or "tower" in lowered:
        return "mast"
    return None


def _extract_site_metadata(payload: object) -> dict[str, object]:
    """Extract project and location metadata from an IEA Task 43 datamodel when present."""
    locations = _extract_measurement_locations(payload)
    if not locations:
        return {}
    record = locations[0]
    metadata: dict[str, object] = {}
    project_name = record.get("name")
    if isinstance(project_name, str) and project_name.strip():
        metadata["project_name"] = project_name.strip()
    latitude = _first_numeric(record, ["latitude_ddeg", "latitude", "lat"])
    longitude = _first_numeric(record, ["longitude_ddeg", "longitude", "lon"])
    elevation = _first_numeric(record, ["elevation_m", "elevation", "elevation_amsl_m", "elevation_asl_m"])
    if latitude is not None and longitude is not None:
        metadata["coordinate"] = Coordinate(latitude=latitude, longitude=longitude, elevation_m=elevation or 0.0)
    measurement_type = _normalize_measurement_type(
        record.get("measurement_station_type_id") or record.get("measurement_type_id") or record.get("measurement_type")
    )
    if measurement_type is not None:
        metadata["measurement_type"] = measurement_type
    return metadata


def _extract_timezone(payload: object) -> tuple[str, object]:
    """Extract timezone from an IEA Task 43 datamodel.

    Returns ``(source_field, tz_object)``.  Supports an IANA timezone name
    (keys ``timezone``, ``time_zone_id``, ``timezone_id``) or the Task 43
    integer offset ``offset_from_utc_hrs`` in ``logger_main_config``.
    Raises ``ValueError`` when no timezone is declared.
    """
    try:
        import zoneinfo
    except ImportError:
        zoneinfo = None  # type: ignore[assignment]

    locations = _extract_measurement_locations(payload)
    for location in locations:
        for iana_key in ("timezone", "time_zone_id", "timezone_id"):
            iana_value = location.get(iana_key)
            if isinstance(iana_value, str) and iana_value.strip():
                if zoneinfo is not None:
                    try:
                        return iana_key, zoneinfo.ZoneInfo(iana_value.strip())
                    except (zoneinfo.ZoneInfoNotFoundError, KeyError):
                        continue
        # Fall back to logger_main_config offset
        configs = location.get("logger_main_config", [])
        for config in configs:
            if not isinstance(config, dict):
                continue
            offset_val = config.get("offset_from_utc_hrs")
            if isinstance(offset_val, (int, float)):
                return "offset_from_utc_hrs", timezone(timedelta(hours=float(offset_val)))
            if isinstance(offset_val, str) and offset_val.strip():
                try:
                    return "offset_from_utc_hrs", timezone(timedelta(hours=float(offset_val.strip())))
                except ValueError:
                    continue
    raise ValueError(
        "Datamodel does not declare a timezone. Expected 'timezone' (IANA) "
        "or 'offset_from_utc_hrs' in logger_main_config."
    )


_DST_ERROR_MARKERS = ("infer dst", "ambiguous", "nonexistent")


def _is_dst_localization_error(exc: Exception) -> bool:
    """Return whether a localisation ValueError is a daylight-saving transition problem."""
    message = str(exc).lower()
    return any(marker in message for marker in _DST_ERROR_MARKERS)


def _standard_time_offset(tz: object) -> timezone | None:
    """Return a zone's non-DST (standard-time) offset as a fixed-offset timezone.

    Probes midwinter and midsummer and takes whichever has no DST component, so it works
    in either hemisphere.  Returns ``None`` for a zone that never leaves DST or that
    cannot be probed.
    """
    for probe in (datetime(2021, 1, 15, 12), datetime(2021, 7, 15, 12)):
        try:
            localized = probe.replace(tzinfo=tz)  # type: ignore[arg-type]
            dst_offset = localized.dst()
            utc_offset = localized.utcoffset()
        except (TypeError, ValueError):
            return None
        if dst_offset is not None and dst_offset == timedelta(0) and utc_offset is not None:
            return timezone(utc_offset)
    return None


def _apply_timezone_to_index(state: SessionState, tz: object) -> dict[str, object]:
    """Convert session timeseries indexes from naive local time to tz-aware UTC.

    A DST-observing IANA zone used to make the campaign unimportable: pandas defaults to
    ``ambiguous="raise"`` and ``nonexistent="raise"``, so any record spanning either
    transition raised — which is every campaign of useful length in Europe, most of North
    America, Australia, New Zealand and Chile.  The message advised passing a pandas
    keyword the analyst cannot reach from a file upload.

    Strict localisation is still attempted first, because when it succeeds the timestamps
    are unambiguous and nothing should be inferred.  When it fails, the fallback is the
    zone's **standard-time** offset: a logger clock almost always runs on fixed local
    standard time rather than following DST, and a campaign that *occupies* the
    spring-forward gap is direct evidence of exactly that.  The choice is returned and
    recorded rather than made silently, and an explicit ``offset_from_utc_hrs`` in the
    datamodel still avoids the question entirely.
    """
    frames = [
        (attr, getattr(state, attr))
        for attr in ("timeseries_df", "raw_timeseries_df")
    ]
    pending = [
        (attr, df)
        for attr, df in frames
        if df is not None and isinstance(df.index, pd.DatetimeIndex) and df.index.tz is None
    ]
    if not pending:
        return {"timezone_resolution": "already_aware"}

    try:
        for attr, df in pending:
            df.index = df.index.tz_localize(tz).tz_convert("UTC")
        return {"timezone_resolution": "strict"}
    except ValueError as exc:
        # pandas 3 raises a bare ValueError for both DST cases rather than the dedicated
        # AmbiguousTimeError / NonExistentTimeError of earlier versions, so discriminate
        # on the message and let anything else propagate untouched.
        if not _is_dst_localization_error(exc):
            raise
        standard = _standard_time_offset(tz)
        if standard is None:
            raise ValueError(
                f"Timestamps cannot be localized to '{tz}' and no standard-time offset "
                "could be derived for it. Declare 'offset_from_utc_hrs' in "
                "logger_main_config to state the logger's fixed offset directly."
            ) from exc
        for attr, df in pending:
            # Re-read: a partially localized frame may already be tz-aware.
            current = getattr(state, attr)
            if isinstance(current.index, pd.DatetimeIndex) and current.index.tz is None:
                current.index = current.index.tz_localize(standard).tz_convert("UTC")
        offset_hours = standard.utcoffset(None).total_seconds() / 3600.0
        return {
            "timezone_resolution": "standard_offset",
            "timezone_requested": str(tz),
            "standard_offset_hours": offset_hours,
            "warning": (
                f"Timestamps span a daylight-saving transition in '{tz}', so they cannot be "
                f"localized unambiguously. They have been read as fixed local standard time "
                f"(UTC{offset_hours:+g}), which is how logger clocks normally run. If this "
                "campaign really was recorded on a DST-shifting clock, declare "
                "'offset_from_utc_hrs' in logger_main_config to state the intended offset."
            ),
        }


def _resolve_boom_pair(
    candidates: list[tuple[str, dict[str, object]]],
    timeseries_df: pd.DataFrame | None = None,
) -> tuple[str, str]:
    """Resolve a boom-pair conflict at a single height and field.

    Resolution priority:
    1. ``is_primary`` / ``primary`` flag (exactly one must be True)
    2. Highest non-null coverage in the timeseries DataFrame
    3. Alphabetical sensor name (deterministic tie-break)

    Returns (chosen_name, resolution_method).
    """
    # 1. Check for primary flag
    primary = [name for name, meta in candidates if meta.get("is_primary") is True]
    if len(primary) == 1:
        return primary[0], "primary_flag"

    # 2. Coverage-based fallback (requires timeseries)
    if timeseries_df is not None:
        best_name = ""
        best_count = -1
        for name, _ in candidates:
            if name in timeseries_df.columns:
                count = int(timeseries_df[name].notna().sum())
            else:
                count = -1
            if count > best_count:
                best_count = count
                best_name = name
        if best_name:
            return best_name, "coverage"

    # 3. Alphabetical name tie-break
    sorted_names = sorted(name for name, _ in candidates)
    return sorted_names[0], "name_alphabetical"


def _build_sensor_mapping(
    points: list[dict[str, object]],
    timeseries_df: pd.DataFrame | None = None,
) -> tuple[dict[float, dict[str, str | None]], list[dict[str, object]]]:
    """Map Task 43 measurement points to height-indexed sensor columns per the Phase 1 schema.

    Boom-pair fix (D7): all sensors per height are collected, then resolved
    deterministically via ``_resolve_boom_pair``.  The output type remains
    ``dict[float, dict[str, str | None]]`` for backward compatibility with
    all consumers (shear, extrapolation, statistics, cleaning, etc.).

    Returns (mapping, resolution_log) where resolution_log records any
    boom-pair resolutions for runconfig auditability.
    """
    type_to_field = {
        "wind_speed": "speed_col",
        "wind_direction": "dir_col",
        "temperature": "temp_col",
        "air_temperature": "temp_col",
        "pressure": "pressure_col",
        "air_pressure": "pressure_col",
        "relative_humidity": "humidity_col",
    }

    # Phase 1: collect ALL candidates per height (name-keyed)
    candidates: dict[float, list[tuple[str, dict[str, object]]]] = {}
    for point in points:
        height_value = point.get("height_m")
        sensor_name = point.get("name")
        sensor_type = type_to_field.get(str(point.get("measurement_type_id", "")))
        if not isinstance(height_value, (int, float)) or not isinstance(sensor_name, str) or sensor_type is None:
            continue
        is_primary = point.get("is_primary") or point.get("primary")
        candidates.setdefault(float(height_value), []).append(
            (sensor_name, {"sensor_type": sensor_type, "is_primary": is_primary, **point})
        )

    # Phase 2: build height-keyed mapping, resolving boom pairs
    mapping: dict[float, dict[str, str | None]] = {}
    resolution_log: list[dict[str, object]] = []

    for height, sensors in candidates.items():
        # Group sensors by field type within this height
        by_type: dict[str, list[tuple[str, dict[str, object]]]] = {}
        for name, meta in sensors:
            field = meta["sensor_type"]
            by_type.setdefault(field, []).append((name, meta))

        slots: dict[str, str | None] = {
            "speed_col": None,
            "dir_col": None,
            "sd_col": None,
            "temp_col": None,
            "pressure_col": None,
            "humidity_col": None,
        }
        for field, field_sensors in by_type.items():
            if len(field_sensors) == 1:
                chosen_name = field_sensors[0][0]
            else:
                chosen_name, method = _resolve_boom_pair(field_sensors, timeseries_df)
                resolution_log.append({
                    "height_m": height,
                    "field": field,
                    "candidates": [name for name, _ in field_sensors],
                    "chosen": chosen_name,
                    "resolution": method,
                })
                if method == "name_alphabetical":
                    logger.warning(
                        "Boom-pair at %.1fm (%s): no primary flag and no timeseries "
                        "coverage data; resolved alphabetically to '%s'",
                        height,
                        field,
                        chosen_name,
                    )
            slots[field] = chosen_name
            if field == "speed_col":
                slots["sd_col"] = f"{chosen_name}_sd"
        if slots.get("speed_col") is not None:
            mapping[height] = slots
    return mapping, resolution_log


def _build_sensor_rows(state: SessionState, require_mapping: bool) -> list[dict[str, object]]:
    """Build sensor inventory rows using session mapping rules from the Phase 1 data inventory spec."""
    if state.timeseries_df is None:
        raise ValueError("Timeseries data is not loaded")
    if require_mapping and not state.sensor_mapping:
        raise ValueError("Sensor mapping is not loaded. Run parse_datamodel first")
    sensors: list[dict[str, object]] = []
    total_rows = len(state.timeseries_df)
    if state.sensor_inventory:
        for name, metadata in state.sensor_inventory.items():
            if name not in state.timeseries_df.columns:
                continue
            series = state.timeseries_df[name]
            coverage = 0.0 if total_rows == 0 else float(series.notna().sum() / total_rows * 100.0)
            sensors.append(
                SensorInfo(
                    name=name,
                    height_m=float(metadata["height_m"]),
                    sensor_type=str(metadata["sensor_type"]),
                    data_coverage_pct=coverage,
                    record_count=int(series.notna().sum()),
                ).model_dump()
            )
        sensors.sort(key=lambda sensor: (-float(sensor["height_m"]), str(sensor["name"])))
        return sensors

    for height, mapping in sorted(state.sensor_mapping.items(), reverse=True):
        for field_name, sensor_type in SENSOR_FIELDS.items():
            column_name = mapping.get(field_name)
            if column_name is None or column_name not in state.timeseries_df.columns:
                continue
            series = state.timeseries_df[column_name]
            coverage = 0.0 if total_rows == 0 else float(series.notna().sum() / total_rows * 100.0)
            sensor = SensorInfo(
                name=column_name,
                height_m=height,
                sensor_type=sensor_type,
                data_coverage_pct=coverage,
                record_count=int(series.notna().sum()),
            )
            sensors.append(sensor.model_dump())
    # Include extrapolated hub-height columns (Spd_*m_hub) not already in sensor_mapping.
    known_names = {s["name"] for s in sensors}
    hub_pattern = re.compile(r"^Spd_(\d+(?:\.\d+)?)m_hub$")
    for col in state.timeseries_df.columns:
        if col in known_names:
            continue
        m = hub_pattern.match(col)
        if m:
            hub_h = float(m.group(1))
            series = state.timeseries_df[col]
            coverage = 0.0 if total_rows == 0 else float(series.notna().sum() / total_rows * 100.0)
            sensors.append(SensorInfo(
                name=col,
                height_m=hub_h,
                sensor_type="wind_speed",
                data_coverage_pct=coverage,
                record_count=int(series.notna().sum()),
            ).model_dump())

    if require_mapping or sensors:
        return sensors

    # Fallback inventory for timeseries-only sessions where parse_datamodel has not run yet.
    inferred: list[dict[str, object]] = []
    height_pattern = re.compile(r"_(\d+(?:\.\d+)?)m(?:_|$)", flags=re.IGNORECASE)
    for col in state.timeseries_df.columns:
        series = state.timeseries_df[col]
        coverage = 0.0 if total_rows == 0 else float(series.notna().sum() / total_rows * 100.0)
        lowered = col.lower()
        if lowered.startswith("spd_"):
            sensor_type = "wind_speed"
        elif lowered.startswith("dir_"):
            sensor_type = "wind_direction"
        elif lowered.startswith("temp_") or lowered.startswith("tmp_"):
            sensor_type = "temperature"
        elif lowered.startswith("pres_") or lowered.startswith("pressure_"):
            sensor_type = "pressure"
        else:
            sensor_type = "unknown"

        match = height_pattern.search(col)
        height_m = float(match.group(1)) if match else 0.0

        inferred.append(
            SensorInfo(
                name=col,
                height_m=height_m,
                sensor_type=sensor_type,
                data_coverage_pct=coverage,
                record_count=int(series.notna().sum()),
            ).model_dump()
        )

    inferred.sort(key=lambda item: (-float(item.get("height_m", 0.0)), str(item.get("name", ""))))
    return inferred


def _gap_lengths_in_minutes(series: pd.Series, timestep_minutes: int) -> list[int]:
    """Measure contiguous missing-data gap lengths in minutes using the inferred Phase 1 timestep."""
    missing = series.isna()
    groups = missing.ne(missing.shift(fill_value=False)).cumsum()
    gap_sizes = missing.groupby(groups).sum()
    return [int(size * timestep_minutes) for size in gap_sizes[gap_sizes > 0].tolist()]


def _cadence_aligned_series(series: pd.Series, timestep_minutes: int) -> pd.Series:
    """Reindex a series on its dominant timestamp phase, tolerating small logger clock offsets."""
    if series.empty:
        return series
    frequency_ns = int(pd.Timedelta(minutes=timestep_minutes).value)
    origin_ns = int(pd.Timestamp("1970-01-01").value)
    index_ns = series.index.to_numpy(dtype="datetime64[ns]").astype("int64")
    phases = pd.Series((index_ns - origin_ns) % frequency_ns)
    phase_ns = int(phases.mode().iloc[0])
    relative_start = int(index_ns.min()) - origin_ns - phase_ns
    relative_end = int(index_ns.max()) - origin_ns - phase_ns
    start_step = -(-relative_start // frequency_ns)
    end_step = relative_end // frequency_ns
    expected_ns = origin_ns + phase_ns + np.arange(start_step, end_step + 1, dtype=np.int64) * frequency_ns
    expected_index = pd.DatetimeIndex(expected_ns)

    nearest_steps = np.rint((index_ns - origin_ns - phase_ns) / frequency_ns).astype(np.int64)
    normalized_ns = origin_ns + phase_ns + nearest_steps * frequency_ns
    tolerance_ns = frequency_ns // 4
    on_cadence = np.abs(index_ns - normalized_ns) <= tolerance_ns
    normalized = series.loc[on_cadence].copy()
    normalized.index = pd.DatetimeIndex(normalized_ns[on_cadence])
    normalized = normalized[~normalized.index.duplicated(keep="last")]
    return normalized.reindex(expected_index)


def _parse_timeseries(state: SessionState, file_path: str) -> dict:
    """Parse a wind timeseries file into session state following the GoKaatru Phase 1 ingest spec."""
    source_df = _read_tabular_file(state, file_path)
    # F-67: an ambiguous DD/MM column is refused unless the run configuration declares the
    # order, because reading it the wrong way round is silent and undetectable downstream.
    declared = state.runconfig.get("dayfirst")
    dayfirst = bool(declared) if isinstance(declared, bool) else None
    timestamp_column, parsed_timestamps = _detect_timestamp_column(source_df, dayfirst)
    filtered_df = source_df.loc[parsed_timestamps.notna()].copy()
    filtered_df.index = pd.DatetimeIndex(parsed_timestamps.loc[parsed_timestamps.notna()])
    filtered_df = filtered_df.drop(columns=[timestamp_column]).sort_index()
    if filtered_df.empty:
        raise ValueError("Parsed timeseries is empty after timestamp detection")
    filtered_df, duplicate_report = _resolve_duplicate_timestamps(filtered_df)
    state.timeseries_df = filtered_df.copy()
    state.raw_timeseries_df = filtered_df.copy(deep=True)
    state.bump_data_version()
    # If the datamodel was imported first and set a timezone, immediately
    # convert the naive local-time index to tz-aware UTC (D8).
    if state.timezone is not None:
        _apply_timezone_to_index(state, state.timezone)
    # A new timeseries is a fresh dataset: any previously persisted sensor
    # selection no longer applies, so drop it. Importing a new dataset (or
    # re-importing from BrightHub) is how the user restores excluded sensors.
    state.runconfig.pop("excluded_sensors", None)
    timestep_minutes = detect_timestep_minutes(filtered_df)
    return {
        "status": "ok",
        "rows": int(len(filtered_df)),
        "columns": filtered_df.columns.tolist(),
        "start": _format_timestamp(filtered_df.index.min()),
        "end": _format_timestamp(filtered_df.index.max()),
        "timestep_minutes": timestep_minutes,
        **duplicate_report,
        # F-07: interval-labelling is a convention the file does not carry and the
        # pipeline cannot infer, so it is declared rather than assumed silently.
        "timestamp_label": TIMESTAMP_LABEL_CONVENTION,
        "timestamp_label_basis": "assumed",
        "timestamp_label_note": TIMESTAMP_LABEL_NOTE,
        "timestamp_column": timestamp_column,
        "date_order": "day_first" if dayfirst else ("month_first" if dayfirst is False else "unambiguous"),
        "date_order_basis": "runconfig" if dayfirst is not None else "inferred",
    }


def _prune_sensor_mapping(state: SessionState) -> None:
    """Drop mapping heights whose speed column is absent from the working dataframe."""
    if state.timeseries_df is None:
        return
    state.sensor_mapping = {
        height: sensor_map
        for height, sensor_map in state.sensor_mapping.items()
        if sensor_map.get("speed_col") in state.timeseries_df.columns
    }


def _apply_sensor_exclusions(state: SessionState) -> None:
    """Re-apply the persisted sensor exclusion list after a (re)import.

    The user's sensor selection is authoritative: ``excluded_sensors`` in the
    runconfig records every sensor removed via the selection UI. Any full
    re-import of a datamodel rebuilds the complete inventory, so this helper
    trims it back to the persisted selection. ``excluded_sensors`` is cleared
    whenever a *new* timeseries is ingested, so this is a no-op for fresh
    datasets and only constrains datamodel-only re-imports of the same data.
    """
    excluded = state.runconfig.get("excluded_sensors")
    if not isinstance(excluded, list) or not excluded:
        return
    excluded_names = {str(name) for name in excluded}
    for name in list(state.sensor_inventory):
        if name in excluded_names:
            state.sensor_inventory.pop(name, None)
    for height, slots in list(state.sensor_mapping.items()):
        for slot, column in list(slots.items()):
            if column in excluded_names:
                slots[slot] = None
        if all(value is None for value in slots.values()):
            del state.sensor_mapping[height]
    # Excluded sensors must not survive in the working data either.
    for frame_attr in ("timeseries_df", "raw_timeseries_df"):
        frame = getattr(state, frame_attr)
        if frame is not None:
            drop_cols = [column for column in frame.columns if column in excluded_names]
            if drop_cols:
                setattr(state, frame_attr, frame.drop(columns=drop_cols))


def _parse_datamodel(state: SessionState, file_path: str) -> dict:
    """Parse an IEA Task 43 datamodel JSON file into the Phase 1 height-to-sensor mapping."""
    try:
        path = _confined_file_path(state, file_path, subdir="uploads")
    except (OSError, RuntimeError) as exc:
        raise ValueError("Input file is not available") from exc
    if not path.exists():
        raise ValueError("Input file is not available")
    payload = json.loads(path.read_text(encoding="utf-8"))
    site_metadata = _extract_site_metadata(payload)
    # Extract and apply campaign timezone (D8)
    tz_source, tz_obj = _extract_timezone(payload)
    state.timezone = tz_obj
    state.runconfig.setdefault("site", {})["timezone"] = str(tz_obj)
    state.runconfig["site"]["timezone_source"] = tz_source
    # Convert existing timeseries if already loaded (datamodel after timeseries)
    tz_resolution = _apply_timezone_to_index(state, tz_obj)
    state.runconfig["site"]["timezone_resolution"] = tz_resolution["timezone_resolution"]
    if "standard_offset_hours" in tz_resolution:
        state.runconfig["site"]["standard_offset_hours"] = tz_resolution["standard_offset_hours"]
    points = _extract_measurement_points(payload)
    mapping, resolution_log = _build_sensor_mapping(points, timeseries_df=state.timeseries_df)
    state.sensor_inventory = _build_sensor_inventory(points)
    if state.timeseries_df is not None:
        mapping = {
            height: sensor_map
            for height, sensor_map in mapping.items()
            if sensor_map.get("speed_col") in state.timeseries_df.columns
        }
    state.sensor_mapping = dict(sorted(mapping.items(), reverse=True))
    # Persist boom-pair resolutions to runconfig for auditability (D7)
    if resolution_log:
        state.runconfig.setdefault("site", {})["sensor_resolution"] = resolution_log
    # A datamodel (re)import rebuilds the full inventory; trim it back to the
    # persisted selection so excluded sensors never silently reappear.
    _apply_sensor_exclusions(state)
    _prune_sensor_mapping(state)
    state.sensor_mapping = dict(sorted(state.sensor_mapping.items(), reverse=True))
    if state.get_project_name() in {None, ""} and isinstance(site_metadata.get("project_name"), str):
        state.set_project_name(str(site_metadata["project_name"]))
    if state.get_coordinate() is None and isinstance(site_metadata.get("coordinate"), Coordinate):
        state.set_coordinate(site_metadata["coordinate"])
    if state.get_measurement_type() in {None, ""} and isinstance(site_metadata.get("measurement_type"), str):
        state.set_measurement_type(str(site_metadata["measurement_type"]))

    result = {
        "status": "ok",
        "heights": list(state.sensor_mapping.keys()),
        "mapping": {str(height): sensor_map.copy() for height, sensor_map in state.sensor_mapping.items()},
        "timezone": str(tz_obj),
        "timezone_source": tz_source,
        **tz_resolution,
    }
    coordinate = state.get_coordinate()
    if state.get_project_name() is not None:
        result["project_name"] = state.get_project_name()
    if coordinate is not None:
        result["location"] = coordinate.model_dump()
    if state.get_measurement_type() is not None:
        result["measurement_type"] = state.get_measurement_type()
    return result


def _list_sensors(state: SessionState) -> dict:
    """List mapped sensors with coverage statistics using the GoKaatru Phase 1 inventory contract."""
    return {"sensors": _build_sensor_rows(state, require_mapping=True)}


def _get_period_of_record(state: SessionState) -> dict:
    """Summarize period of record and sensor inventory per the Phase 1 measurement inventory spec."""
    if state.timeseries_df is None:
        raise ValueError("Timeseries data is not loaded")
    return {
        "start": _format_timestamp(state.timeseries_df.index.min()),
        "end": _format_timestamp(state.timeseries_df.index.max()),
        "total_records": int(len(state.timeseries_df)),
        "timestep_minutes": detect_timestep_minutes(state.timeseries_df),
        "sensors": _build_sensor_rows(state, require_mapping=False),
    }


def _get_data_coverage(state: SessionState, sensor_name: str) -> dict:
    """Return sensor coverage and gap statistics using the Phase 1 data availability spec."""
    if state.timeseries_df is None:
        raise ValueError("Timeseries data is not loaded")
    if sensor_name not in state.timeseries_df.columns:
        raise ValueError(f"Sensor column '{sensor_name}' not found in loaded timeseries")
    timestep_minutes = detect_timestep_minutes(state.timeseries_df)
    series = _cadence_aligned_series(state.timeseries_df[sensor_name], timestep_minutes)
    gap_lengths = _gap_lengths_in_minutes(series, timestep_minutes)
    total_records = int(len(series))
    valid_records = int(series.notna().sum())
    largest_gap = max(gap_lengths, default=0)
    gaps_over_1_hour = sum(1 for gap in gap_lengths if gap > 60)
    return {
        "sensor": sensor_name,
        "total_records": total_records,
        "valid_records": valid_records,
        "coverage_pct": 0.0 if total_records == 0 else float(valid_records / total_records * 100.0),
        "largest_gap_minutes": largest_gap,
        "gaps_over_1_hour": gaps_over_1_hour,
    }


@mcp.tool()
def parse_timeseries(file_path: str) -> dict:
    """Parse a wind timeseries file into session state following the GoKaatru Phase 1 ingest spec."""
    return _parse_timeseries(session, file_path)


@mcp.tool()
def parse_datamodel(file_path: str) -> dict:
    """Parse an IEA Task 43 datamodel JSON file into the Phase 1 height-to-sensor mapping."""
    return _parse_datamodel(session, file_path)


@mcp.tool()
def list_sensors() -> dict:
    """List mapped sensors with coverage statistics using the GoKaatru Phase 1 inventory contract."""
    return _list_sensors(session)


@mcp.tool()
def get_period_of_record() -> dict:
    """Summarize period of record and sensor inventory per the Phase 1 measurement inventory spec."""
    return _get_period_of_record(session)


@mcp.tool()
def get_data_coverage(sensor_name: str) -> dict:
    """Return sensor coverage and gap statistics using the Phase 1 data availability spec."""
    return _get_data_coverage(session, sensor_name)
