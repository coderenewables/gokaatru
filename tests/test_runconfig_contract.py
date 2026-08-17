"""Regression tests for D20 — the canonical/mirror runconfig contract.

The backend strips the frontend's mirrored keys after promoting them to
canonical ones, and configSync.ts fans the canonical values back out. That is
intentional. What was missing is enforcement: the contract lived implicitly in
three files, and missing one of them failed silently.

These tests assert that every stripped key is reproducible from a canonical key,
and that the two backend strippers cannot drift apart.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from server.core.runconfig import (
    BACKEND_OWNED_SECTION_KEYS,
    RUNCONFIG_MIRRORS,
    canonical_paths,
    get_dotted,
    has_dotted,
    mirror_paths,
    pop_dotted,
    strip_mirrors,
)
from server.state.session import SessionState
from server.tools.config import _normalize_runconfig, _sync_state_from_runconfig

CONFIG_SYNC_TS = Path("frontend/src/lib/configSync.ts")


def _frontend_shaped_config() -> dict:
    """A runconfig as the frontend serializes it, carrying every mirrored key."""
    return {
        "project_name": "Test Project",
        "measurement_type": "lidar",
        "location": {"latitude": 52.5, "longitude": 4.75, "elevation_m": 12.0},
        "hub_height_m": 150.0,
        "project": {"name": "Test Project", "measurementType": "lidar", "client": "ACME"},
        "site": {
            "latitude": 52.5,
            "longitude": 4.75,
            "elevationM": 12.0,
            "hubHeightM": 150.0,
            "region": "North Sea",
        },
        "shear": {
            "method": "power_law",
            "targetHubHeightM": 150.0,
            "aggregation": "mean",
            "useWindKit": False,
        },
        "reanalysis": {"searchLatitude": 52.5, "searchLongitude": 4.75, "preferredProvider": "ERA5"},
        "ltc": {"uncertainty": {"hubHeightM": 150.0, "iavPct": 5.0}},
    }


class TestEveryMirrorIsReproducible:
    """The core assertion D20 asks for."""

    def test_stripped_keys_are_gone(self) -> None:
        config = _normalize_runconfig(_frontend_shaped_config())
        for path in mirror_paths():
            assert not has_dotted(config, path), f"{path} survived normalization"

    @pytest.mark.parametrize("entry", RUNCONFIG_MIRRORS, ids=lambda e: e.mirror)
    def test_each_mirror_has_its_canonical_source(self, entry) -> None:
        """A stripped key is only safe to strip if it can be rebuilt."""
        config = _normalize_runconfig(_frontend_shaped_config())
        assert has_dotted(config, entry.canonical), (
            f"{entry.mirror} is stripped but its source {entry.canonical} is absent — "
            "the frontend cannot rehydrate it"
        )

    def test_mirror_values_match_their_canonical_source_before_stripping(self) -> None:
        """The mirrors in a real frontend payload agree with the canonical values."""
        raw = _frontend_shaped_config()
        for entry in RUNCONFIG_MIRRORS:
            assert get_dotted(raw, entry.mirror) == get_dotted(raw, entry.canonical), entry.mirror

    def test_canonical_keys_survive_normalization(self) -> None:
        config = _normalize_runconfig(_frontend_shaped_config())
        for path in canonical_paths():
            assert has_dotted(config, path), f"canonical key {path} was lost"


class TestPromotionFromLegacyConfigs:
    """A config carrying only the mirrors must still yield the canonical keys."""

    def test_legacy_only_config_promotes(self) -> None:
        legacy = {
            "project": {"name": "Legacy", "measurementType": "mast"},
            "site": {"latitude": 10.0, "longitude": 20.0, "elevationM": 5.0, "hubHeightM": 100.0},
        }
        config = _normalize_runconfig(legacy)

        assert config["project_name"] == "Legacy"
        assert config["measurement_type"] == "mast"
        assert config["location"] == {"latitude": 10.0, "longitude": 20.0, "elevation_m": 5.0}
        assert config["hub_height_m"] == 100.0

    def test_derived_only_mirrors_are_dropped_not_promoted(self) -> None:
        """shear.targetHubHeightM etc. are outputs, never inputs."""
        config = _normalize_runconfig({"shear": {"targetHubHeightM": 99.0}})
        assert "hub_height_m" not in config
        assert config["shear"] == {}

    def test_canonical_wins_over_a_conflicting_mirror(self) -> None:
        config = _normalize_runconfig(
            {"hub_height_m": 150.0, "site": {"hubHeightM": 80.0}}
        )
        assert config["hub_height_m"] == 150.0

    def test_non_string_project_name_is_dropped_not_promoted(self) -> None:
        """Legacy configs are untrusted input; a junk value must not reach disk."""
        config = _normalize_runconfig({"project": {"name": 42}})
        assert "project_name" not in config
        assert config["project"] == {}


class TestBothStrippersAgree:
    """to_runconfig and _normalize_runconfig must strip the same set."""

    def test_to_runconfig_strips_every_mirror(self) -> None:
        state = SessionState()
        state.reset()
        state.runconfig = _frontend_shaped_config()

        config = state.to_runconfig()
        for path in mirror_paths():
            assert not has_dotted(config, path), f"{path} survived to_runconfig"

    def test_round_trip_through_state_preserves_canonical_values(self) -> None:
        state = SessionState()
        state.reset()
        state.runconfig = _frontend_shaped_config()
        _sync_state_from_runconfig(state)

        config = _normalize_runconfig(state.to_runconfig())
        assert config["hub_height_m"] == 150.0
        assert config["project_name"] == "Test Project"
        assert config["location"]["latitude"] == 52.5

    def test_strip_mirrors_is_idempotent(self) -> None:
        config = strip_mirrors(_frontend_shaped_config())
        assert strip_mirrors(dict(config)) == config


class TestBackendOwnedSectionKeys:
    """Keys the backend owns inside a frontend-written section must not be stripped."""

    def test_shear_min_speed_survives_both_strippers(self) -> None:
        config = _frontend_shaped_config()
        config["shear"]["minSpeedMps"] = 4.5

        normalized = _normalize_runconfig(config)
        assert normalized["shear"]["minSpeedMps"] == 4.5

        state = SessionState()
        state.reset()
        state.runconfig = normalized
        assert state.to_runconfig()["shear"]["minSpeedMps"] == 4.5

    @pytest.mark.parametrize("path", BACKEND_OWNED_SECTION_KEYS)
    def test_backend_owned_keys_are_not_mirrors(self, path: str) -> None:
        assert path not in mirror_paths()

    def test_shear_min_speed_round_trips_through_the_session_accessor(self) -> None:
        state = SessionState()
        state.reset()
        state.set_shear_min_speed_mps(6.0)
        assert state.to_runconfig()["shear"]["minSpeedMps"] == 6.0
        assert state.get_shear_min_speed_mps(3.0) == 6.0


class TestFrontendDocumentationIsInStep:
    """The third drift point: configSync.ts must document the same mapping."""

    def test_configsync_references_the_table(self) -> None:
        source = CONFIG_SYNC_TS.read_text(encoding="utf-8")
        assert "RUNCONFIG_MIRRORS" in source
        assert "server/core/runconfig.py" in source

    @pytest.mark.parametrize("entry", RUNCONFIG_MIRRORS, ids=lambda e: e.mirror)
    def test_every_mirror_is_documented_in_configsync(self, entry) -> None:
        """A mirror added to the table without a rehydrate is the D20 failure mode."""
        source = CONFIG_SYNC_TS.read_text(encoding="utf-8")
        assert entry.mirror in source, (
            f"{entry.mirror} is stripped by the backend but is not mentioned in "
            f"{CONFIG_SYNC_TS} — the frontend will not rehydrate it"
        )

    def test_hydrate_assigns_each_mirrored_field(self) -> None:
        """Beyond the comment: the hydrate function must actually set each mirror."""
        source = CONFIG_SYNC_TS.read_text(encoding="utf-8")
        hydrate = source.split("export function hydrateConfigFromRunconfig")[1].split(
            "export function"
        )[0]
        for entry in RUNCONFIG_MIRRORS:
            # "site.hubHeightM" -> assignment to `.site.hubHeightM`
            assigned = re.search(rf"\.{re.escape(entry.mirror)}\s*=", hydrate)
            merged = f"runconfig.{entry.mirror.split('.')[0]}" in hydrate
            assert assigned or merged, f"hydrate never reconstructs {entry.mirror}"


class TestPersistedConfigStaysValidJson:
    """The stripped config is what reaches disk and the browser."""

    def test_normalized_config_is_json_serializable(self) -> None:
        config = _normalize_runconfig(_frontend_shaped_config())
        assert json.loads(json.dumps(config, allow_nan=False)) == config

    def test_pop_dotted_tolerates_missing_paths(self) -> None:
        config: dict = {"a": {"b": 1}}
        pop_dotted(config, "a.b.c.d")
        pop_dotted(config, "nope.nothing")
        assert config == {"a": {"b": 1}}
