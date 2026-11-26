"""datamodel_builder — build a minimal IEA Task 43 data model from CSV headers alone.

A campaign delivered as a bare CSV cannot be analysed: ``sensor_mapping`` stays empty, so
``completed_steps`` never reaches ``datamodel`` and every height-indexed stage — shear,
extrapolation, the sensor policies — has no heights to work with.  ``state.timezone``
stays unset too, because parsing a data model is the only thing that ever assigns it.

This module builds the smallest data model that closes both gaps.  It is deliberately a
*document* builder, not a state writer: the output is a plain Task 43 subset that goes
through the existing ``_parse_datamodel``, so one code path populates session state and
the analyst's declaration survives as a downloadable, auditable artifact rather than as an
inference living in memory.

Only what a consumer actually reads is emitted — location coordinates and timezone,
per-point name/height/measurement type, boom orientation and the primary flag, and the
statistic columns Task 43 already carries on ``logger_measurement_config``.  Calibration,
uncertainty, mast geometry and logger provenance are outside the scope of making the
pipeline run, and inventing them would misrepresent how much is actually known.

Inference is a *draft*, never an answer.  ``draft_columns`` proposes a reading of each
header and says why it could not read one; ``build_datamodel`` refuses anything still
incomplete rather than substituting a default, because a missing height silently becoming
0 m puts a sensor on the ground.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Sequence

ROLE_MEASUREMENT = "measurement"
ROLE_STATISTIC = "statistic"
ROLE_IGNORED = "ignored"

#: The ``author`` of every document the builder writes; what tells a drafted data model,
#: which the workbench may edit, from a campaign's own, which it never changes.
BUILDER_AUTHOR = "GoKaatru data model builder"


def is_built_document(payload: object) -> bool:
    """Whether a Task 43 document was written by this builder rather than delivered with
    the campaign."""
    return isinstance(payload, dict) and payload.get("author") == BUILDER_AUTHOR


BUILDER_PROVENANCE_NOTE = (
    "Built by the GoKaatru data model builder from timeseries column headers. "
    "Column roles and heights were drafted by header inference and declared by the "
    "analyst; they are not from an instrument record."
)

# The measurement_type_id values ``_build_sensor_mapping``'s type_to_field actually
# understands. Emitting anything else produces a point that parses but maps to no slot.
ACCEPTED_MEASUREMENT_TYPES = frozenset(
    {
        "wind_speed",
        "wind_direction",
        "temperature",
        "air_temperature",
        "pressure",
        "air_pressure",
        "relative_humidity",
    }
)

# Trailing statistic tokens, normalised onto Task 43 statistic_type_id values. Only
# ``avg`` and ``sd`` are ever emitted; the rest exist so that a max/min/count column is
# recognised as belonging to its parent instead of being read as a sensor of its own.
_STATISTIC_SUFFIXES: dict[str, str] = {
    "avg": "avg",
    "average": "avg",
    "mean": "avg",
    "sd": "sd",
    "std": "sd",
    "stdev": "sd",
    "stddev": "sd",
    "max": "max",
    "min": "min",
    "ti": "ti",
    "count": "count",
    "sum": "sum",
    "tot": "sum",
}

_STATISTIC_RE = re.compile(
    r"^(?P<stem>.+?)[_\s-](?P<statistic>" + "|".join(sorted(_STATISTIC_SUFFIXES, key=len, reverse=True)) + r")$",
    flags=re.IGNORECASE,
)

# A height token is a number immediately followed by a metre unit. The optional sign
# matters: sea-surface and below-deck sensors are recorded at negative heights
# (Horns Rev carries a water temperature at -4 m).
_HEIGHT_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*m(?![a-z])", flags=re.IGNORECASE)

# Checked before any instrument pattern. A quality channel names the sensor it describes,
# so read as an instrument ``Qual_Spd_58m_quality`` would invent a second 58 m anemometer
# and turn a clean height into a boom pair that then gets "resolved".
_IGNORE_RE = re.compile(
    r"qual|status|flag|valid|error|alarm|logger|batt|voltage|current|diag|signal|avail",
    flags=re.IGNORECASE,
)

# Ordered: direction is tested before speed because a direction header often carries a
# wind token too, and the more specific reading should win.
_MEASUREMENT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"wind[_\s-]?dir|(?:^|[_\s-])wd(?=$|[_\s\d-])|(?:^|[_\s-])dir|vane", re.IGNORECASE), "wind_direction"),
    (re.compile(r"wind[_\s-]?spe?e?d|(?:^|[_\s-])ws(?=$|[_\s\d-])|(?:^|[_\s-])spd|anem", re.IGNORECASE), "wind_speed"),
    (re.compile(r"temp|(?:^|[_\s-])tmp", re.IGNORECASE), "temperature"),
    (re.compile(r"press|(?:^|[_\s-])prs|baro|(?:^|[_\s-])bp(?=$|[_\s\d-])", re.IGNORECASE), "pressure"),
    (re.compile(r"humid|(?:^|[_\s-])rh(?=$|[_\s\d-])|(?:^|[_\s-])hum", re.IGNORECASE), "relative_humidity"),
)


@dataclass(frozen=True)
class ColumnDraft:
    """One proposed reading of one CSV column.

    ``reason`` carries why a column could not be read confidently, so the analyst is told
    what to supply rather than being handed a silent default.
    """

    name: str
    role: str
    measurement_type_id: str | None = None
    height_m: float | None = None
    statistic_type_id: str | None = None
    parent: str | None = None
    reason: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "role": self.role,
            "measurement_type_id": self.measurement_type_id,
            "height_m": self.height_m,
            "statistic_type_id": self.statistic_type_id,
            "parent": self.parent,
            "reason": self.reason,
        }


def _split_statistic(name: str) -> tuple[str, str | None]:
    """Split a header into its stem and trailing statistic token, if it has one."""
    match = _STATISTIC_RE.match(name)
    if match is None:
        return name, None
    return match.group("stem"), _STATISTIC_SUFFIXES[match.group("statistic").lower()]


def _infer_measurement_type(stem: str) -> str | None:
    """Return the measurement_type_id a header stem reads as, or None."""
    if _IGNORE_RE.search(stem):
        return None
    for pattern, measurement_type_id in _MEASUREMENT_PATTERNS:
        if pattern.search(stem):
            return measurement_type_id
    return None


def _infer_height(stem: str) -> float | None:
    """Return the first metre-denominated height token in a header stem, or None."""
    match = _HEIGHT_RE.search(stem)
    return None if match is None else float(match.group(1))


def draft_columns(columns: Sequence[str]) -> list[ColumnDraft]:
    """Propose a reading of every timeseries column, in the order they appear.

    Columns are grouped by stem first, so ``WS_80m_Avg`` and ``WS_80m_SD`` are recognised
    as one sensor and its turbulence channel.  Grouping on the stem rather than on the
    parent's full name is what makes the builder work on real exports: the
    ``{speed}_sd`` naming convention only ever paired ``Spd_80m`` with ``Spd_80m_sd``.
    """
    parsed = [(name, *_split_statistic(name)) for name in columns]

    groups: dict[str, list[tuple[str, str | None]]] = {}
    for name, stem, statistic in parsed:
        groups.setdefault(stem.lower(), []).append((name, statistic))

    representatives: dict[str, str] = {}
    for key, members in groups.items():
        bare = [name for name, statistic in members if statistic is None]
        averaged = [name for name, statistic in members if statistic == "avg"]
        if bare:
            representatives[key] = bare[0]
        elif averaged:
            representatives[key] = averaged[0]

    drafts: list[ColumnDraft] = []
    for name, stem, statistic in parsed:
        key = stem.lower()
        representative = representatives.get(key)
        measurement_type_id = _infer_measurement_type(stem)

        if measurement_type_id is None:
            drafts.append(
                ColumnDraft(
                    name=name,
                    role=ROLE_IGNORED,
                    reason=(
                        "Header does not read as a wind speed, direction, temperature, "
                        "pressure or humidity channel."
                    ),
                )
            )
            continue

        if name != representative:
            drafts.append(
                ColumnDraft(
                    name=name,
                    role=ROLE_STATISTIC,
                    statistic_type_id=statistic,
                    parent=representative,
                    measurement_type_id=measurement_type_id,
                    height_m=_infer_height(stem),
                )
            )
            continue

        height_m = _infer_height(stem)
        drafts.append(
            ColumnDraft(
                name=name,
                role=ROLE_MEASUREMENT,
                measurement_type_id=measurement_type_id,
                height_m=height_m,
                reason=(
                    None
                    if height_m is not None
                    else "No height token in the header — declare the height in metres."
                ),
            )
        )
    return drafts


def spec_from_draft(columns: Sequence[str], location: dict[str, object]) -> dict[str, object]:
    """Turn a draft into a build spec, keeping only confidently-read measurement columns.

    This is the prefill the UI edits before submitting, and the shortest path for a
    caller that accepts the inference wholesale.  Columns the draft could not read are
    left out rather than carried through with a placeholder.
    """
    drafts = draft_columns(columns)
    statistics: dict[str, list[dict[str, str]]] = {}
    for draft in drafts:
        if draft.role == ROLE_STATISTIC and draft.statistic_type_id == "sd" and draft.parent:
            statistics.setdefault(draft.parent, []).append(
                {"column_name": draft.name, "statistic_type_id": "sd"}
            )

    points: list[dict[str, object]] = []
    for draft in drafts:
        if draft.role != ROLE_MEASUREMENT or draft.height_m is None or draft.measurement_type_id is None:
            continue
        point: dict[str, object] = {
            "name": draft.name,
            "measurement_type_id": draft.measurement_type_id,
            "height_m": draft.height_m,
        }
        if draft.name in statistics:
            point["statistics"] = statistics[draft.name]
        points.append(point)
    return {"location": dict(location), "points": points}


def _coerce_float(value: object) -> float | None:
    """Return a numeric field as a float, or None when it is absent or unreadable."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _validate_timezone(location: dict[str, object]) -> tuple[str | None, float | None]:
    """Return the declared (IANA zone, UTC offset), refusing when neither is present."""
    zone = location.get("timezone")
    zone = zone.strip() if isinstance(zone, str) and zone.strip() else None
    offset = _coerce_float(location.get("offset_from_utc_hrs"))
    if zone is None and offset is None:
        raise ValueError(
            "Declare the campaign timezone: either an IANA zone name (site 'timezone') or "
            "the logger's fixed UTC offset in hours ('offset_from_utc_hrs'). Timestamps "
            "cannot be placed on a clock without one, and nothing downstream can infer it."
        )
    return zone, offset


