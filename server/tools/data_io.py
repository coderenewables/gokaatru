"""data_io — Phase 1 MCP tools for timeseries and datamodel loading.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from server.core.validators import detect_timestep_minutes
from server.main import mcp
from server.schemas.common import Coordinate, SensorInfo
from server.state.session import SessionState, session

TIMESTAMP_CANDIDATES = ["Timestamp", "timestamp", "DateTime", "datetime", "Date", "date", "Time", "time"]
SENSOR_FIELDS = {
    "speed_col": "wind_speed",
    "dir_col": "wind_direction",
    "temp_col": "temperature",
    "pressure_col": "pressure",
}


def _read_tabular_file(file_path: str) -> pd.DataFrame:
    """Load CSV, TSV, or Excel input according to the GoKaatru Phase 1 file-ingest spec."""
    try:
        path = Path(file_path).resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"Invalid file path: {file_path}") from exc
    if not path.exists():
        raise ValueError(f"Input file does not exist: {file_path}")
    if not path.is_file():
        raise ValueError(f"Input path is not a regular file: {file_path}")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".tsv", ".txt"}:
        return pd.read_csv(path, sep="\t")
    if suffix in {".xls", ".xlsx"}:
        return pd.read_excel(path)
    raise ValueError(f"Unsupported file type '{suffix}'. Expected CSV, TSV, TXT, XLS, or XLSX")


def _detect_timestamp_column(df: pd.DataFrame) -> tuple[str, pd.Series]:
    """Select the timestamp column with the most valid parses per the Phase 1 ingestion rule."""
    candidates = [column for column in TIMESTAMP_CANDIDATES if column in df.columns] or list(df.columns)
    best_name = ""
    best_series = pd.Series(dtype="datetime64[ns]")
    best_count = -1
    for column in candidates:
        parsed = pd.to_datetime(df[column], errors="coerce")
        valid_count = int(parsed.notna().sum())
        if valid_count > best_count:
            best_name = str(column)
            best_series = parsed
            best_count = valid_count
    if best_count <= 0:
        raise ValueError("Could not detect a timestamp column with any valid datetime values")
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


def _build_sensor_mapping(points: list[dict[str, object]]) -> dict[float, dict[str, str | None]]:
    """Map Task 43 measurement points to height-indexed sensor columns per the Phase 1 schema."""
    mapping: dict[float, dict[str, str | None]] = {}
    type_to_field = {
        "wind_speed": "speed_col",
        "wind_direction": "dir_col",
        "temperature": "temp_col",
        "air_temperature": "temp_col",
        "pressure": "pressure_col",
        "air_pressure": "pressure_col",
    }
    for point in points:
        height_value = point.get("height_m")
        sensor_name = point.get("name")
        sensor_type = type_to_field.get(str(point.get("measurement_type_id", "")))
        if not isinstance(height_value, (int, float)) or not isinstance(sensor_name, str) or sensor_type is None:
            continue
        mapping.setdefault(
            float(height_value),
            {
                "speed_col": None,
                "dir_col": None,
                "sd_col": None,
                "temp_col": None,
                "pressure_col": None,
            },
        )
        mapping[float(height_value)][sensor_type] = sensor_name
        if sensor_type == "speed_col":
            mapping[float(height_value)]["sd_col"] = f"{sensor_name}_sd"
    return mapping


def _build_sensor_rows(state: SessionState, require_mapping: bool) -> list[dict[str, object]]:
    """Build sensor inventory rows using session mapping rules from the Phase 1 data inventory spec."""
    if state.timeseries_df is None:
        raise ValueError("Timeseries data is not loaded")
    if require_mapping and not state.sensor_mapping:
        raise ValueError("Sensor mapping is not loaded. Run parse_datamodel first")
    sensors: list[dict[str, object]] = []
    total_rows = len(state.timeseries_df)
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
    # Include extrapolated hub-height columns (Spd_*m_hub) not already in sensor_mapping
    known_names = {s["name"] for s in sensors}
    import re
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
    return sensors


def _gap_lengths_in_minutes(series: pd.Series, timestep_minutes: int) -> list[int]:
    """Measure contiguous missing-data gap lengths in minutes using the inferred Phase 1 timestep."""
    missing = series.isna()
    groups = missing.ne(missing.shift(fill_value=False)).cumsum()
    gap_sizes = missing.groupby(groups).sum()
    return [int(size * timestep_minutes) for size in gap_sizes[gap_sizes > 0].tolist()]


def _parse_timeseries(state: SessionState, file_path: str) -> dict:
    """Parse a wind timeseries file into session state following the GoKaatru Phase 1 ingest spec."""
    source_df = _read_tabular_file(file_path)
    timestamp_column, parsed_timestamps = _detect_timestamp_column(source_df)
    filtered_df = source_df.loc[parsed_timestamps.notna()].copy()
    filtered_df.index = pd.DatetimeIndex(parsed_timestamps.loc[parsed_timestamps.notna()])
    filtered_df = filtered_df.drop(columns=[timestamp_column]).sort_index()
    if filtered_df.empty:
        raise ValueError("Parsed timeseries is empty after timestamp detection")
    state.timeseries_df = filtered_df.copy()
    state.raw_timeseries_df = filtered_df.copy(deep=True)
    timestep_minutes = detect_timestep_minutes(filtered_df)
    return {
        "status": "ok",
        "rows": int(len(filtered_df)),
        "columns": filtered_df.columns.tolist(),
        "start": _format_timestamp(filtered_df.index.min()),
        "end": _format_timestamp(filtered_df.index.max()),
        "timestep_minutes": timestep_minutes,
    }


def _parse_datamodel(state: SessionState, file_path: str) -> dict:
    """Parse an IEA Task 43 datamodel JSON file into the Phase 1 height-to-sensor mapping."""
    path = Path(file_path)
    if not path.exists():
        raise ValueError(f"Datamodel file does not exist: {file_path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    site_metadata = _extract_site_metadata(payload)
    mapping = _build_sensor_mapping(_extract_measurement_points(payload))
    if state.timeseries_df is not None:
        mapping = {
            height: sensor_map
            for height, sensor_map in mapping.items()
            if sensor_map.get("speed_col") in state.timeseries_df.columns
        }
    state.sensor_mapping = dict(sorted(mapping.items(), reverse=True))
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
    full_index = pd.date_range(
        state.timeseries_df.index.min(),
        state.timeseries_df.index.max(),
        freq=f"{timestep_minutes}min",
    )
    series = state.timeseries_df[sensor_name].reindex(full_index)
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
