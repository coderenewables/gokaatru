"""Results of the pipeline operations (P3-6)."""
from __future__ import annotations

from typing import Any

from server.schemas.results._base import Number, Result


class PipelineEdge(Result):
    source: str
    target: str
    #: What the source writes and the target reads.
    artifact: str


class StepReport(Result):
    operation: str
    #: current, changed, stale, not_run, upstream, invalid or ready (``server/tools/pipelines.py``).
    status: str
    #: For each artifact the step reads, the steps of the pipeline that write it; none when it
    #: comes from the session.
    inputs: dict[str, list[str]]
    outputs: list[str]
    #: As a call would log them, defaults filled in; absent when they do not fit.
    parameters: dict[str, Any] | None = None
    reason: str | None = None
    errors: list[str] | None = None
    #: For ``upstream``: the steps it waits for.
    waiting_on: list[str] | None = None


class OrderPipelineResult(Result):
    order: list[str]
    edges: list[PipelineEdge]
    steps: dict[str, StepReport]
    #: The steps a "Run stale" would run, in order.
    to_run: list[str]


class SavedPipeline(Result):
    name: str
    steps: list[dict[str, Any]]
    actor: str | None
    saved_at: str | None


class SavePipelineResult(SavedPipeline):
    status: str
    replaced: bool


class DeletePipelineResult(Result):
    status: str
    deleted: str


class ListPipelinesResult(Result):
    pipelines: list[SavedPipeline]


class ScenarioAxes(Result):
    shear_fit_policy: str | None
    reference_policy: str | None
    shear_model: str
    reference_source: str
    ltc_algorithm: str
    hub_height_m: Number
    analyst_shear_alpha: Number


class PipelineFromScenarioResult(Result):
    sweep_id: str
    config_hash: str
    scenario: ScenarioAxes
    steps: list[dict[str, Any]]
    #: Whether the campaign is as the sweep found it (its fixed-prefix hash); when not, the
    #: steps run on today's session and will not reproduce the row.
    prefix_matches: bool
    prefix_note: str | None = None


class SweepSpecLevels(Result):
    shear_fit_policies: list[str]
    reference_policies: list[str]
    shear_models: list[str]
    reference_sources: list[str]
    ltc_algorithms: list[str]
    hub_height_m: Number
    analyst_shear_alpha: Number


class UnmatchedChoice(Result):
    axis: str
    why: str


class SweepSpecFromPipelineResult(Result):
    spec: SweepSpecLevels
    #: Choices no sweep level expresses; each such axis takes the sweep's default.
    unmatched: list[UnmatchedChoice]