def _validate_points(
    points: object, available_columns: Iterable[str]
) -> list[dict[str, object]]:
    """Check every declared point against the loaded data, refusing anything incomplete."""
    if not isinstance(points, list) or not points:
        raise ValueError("Declare at least one measurement point to build a data model.")

    available = set(available_columns)
    seen: set[str] = set()
    validated: list[dict[str, object]] = []

    for entry in points:
        if not isinstance(entry, dict):
            raise ValueError("Each measurement point must be an object.")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Each measurement point needs the timeseries column name it describes.")
        name = name.strip()
        if name not in available:
            raise ValueError(f"Column '{name}' is not present in the loaded timeseries.")
        if name in seen:
            raise ValueError(f"Column '{name}' is declared more than once.")
        seen.add(name)

        measurement_type_id = entry.get("measurement_type_id")
        if measurement_type_id not in ACCEPTED_MEASUREMENT_TYPES:
            raise ValueError(
                f"Column '{name}' has measurement_type_id "
                f"{measurement_type_id!r}; expected one of "
                f"{', '.join(sorted(ACCEPTED_MEASUREMENT_TYPES))}."
            )

        height_m = _coerce_float(entry.get("height_m"))
        if height_m is None:
            raise ValueError(
                f"Column '{name}' has no height. Declare its height in metres — it is the "
                "key every vertical-profile stage indexes on."
            )

        statistics: list[dict[str, str]] = []
        for statistic in entry.get("statistics") or []:
            if not isinstance(statistic, dict):
                raise ValueError(f"Column '{name}' has an unreadable statistics entry.")
            column_name = statistic.get("column_name")
            if not isinstance(column_name, str) or column_name not in available:
                raise ValueError(
                    f"Column '{name}' declares statistic column {column_name!r}, which is "
                    "not present in the loaded timeseries."
                )
            statistics.append(
                {
                    "column_name": column_name,
                    "statistic_type_id": str(statistic.get("statistic_type_id") or "sd"),
                }
            )

        validated.append(
            {
                "name": name,
                "measurement_type_id": measurement_type_id,
                "height_m": height_m,
                "boom_orientation_deg": _coerce_float(entry.get("boom_orientation_deg")),
                "is_primary": entry.get("is_primary") if isinstance(entry.get("is_primary"), bool) else None,
                "statistics": statistics,
            }
        )
    return validated


