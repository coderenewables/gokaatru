"""test_sensor_selection — Regression coverage for the authoritative sensor-selection flow.

Part of GoKaatru MCP Server.

The sensor selection made in the Data Load stage must be authoritative: once
sensors are excluded they must disappear from the inventory, the sensor
mapping, and the working/raw timeseries data, and they must not silently
reappear when a datamodel is re-parsed (session restore, datamodel-only
re-import). Only loading a new timeseries or re-importing from BrightHub
restores the full dataset.
"""
from __future__ import annotations

from pathlib import Path

from server.state.session import session
from server.tools.data_io import _apply_sensor_exclusions, _list_sensors, _parse_datamodel, _parse_timeseries


def _ingest(timeseries_path: Path, datamodel_path: Path) -> None:
    """Parse a timeseries + datamodel pair into the singleton session."""
    _parse_timeseries(session, str(timeseries_path))
    _parse_datamodel(session, str(datamodel_path))


def _exclude(names: list[str]) -> None:
    """Mirror the sensors/delete route's authoritative removal semantics."""
    removed_set = set(names)
    for name in names:
        meta = session.sensor_inventory.pop(name, None)
        if meta is None:
            continue
        for map_height, slots in list(session.sensor_mapping.items()):
            for slot, column in list(slots.items()):
                if column == name:
                    slots[slot] = None
            if all(value is None for value in slots.values()):
                del session.sensor_mapping[map_height]
    for frame_attr in ("timeseries_df", "raw_timeseries_df"):
        frame = getattr(session, frame_attr)
        if frame is not None:
            drop_cols = [column for column in frame.columns if column in removed_set]
            if drop_cols:
                setattr(session, frame_attr, frame.drop(columns=drop_cols))
    existing = session.runconfig.get("excluded_sensors")
    excluded_list = [str(name) for name in existing] if isinstance(existing, list) else []
    for name in names:
        if name not in excluded_list:
            excluded_list.append(name)
    session.runconfig["excluded_sensors"] = excluded_list


def test_excluded_sensors_removed_from_inventory_mapping_and_data(
    uploaded_timeseries_path: Path, uploaded_datamodel_path: Path
) -> None:
    """Deleting sensors must remove them from every analysis surface, not just the list."""
    _ingest(uploaded_timeseries_path, uploaded_datamodel_path)
    assert "Spd_80m" in session.timeseries_df.columns

    _exclude(["Spd_80m", "Dir_80m"])

    assert "Spd_80m" not in session.sensor_inventory
    assert "Dir_80m" not in session.sensor_inventory
    assert "Spd_80m" not in session.timeseries_df.columns
    assert "Spd_80m" not in session.raw_timeseries_df.columns
    assert all(slots.get("speed_col") != "Spd_80m" for slots in session.sensor_mapping.values())
    listed = {row["name"] for row in _list_sensors(session)["sensors"]}
    assert "Spd_80m" not in listed
    assert "Dir_80m" not in listed
    assert session.runconfig["excluded_sensors"] == ["Spd_80m", "Dir_80m"]


def test_datamodel_reimport_does_not_restore_excluded_sensors(
    uploaded_timeseries_path: Path, uploaded_datamodel_path: Path
) -> None:
    """Re-parsing the datamodel (session restore) must honor the persisted exclusion."""
    _ingest(uploaded_timeseries_path, uploaded_datamodel_path)
    _exclude(["Spd_80m", "Dir_80m"])

    # Re-parse only the datamodel, as happens on session restore / re-import.
    _parse_datamodel(session, str(uploaded_datamodel_path))

    assert "Spd_80m" not in session.sensor_inventory
    assert "Dir_80m" not in session.sensor_inventory
    assert "Spd_80m" not in session.timeseries_df.columns
    assert all(slots.get("speed_col") != "Spd_80m" for slots in session.sensor_mapping.values())
    listed = {row["name"] for row in _list_sensors(session)["sensors"]}
    assert "Spd_80m" not in listed


def test_timeseries_reload_clears_exclusion_and_restores_full_dataset(
    uploaded_timeseries_path: Path, uploaded_datamodel_path: Path
) -> None:
    """Loading the timeseries again is the supported way to restore excluded sensors."""
    _ingest(uploaded_timeseries_path, uploaded_datamodel_path)
    _exclude(["Spd_80m"])
    assert "excluded_sensors" in session.runconfig

    # Re-load the full dataset (timeseries + datamodel), as the UI does on re-import.
    _ingest(uploaded_timeseries_path, uploaded_datamodel_path)

    assert "excluded_sensors" not in session.runconfig
    assert "Spd_80m" in session.sensor_inventory
    assert "Spd_80m" in session.timeseries_df.columns


def test_apply_sensor_exclusions_noop_without_persisted_selection(
    uploaded_timeseries_path: Path, uploaded_datamodel_path: Path
) -> None:
    """Without a persisted exclusion, re-import keeps the complete inventory."""
    _ingest(uploaded_timeseries_path, uploaded_datamodel_path)
    full_inventory = set(session.sensor_inventory)
    full_columns = list(session.timeseries_df.columns)

    _apply_sensor_exclusions(session)

    assert set(session.sensor_inventory) == full_inventory
    assert list(session.timeseries_df.columns) == full_columns
