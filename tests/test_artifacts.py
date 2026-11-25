"""Artifacts and what each operation declares it reads and writes (P3-2, decisions/0015.2).

The declarations are the canvas's ports and the dependencies staleness follows, so they are
held to the code twice over, on every call the operation samples make
(``tests/operation_samples.py``): what a call changes in the session is among what its
operation declares it writes, and the first calls of each operation give the same answer
with every artifact it does not declare it reads removed beforehand.
"""
from __future__ import annotations

import copy
import functools
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from server.operations import REGISTRY
from server.state.artifacts import ARTIFACT_FIELDS, ARTIFACTS, LTC_ALGORITHMS, UNTRACKED_FIELDS, fingerprints
from server.state.session import SessionState, bind_session, get_active_session
from tests import operation_samples

#: Fields several artifacts split between them; each part is tested through its artifact's
#: own operations rather than by changing the whole field.
SHARED_FIELDS = frozenset({"runconfig", "timeseries_df", "era5_data", "merra_data", "reanalysis_interpolated"})

#: Calls of each operation probed for undeclared reads; later calls are only checked for
#: undeclared writes.
PROBED_CALLS = 1

#: Operations whose first call fills a cache on disk, and whose answer says whether it was a
#: cache hit: probed after one call has filled it.
WARM_CACHE: dict[str, str] = {
    "brighthub_download_reanalysis": "a node already downloaded is read from the project cache",
    "extract_era5_data": "a node already extracted is read from the EarthDataHub cache",
}

#: Declared writes no sample call makes, and why the declaration is still right.
_SAME_SITE = "the samples give it the coordinate, hub height or name the session already has"
_UNDO = (
    "undo and redo write what the undone operation wrote; the samples undo cleaning, a removal, "
    "a project name and a data model build"
)
WRITES_NOT_OBSERVED: dict[tuple[str, str], str] = {
    ("brighthub_prepare_reanalysis", "site"): _SAME_SITE,
    ("extrapolate_to_hub_height", "site"): _SAME_SITE,
    ("parse_datamodel", "site"): _SAME_SITE,
    ("parse_datamodel", "label"): _SAME_SITE,
    ("parse_datamodel", "measured_data"): "it converts records to UTC only when they are not yet; the samples' are",
    ("build_data_model", "measured_data"): "it converts records to UTC only when they are not yet; the samples' are",
    **{
        ("load_run_config", artifact): "the samples load the configuration they have just saved"
        for artifact in ("label", "settings", "site")
    },
    **{
        ("update_run_config", artifact): "a dotted key can name any of them; the samples change the project name"
        for artifact in ("data_model", "settings", "site")
    },
    **{
        (f"run_ltc_{algorithm}", "ltc_matching"): (
            "every correction records how it aligned the series; in the samples each aligns them as the first did"
        )
        for algorithm in ("total_least_squares", "speedsort", "variance_ratio", "xgboost")
    },
    **{
        (operation, artifact): _UNDO
        for operation in ("undo_last_change", "redo_last_change")
        for artifact in ("hub_height_series", "selections", "settings", "site")
    },
}


def _fresh() -> SessionState:
    state = SessionState()
    state.reset()
    return state


def test_every_session_field_belongs_to_an_artifact_or_is_listed_as_untracked() -> None:
    fields = set(vars(_fresh()))
    held = {field for owned in ARTIFACT_FIELDS.values() for field in owned}
    assert set(ARTIFACT_FIELDS) == set(ARTIFACTS)
    assert held.isdisjoint(UNTRACKED_FIELDS)
    assert held | set(UNTRACKED_FIELDS) == fields