def _emit_point(point: dict[str, object]) -> dict[str, object]:
    """Render one validated point as a Task 43 measurement_point."""
    name = point["name"]
    height_m = point["height_m"]
    columns = [{"column_name": name, "statistic_type_id": "avg"}]
    columns.extend(point["statistics"])  # type: ignore[arg-type]

    emitted: dict[str, object] = {
        "name": name,
        "measurement_type_id": point["measurement_type_id"],
        "height_m": height_m,
        "height_reference_id": "ground_level",
        "logger_measurement_config": [{"height_m": height_m, "column_name": columns}],
    }
    if point["is_primary"] is not None:
        emitted["is_primary"] = point["is_primary"]
    if point["boom_orientation_deg"] is not None:
        emitted["mounting_arrangement"] = [
            {"boom_orientation_deg": point["boom_orientation_deg"], "mounting_type_id": "side"}
        ]
    return emitted


def build_datamodel(spec: dict[str, object], available_columns: Iterable[str]) -> dict[str, object]:
    """Build a minimal IEA Task 43 data model document from a declared spec.

    Raises ``ValueError`` with the offending column named whenever the spec is
    incomplete; nothing is defaulted on the analyst's behalf.
    """
    location = spec.get("location")
    if not isinstance(location, dict):
        raise ValueError("Declare the measurement location (name, coordinates, timezone).")

    zone, offset = _validate_timezone(location)
    points = _validate_points(spec.get("points"), available_columns)

    notes = str(location.get("notes") or "").strip()
    emitted_location: dict[str, object] = {
        "name": str(location.get("name") or "Unnamed site"),
        "notes": f"{notes}\n{BUILDER_PROVENANCE_NOTE}".strip(),
        "measurement_point": [_emit_point(point) for point in points],
    }

    latitude = _coerce_float(location.get("latitude_ddeg"))
    longitude = _coerce_float(location.get("longitude_ddeg"))
    if latitude is not None and longitude is not None:
        emitted_location["latitude_ddeg"] = latitude
        emitted_location["longitude_ddeg"] = longitude
    elevation = _coerce_float(location.get("elevation_m"))
    if elevation is not None:
        emitted_location["elevation_m"] = elevation
    station_type = location.get("measurement_station_type_id")
    if isinstance(station_type, str) and station_type.strip():
        emitted_location["measurement_station_type_id"] = station_type.strip()
    if zone is not None:
        emitted_location["timezone"] = zone
    if offset is not None:
        emitted_location["logger_main_config"] = [{"offset_from_utc_hrs": offset}]

    return {
        "author": BUILDER_AUTHOR,
        "date": datetime.now(timezone.utc).isoformat(),
        "version": "1.3.0-gokaatru-subset",
        "measurement_location": [emitted_location],
    }
