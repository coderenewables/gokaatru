"""The order of a pipeline's steps follows what they read and write (P3-6, decisions/0015.2)."""
from __future__ import annotations

import random

import pytest

from server.core.pipeline import PipelineError, StepDeclaration, order_steps

DECLARED = {
    "shear_series": StepDeclaration(5, ("measured",), ("shear_series",)),
    "shear_table": StepDeclaration(5, ("shear_series",), ("shear_table",)),
    "aggregate_table": StepDeclaration(5, ("measured",), ("shear_series", "shear_table")),
    "hub": StepDeclaration(6, ("measured", "shear_table", "settings"), ("hub", "site")),
    "ltc_a": StepDeclaration(8, ("hub", "reference"), ("ltc_a", "matching")),
    "ltc_b": StepDeclaration(8, ("hub", "reference"), ("ltc_b", "matching")),
    "ensemble": StepDeclaration(10, ("ltc_a", "ltc_b"), ("ensemble",)),
    "weibull": StepDeclaration(13, ("measured",), ()),
}
DERIVED = frozenset({"shear_series", "shear_table", "hub", "ltc_a", "ltc_b", "ensemble"})


def _steps(*operations: str) -> list[dict]:
    return [{"id": f"s{index}", "operation": name} for index, name in enumerate(operations)]


def test_steps_given_in_any_order_run_writers_first() -> None:
    steps = _steps("ensemble", "ltc_b", "hub", "shear_table", "ltc_a", "shear_series")
    ordered = order_steps(steps, DECLARED, DERIVED)
    by_id = {step["id"]: step["operation"] for step in steps}
    assert [by_id[step_id] for step_id in ordered.order] == [
        "shear_series", "shear_table", "hub", "ltc_b", "ltc_a", "ensemble",
    ]
    assert ordered.inputs["s0"] == {"ltc_a": ("s4",), "ltc_b": ("s1",)}
    assert ordered.inputs["s2"]["measured"] == ()


def test_ties_break_on_stage_then_on_the_order_given() -> None:
    ordered = order_steps(_steps("weibull", "ltc_a", "hub", "shear_series", "shear_table"), DECLARED, DERIVED)
    assert ordered.order == ("s3", "s4", "s2", "s1", "s0")


def test_a_second_producer_of_a_result_is_refused_naming_both() -> None:
    with pytest.raises(PipelineError, match=r"shear_series by s0, s1; shear_table by s1, s2"):
        order_steps(_steps("shear_series", "aggregate_table", "shear_table"), DECLARED, DERIVED)


def test_several_writers_of_a_non_result_are_allowed() -> None:
    ordered = order_steps(_steps("ltc_a", "ltc_b"), DECLARED, DERIVED)
    assert ordered.order == ("s0", "s1")


def test_a_cycle_is_refused_naming_its_steps() -> None:
    declared = {
        "x": StepDeclaration(1, ("b",), ("a",)),
        "y": StepDeclaration(1, ("a",), ("b",)),
        "z": StepDeclaration(1, (), ("c",)),
    }
    with pytest.raises(PipelineError, match="Steps s0, s1 each wait for another"):
        order_steps(_steps("x", "y", "z"), declared, frozenset({"a", "b", "c"}))


@pytest.mark.parametrize("bad", [[{"id": "", "operation": "hub"}], _steps("hub") + _steps("hub")])
def test_ids_must_be_given_and_unique(bad: list[dict]) -> None:
    with pytest.raises(PipelineError, match="id"):
        order_steps(bad, DECLARED, DERIVED)


def test_an_unknown_operation_is_refused() -> None:
    with pytest.raises(PipelineError, match="no operation named 'nope'"):
        order_steps(_steps("nope"), DECLARED, DERIVED)


@pytest.mark.parametrize("seed", range(40))
def test_random_pipelines_respect_every_dependency(seed: int) -> None:
    # Random acyclic declarations: operation i reads only artifacts written by lower i.
    rng = random.Random(seed)
    declared = {}
    for index in range(rng.randint(2, 9)):
        reads = tuple(f"r{j}" for j in range(index) if rng.random() < 0.4)
        declared[f"op{index}"] = StepDeclaration(rng.randint(0, 3), reads, (f"r{index}",))
    names = list(declared)
    rng.shuffle(names)
    steps = _steps(*names)
    ordered = order_steps(steps, declared, frozenset(f"r{index}" for index in range(len(names))))
    at = {step_id: index for index, step_id in enumerate(ordered.order)}
    operation = {step["id"]: step["operation"] for step in steps}
    assert sorted(ordered.order) == sorted(step["id"] for step in steps)
    for reader in ordered.order:
        for writer in ordered.order:
            if set(declared[operation[reader]].reads) & set(declared[operation[writer]].writes):
                assert at[writer] < at[reader]