def _probe_value(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return pd.DataFrame({"probe": [1.0]})
    if isinstance(value, dict):
        return {"probe": 1}
    if isinstance(value, list):
        return ["probe"]
    if isinstance(value, set):
        return {"probe"}
    return "probe"


@pytest.mark.parametrize(
    ("artifact", "field"),
    [
        (name, field)
        for name, fields in ARTIFACT_FIELDS.items()
        for field in fields
        if field not in SHARED_FIELDS and field != "ltc_results"
    ],
)
def test_changing_a_field_changes_its_artifact_digest(artifact: str, field: str) -> None:
    state = _fresh()
    before = ARTIFACTS[artifact].digest(state)
    setattr(state, field, _probe_value(getattr(state, field)))
    assert ARTIFACTS[artifact].digest(state) != before


@pytest.mark.parametrize("algorithm", LTC_ALGORITHMS)
def test_each_long_term_correction_is_its_own_artifact(algorithm: str) -> None:
    state = _fresh()
    before = fingerprints(state)
    state.ltc_results[algorithm] = {"long_term_mean_speed": 7.0}
    after = fingerprints(state)
    assert {name for name in before if before[name] != after[name]} == {f"ltc:{algorithm}"}


def test_a_hub_column_belongs_to_the_hub_series_not_the_measured_data() -> None:
    state = _fresh()
    index = pd.date_range("2024-01-01", periods=3, freq="10min", tz="UTC")
    state.timeseries_df = pd.DataFrame({"Spd_100m": [5.0, 6.0, 7.0]}, index=index)
    state.reanalysis_interpolated = {"era5": pd.DataFrame({"Spd_100m": [5.0, 6.0, 7.0]}, index=index)}
    before = fingerprints(state)
    state.timeseries_df["Spd_120m_hub"] = [5.5, 6.5, 7.5]
    state.reanalysis_interpolated["era5"]["Spd_120m_hub"] = [5.5, 6.5, 7.5]
    after = fingerprints(state)
    assert {name for name in before if before[name] != after[name]} == {"hub_height_series", "reanalysis_hub_series"}


def test_clearing_an_artifact_changes_only_its_own_digest() -> None:
    state = _fresh()
    index = pd.date_range("2024-01-01", periods=3, freq="10min", tz="UTC")
    state.timeseries_df = pd.DataFrame({"Spd_100m": [5.0, 6.0, 7.0], "Spd_120m_hub": [5.5, 6.5, 7.5]}, index=index)
    state.runconfig = {"project_name": "Mast", "hub_height_m": 120.0, "reference_source": "era5",
                       "site": {"timezone": "UTC"}}
    state.selections = {"north": {"definition": {}}}
    for name, artifact in ARTIFACTS.items():
        clone = copy.deepcopy(state)
        before = fingerprints(clone)
        artifact.clear(clone)
        after = fingerprints(clone)
        assert {key for key in before if before[key] != after[key]} <= {name}, name


def test_every_declaration_names_artifacts_and_a_read_writes_nothing() -> None:
    for declared in REGISTRY:
        assert set(declared.reads + declared.writes) <= set(ARTIFACTS), declared.name
        if declared.effect == "read":
            assert declared.writes == (), declared.name


def _normal(value: Any) -> Any:
    # A time the call ran is not part of its answer.
    if isinstance(value, dict):
        return {key: _normal(item) for key, item in value.items() if not str(key).endswith("_at")}
    if isinstance(value, list):
        return [_normal(item) for item in value]
    return value


def _outcome(function: Any, arguments: dict[str, Any]) -> Any:
    try:
        return _normal(json.loads(operation_samples.wire(function(**arguments))))
    except Exception as exc:  # noqa: BLE001 — a refusal is an answer too
        return ["error", type(exc).__name__, str(exc)]


class _Observed:
    def __init__(self) -> None:
        self.writes: dict[str, set[str]] = defaultdict(set)
        self.undeclared_writes: dict[str, set[str]] = defaultdict(set)
        self.undeclared_reads: dict[str, set[str]] = defaultdict(set)
        self.calls: dict[str, int] = defaultdict(int)


def _undeclared_reads(declared: Any, real: Any, state: SessionState, arguments: dict[str, Any]) -> set[str]:
    """Which undeclared artifacts the call reads: none if it answers the same with all of them
    removed at once; otherwise each is removed alone to name the ones that matter."""
    undeclared = sorted(set(ARTIFACTS) - set(declared.reads))

    def answer(removed: list[str]) -> Any:
        clone = copy.deepcopy(state)
        for name in removed:
            ARTIFACTS[name].clear(clone)
        with bind_session(clone):
            return _outcome(real, arguments)

    if declared.name in WARM_CACHE:
        answer([])
    expected = answer([])
    if answer(undeclared) == expected:
        return set()
    return {name for name in undeclared if answer([name]) != expected} or {"(only in combination)"}


def _instrument(observed: _Observed) -> dict[str, Any]:
    """Watch every operation's calls; returns the real functions, for putting back."""
    depth = [0]
    originals: dict[str, Any] = {}

    def watch(declared: Any, real: Any) -> Any:
        @functools.wraps(real)
        def watched(*args: Any, **arguments: Any) -> Any:
            if depth[0]:
                return real(*args, **arguments)
            depth[0] += 1
            try:
                state = get_active_session()
                observed.calls[declared.name] += 1
                if observed.calls[declared.name] <= PROBED_CALLS:
                    observed.undeclared_reads[declared.name] |= _undeclared_reads(
                        declared, real, copy.deepcopy(state), arguments
                    )
                before = fingerprints(state)
                result = real(*args, **arguments)
                after = fingerprints(state)
                changed = {key for key in before if before[key] != after[key]}
                observed.writes[declared.name] |= changed
                observed.undeclared_writes[declared.name] |= changed - set(declared.writes)
                return result
            finally:
                depth[0] -= 1

        return watched

    for declared in REGISTRY:
        originals[declared.name] = declared.fn
        object.__setattr__(declared, "fn", watch(declared, declared.fn))
    return originals


@pytest.fixture(scope="module")
def observed(tmp_path_factory: pytest.TempPathFactory) -> _Observed:
    found = _Observed()
    originals = _instrument(found)
    try:
        with pytest.MonkeyPatch.context() as monkeypatch:
            operation_samples.collect(Path(tmp_path_factory.mktemp("artifacts")), monkeypatch)
    finally:
        for declared in REGISTRY:
            object.__setattr__(declared, "fn", originals[declared.name])
    return found


def test_every_operation_is_called(observed: _Observed) -> None:
    assert {declared.name for declared in REGISTRY} <= set(observed.calls)


def test_no_call_changes_an_artifact_its_operation_does_not_declare_it_writes(observed: _Observed) -> None:
    assert {name: sorted(found) for name, found in observed.undeclared_writes.items() if found} == {}


def test_no_call_reads_an_artifact_its_operation_does_not_declare(observed: _Observed) -> None:
    assert {name: sorted(found) for name, found in observed.undeclared_reads.items() if found} == {}


def test_every_declared_write_is_made_by_some_call(observed: _Observed) -> None:
    unseen = {
        (declared.name, artifact)
        for declared in REGISTRY
        for artifact in declared.writes
        if artifact not in observed.writes[declared.name]
    }
    unexplained = sorted(unseen - set(WRITES_NOT_OBSERVED))
    assert not unexplained, "declared, never made, no reason given:\n" + "\n".join(map(str, unexplained))
    assert set(WRITES_NOT_OBSERVED) <= unseen, "made after all; remove the reason"
