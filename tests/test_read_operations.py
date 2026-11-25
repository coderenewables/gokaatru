"""A read changes nothing, on a fully analysed session (P1-19a).

``tests/test_operation_routes.py`` checks each read on a mast with no reanalysis, where every
read past the measured data refuses before it could write anything. Here every read runs on
the synthetic pipeline's session, which holds every result the reads consume, and the whole
session must be as it was afterwards: every frame, every result, every version stamp. Only
the operation log may grow, since it records the call.
"""
from __future__ import annotations

import hashlib
import inspect
from typing import Any

import numpy as np
import pandas as pd
import pytest
from pydantic import BaseModel

from server.operations import REGISTRY
from server.state.session import SessionState, bind_session
from tests.synthetic_pipeline import NORTH, READ_ARGUMENTS, run_pipeline

# Fields a read may change by design.
MAY_CHANGE = {"operation_log": "every call is logged", "updated_at": "not set by reads; listed for completeness"}
READS = sorted(op.name for op in REGISTRY if op.effect == "read" and not op.network)


def _digest(value: Any) -> Any:
    if isinstance(value, (pd.DataFrame, pd.Series)):
        frame = value.to_frame() if isinstance(value, pd.Series) else value
        hashed = pd.util.hash_pandas_object(frame, index=True).to_numpy()
        return ("frame", tuple(map(str, frame.columns)), hashlib.sha256(hashed.tobytes()).hexdigest())
    if isinstance(value, np.ndarray):
        return ("array", value.shape, hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest())
    if isinstance(value, BaseModel):
        return _digest(value.model_dump())
    if isinstance(value, dict):
        return {str(key): _digest(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_digest(item) for item in value]
    if isinstance(value, float) and np.isnan(value):
        return "nan"
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return repr(value)


def _snapshot(state: SessionState) -> dict[str, Any]:
    return {name: _digest(value) for name, value in vars(state).items() if name not in MAY_CHANGE}


@pytest.fixture(scope="module")
def analysed(tmp_path_factory) -> SessionState:
    state, _ = run_pipeline(tmp_path_factory.mktemp("reads"))
    with bind_session(state):
        REGISTRY.get("define_selection").fn(name="north", definition=NORTH)
    return state


@pytest.mark.parametrize("name", READS)
def test_a_read_leaves_the_analysed_session_as_it_found_it(name: str, analysed: SessionState) -> None:
    declared = REGISTRY.get(name)
    arguments = {
        parameter.name: READ_ARGUMENTS[parameter.name]
        for parameter in inspect.signature(declared.fn).parameters.values()
        if parameter.default is inspect.Parameter.empty
    }
    before = _snapshot(analysed)
    with bind_session(analysed):
        declared.fn(**arguments)
    after = _snapshot(analysed)
    changed = sorted(field for field in before.keys() | after.keys() if before.get(field) != after.get(field))
    assert changed == [], f"{name} changed {changed}"
