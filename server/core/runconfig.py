"""runconfig — the canonical/mirror runconfig contract (D20).

The runconfig has a **single source of truth on the backend** and **derived
mirrors on the frontend**. ``server/tools/config.py::_normalize_runconfig`` and
``server/state/session.py::to_runconfig`` strip the mirrored keys after
promoting any legacy values to their canonical form;
``frontend/src/lib/configSync.ts::hydrateConfigFromRunconfig`` fans the canonical
values back out into the typed frontend model.

That is correct and intentional — do not "fix" it by persisting the mirrors.

The problem this module solves is that the contract used to be implicit and
duplicated across those three files. Adding a mirrored field meant coordinated
edits in all three, and missing one failed silently: the frontend Zod schema
requires the mirrored fields, so a missed rehydrate surfaces as a validation
error far from its cause.

``RUNCONFIG_MIRRORS`` is the one place that mapping is written down. The backend
files below drive their stripping from it, and
``tests/test_runconfig_contract.py`` asserts that every stripped key is
reproducible from a canonical key.

This module lives in ``core`` rather than ``tools/config.py`` so that
``state/session.py`` can import it too — ``tools/config.py`` already imports
``SessionState``, so the table could not live there without a cycle.
"""
from __future__ import annotations

from dataclasses import dataclass

_MISSING = object()


@dataclass(frozen=True)
class RunconfigMirror:
    """One frontend-visible key derived from a canonical backend key.

    ``mirror`` is stripped from the persisted runconfig. ``canonical`` is the
    key it must be reproducible from. ``promote`` marks the mirrors that a
    legacy (pre-canonical) config may be used to seed the canonical key from;
    the rest are purely derived and are only ever dropped.
    """

    mirror: str
    canonical: str
    promote: bool


# The complete canonical -> mirror mapping. Referenced by a comment in
# frontend/src/lib/configSync.ts; keep the three in step.
RUNCONFIG_MIRRORS: tuple[RunconfigMirror, ...] = (
    RunconfigMirror("project.name", "project_name", promote=True),
    RunconfigMirror("project.measurementType", "measurement_type", promote=True),
    RunconfigMirror("site.latitude", "location.latitude", promote=True),
    RunconfigMirror("site.longitude", "location.longitude", promote=True),
    RunconfigMirror("site.elevationM", "location.elevation_m", promote=True),
    RunconfigMirror("site.hubHeightM", "hub_height_m", promote=True),
    # Derived only — the frontend fans hub_height_m out to these three.
    RunconfigMirror("shear.targetHubHeightM", "hub_height_m", promote=False),
    RunconfigMirror("ltc.uncertainty.hubHeightM", "hub_height_m", promote=False),
    RunconfigMirror("reanalysis.searchLatitude", "location.latitude", promote=False),
    RunconfigMirror("reanalysis.searchLongitude", "location.longitude", promote=False),
)

# Canonical, backend-owned keys that happen to live *inside* a section the
# frontend also writes. They are not mirrors: nothing on the frontend derives
# them, and the frontend must not clobber them.
#
# The frontend's Zod section schemas are non-strict, so these are silently
# dropped from the typed model on hydrate and never re-serialized. They survive
# only because `buildRunconfigUpdates` emits updates key-by-key and therefore
# cannot delete a key it does not know about. That is fragile: anything that
# ever replaces a whole section wholesale would drop them.
BACKEND_OWNED_SECTION_KEYS: tuple[str, ...] = (
    "shear.minSpeedMps",  # D3 — shear valid-record speed gate
)


def get_dotted(config: dict[str, object], path: str) -> object:
    """Return the value at a dotted path, or ``_MISSING`` when absent."""
    cursor: object = config
    for part in path.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            return _MISSING
        cursor = cursor[part]
    return cursor


def has_dotted(config: dict[str, object], path: str) -> bool:
    """Return whether a dotted path is present."""
    return get_dotted(config, path) is not _MISSING


def pop_dotted(config: dict[str, object], path: str) -> None:
    """Remove a dotted path if present, leaving parent containers in place."""
    parts = path.split(".")
    cursor: object = config
    for part in parts[:-1]:
        if not isinstance(cursor, dict) or part not in cursor:
            return
        cursor = cursor[part]
    if isinstance(cursor, dict):
        cursor.pop(parts[-1], None)


def strip_mirrors(config: dict[str, object]) -> dict[str, object]:
    """Remove every mirrored key, in place, returning the same dict.

    Called by both backend writers so neither can drift from the table.
    """
    for entry in RUNCONFIG_MIRRORS:
        pop_dotted(config, entry.mirror)
    return config


def mirror_paths() -> tuple[str, ...]:
    """Return every mirrored key path."""
    return tuple(entry.mirror for entry in RUNCONFIG_MIRRORS)


def canonical_paths() -> tuple[str, ...]:
    """Return the distinct canonical keys the mirrors derive from."""
    return tuple(dict.fromkeys(entry.canonical for entry in RUNCONFIG_MIRRORS))
