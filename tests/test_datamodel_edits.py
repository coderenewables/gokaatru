"""Editing a drafted data model is undoable; a campaign's own is never changed (P2-7, 0014.8).

The mast diagram edits a data model by building it again from an edited spec. Undo puts
back the mapping, the inventory, the document on disk and the run configuration the build
set, and marks results stale again. The build that first puts the records into UTC cannot
be undone, and a data model delivered with the campaign refuses any build.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from server.core.datamodel_builder import build_datamodel
from server.operations import REGISTRY
from server.state.session import SessionState, bind_session
from server.tools.data_io import _parse_datamodel
from server.tools.datamodel_builder import BUILT_DATAMODEL_FILENAME, datamodel_state, same_declaration
from tests.test_datamodel_timezone import _spec, _state


def _call(state: SessionState, name: str, **arguments):
    with bind_session(state):
        return REGISTRY.get(name).fn(**arguments)


def _edited() -> dict:
    """The diagram's edit: the anemometer dragged from 80 m to 82 m."""
    spec = _spec(1)
    for point in spec["points"]:
        point["height_m"] = 82.0
    return spec


def test_an_edit_is_undone_and_redone_exactly(tmp_path: Path) -> None:
    state = _state(tmp_path)
    _call(state, "build_data_model", spec=_spec(1))
    first = datamodel_state(state)
    version = state.data_version

    _call(state, "build_data_model", spec=_edited())
    edited = datamodel_state(state)
    assert list(state.sensor_mapping) == [82.0] and state.data_version == version + 1
    assert state.datamodel_origin == {"file": BUILT_DATAMODEL_FILENAME, "built": True, "spec": _edited()}

    undone = _call(state, "undo_last_change")
    assert undone["detail"]["data_model"] == "restored"
    assert datamodel_state(state) == first
    assert list(state.sensor_mapping) == [80.0] and state.data_version == version + 2
    document = json.loads((tmp_path / "uploads" / BUILT_DATAMODEL_FILENAME).read_text())
    assert document["measurement_location"][0]["measurement_point"][0]["height_m"] == 80.0

    _call(state, "redo_last_change")
    redone = datamodel_state(state)
    assert same_declaration(redone.pop("document"), edited.pop("document"))
    assert redone == edited
    # The redo's fresh date is not a later change: the edit can be undone again.
    _call(state, "undo_last_change")
    assert list(state.sensor_mapping) == [80.0]


def test_the_build_that_puts_the_records_into_utc_cannot_be_undone(tmp_path: Path) -> None:
    state = _state(tmp_path)
    _call(state, "build_data_model", spec=_spec(1))
    with pytest.raises(ValueError, match="put the records into UTC, and undoing it would move every timestamp"):
        _call(state, "undo_last_change")


def test_undo_refuses_when_a_later_change_moved_the_mapping(tmp_path: Path) -> None:
    state = _state(tmp_path)
    _call(state, "build_data_model", spec=_spec(1))
    _call(state, "build_data_model", spec=_edited())
    state.sensor_mapping[82.0]["dir_col"] = None
    with pytest.raises(ValueError, match="moved the sensor mapping"):
        _call(state, "undo_last_change")


def test_a_campaigns_own_data_model_refuses_every_build(tmp_path: Path) -> None:
    state = _state(tmp_path)
    own = build_datamodel(_spec(1), available_columns=list(state.timeseries_df.columns))
    own["author"] = "Campaign operator"
    (tmp_path / "uploads" / "datamodel.json").write_text(json.dumps(own))
    _parse_datamodel(state, "datamodel.json")
    mapping = copy.deepcopy(state.sensor_mapping)

    with pytest.raises(ValueError, match="campaign's own data model, datamodel.json, is in use"):
        _call(state, "build_data_model", spec=_edited())
    assert state.sensor_mapping == mapping
    assert not (tmp_path / "uploads" / BUILT_DATAMODEL_FILENAME).exists()
    in_use = _call(state, "draft_data_model")["in_use"]
    assert in_use == {"file": "datamodel.json", "built": False, "spec": None}


def test_a_refused_build_leaves_the_document_as_it_was(tmp_path: Path) -> None:
    state = _state(tmp_path)
    _call(state, "build_data_model", spec=_spec(1))
    path = tmp_path / "uploads" / BUILT_DATAMODEL_FILENAME
    before = path.read_text()
    with pytest.raises(ValueError, match="this data model declares UTC\\+02:00"):
        _call(state, "build_data_model", spec=_spec(2))
    assert path.read_text() == before


def test_the_draft_reports_the_spec_in_use(tmp_path: Path) -> None:
    state = _state(tmp_path)
    assert _call(state, "draft_data_model")["in_use"] is None
    _call(state, "build_data_model", spec=_spec(1))
    assert _call(state, "draft_data_model")["in_use"]["spec"] == _spec(1)
