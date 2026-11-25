"""Results of the pipeline operations (P3-6)."""
from __future__ import annotations

from typing import Any

from server.schemas.results._base import Result


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
