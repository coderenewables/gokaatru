"""Disclosure fields are declared, documented and actually returned (P1-7, decisions/0009).

Every field an operation declares in ``disclosure`` must have a row in README's "Disclosure
fields" table, every field in that table must belong to a declared operation (or be listed
here as coming from somewhere else), and a synthetic pipeline run must find each declared
field in its operation's response.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from server.operations import REGISTRY
from server.state.session import bind_session
from tests.synthetic_pipeline import run_pipeline

README = Path(__file__).resolve().parents[1] / "README.md"

# Rows of the README table that no operation returns, and where they come from instead.
NOT_FROM_AN_OPERATION = {
    "duplicates_skipped": "the sweep manifest; the sweep engine is HTTP-only",
    "is_interpolation": "derive_uncertainty_inputs, called by the sweep",
    "provenance.is_interpolation": "derive_uncertainty_inputs, called by the sweep",
    "inputs": "names where is_interpolation sits in that row, not a field of its own",
    "extrapolate_reanalysis": "the sweep's extrapolate stage detail, not the tool's response",
    "reanalysis_status": "the sweep's extrapolate stage detail, not the tool's response",
    "selection": (
        "added by the operation wrapper when a selectable operation is given a selection; "
        "checked in tests/test_selection_operations.py"
    ),
}

# Declared fields a response carries only in some situations, and why this run does not.
CONDITIONAL = {
    ("run_clipping_analysis", "excluded_reason"): "only when a year fails the completeness gate",
    ("list_sweeps", "in_progress"): "only on a checkpoint of an unfinished sweep",
    ("brighthub_import_location", "upstream_processing"): "a network operation, not run here",
}


def _readme_fields() -> set[str]:
    text = README.read_text(encoding="utf-8")
    section = text.split("### Disclosure fields", 1)[1].split("\n### ", 1)[0]
    fields: set[str] = set()
    for line in section.splitlines():
        if not line.startswith("| `"):
            continue
        fields.update(re.findall(r"`([^`]+)`", line.split("|")[1]))
    return fields


def _declared() -> dict[str, set[str]]:
    return {op.name: set(op.disclosure) for op in REGISTRY if op.disclosure}


def test_every_declared_field_has_a_readme_row() -> None:
    documented = _readme_fields()
    undocumented = {
        f"{name}.{field}" for name, fields in _declared().items() for field in fields if field not in documented
    }
    assert undocumented == set()


def test_every_readme_row_belongs_to_an_operation_or_is_accounted_for() -> None:
    declared = set().union(*_declared().values())
    unclaimed = _readme_fields() - declared - set(NOT_FROM_AN_OPERATION)
    assert unclaimed == set()


# ---------------------------------------------------------------------------
# A synthetic pipeline, to see each declared field in a real response
# ---------------------------------------------------------------------------

def _paths(value: Any, prefix: str = "") -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            found.add(path)
            found |= _paths(item, path)
    elif isinstance(value, list):
        for item in value:
            found |= _paths(item, prefix)
    return found


def _carries(response: Any, field: str) -> bool:
    return any(path == field or path.endswith(f".{field}") for path in _paths(response))


#: Operations the pipeline does not run, called after it on its analysed session: a sweep
#: scenario's steps (P3-7b), which would replace the pipeline's own table and uncertainty.
AFTER_THE_PIPELINE: dict[str, dict[str, Any]] = {
    "calculate_scenario_uncertainty": {
        "algorithm": "variance_ratio", "shear_model": "power_law_mean", "reference_heights": [80.0, 100.0],
    },
    "build_constant_shear_table": {"alpha": 0.2},
}


@pytest.fixture(scope="module")
def responses(tmp_path_factory) -> dict[str, Any]:
    state, calls = run_pipeline(tmp_path_factory.mktemp("disclosure"))
    found = {name: result for name, _, result in calls}
    with bind_session(state):
        for name, arguments in AFTER_THE_PIPELINE.items():
            found[name] = REGISTRY.get(name).fn(**arguments)
    return found


@pytest.mark.parametrize(
    ("name", "field"),
    sorted((op.name, field) for op in REGISTRY for field in op.disclosure),
)
def test_a_declared_field_is_in_its_operations_response(responses, name: str, field: str) -> None:
    if (name, field) in CONDITIONAL:
        pytest.skip(CONDITIONAL[(name, field)])
    assert name in responses, f"the synthetic pipeline does not run {name}"
    assert _carries(responses[name], field), f"{name} did not return {field}"
