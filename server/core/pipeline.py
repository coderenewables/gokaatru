"""pipeline — the order a pipeline's steps run in, from what each reads and writes.

A pipeline is the campaign's one chosen chain (decisions/0015.1): a list of steps, each an
operation with its parameters. The steps are not wired by hand. Each operation declares the
artifacts it reads and writes (decisions/0015.2), so a step that reads what another writes
runs after it, and the order follows from the declarations alone; F-09's drawn edges, which
said one thing while the session said another, have nothing left to disagree with.

One step produces each derived result: two steps that would both build the shear table are
refused, naming both, rather than one silently overwriting the other. Artifacts that are not
results (the configuration, how a correction aligned its series) may be written by several
steps, and order only those that read them. A cycle is refused, naming its steps.

Pure: the declarations come in as data, so this module knows nothing of the registry or the
session.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


class PipelineError(ValueError):
    """A pipeline that cannot be ordered as given."""


@dataclass(frozen=True)
class StepDeclaration:
    """What ordering needs to know about a step's operation."""

    stage_rank: int
    reads: tuple[str, ...]
    writes: tuple[str, ...]


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    artifact: str


@dataclass(frozen=True)
class Ordered:
    #: Step ids in the order they run.
    order: tuple[str, ...]
    edges: tuple[Edge, ...]
    #: For each step and each artifact it reads, the steps of this pipeline that write it;
    #: none when it comes from the session as it stands.
    inputs: dict[str, dict[str, tuple[str, ...]]]


def _step_ids(steps: Sequence[Mapping[str, Any]]) -> list[str]:
    ids = [str(step.get("id", "")) for step in steps]
    if any(not step_id for step_id in ids):
        raise PipelineError("Every step needs an id")
    repeated = sorted({step_id for step_id in ids if ids.count(step_id) > 1})
    if repeated:
        raise PipelineError(f"Step ids must be unique; repeated: {', '.join(repeated)}")
    return ids


def order_steps(
    steps: Sequence[Mapping[str, Any]],
    declarations: Mapping[str, StepDeclaration],
    derived: frozenset[str],
) -> Ordered:
    """Order ``steps`` (each ``{"id", "operation", ...}``) by what they read and write.

    ``declarations`` maps an operation's name to its declaration; ``derived`` names the
    artifacts that are results, of which one step may produce each.
    """
    ids = _step_ids(steps)
    operation_of: dict[str, str] = {}
    for step_id, step in zip(ids, steps):
        name = str(step.get("operation", ""))
        if name not in declarations:
            raise PipelineError(f"Step '{step_id}': no operation named '{name}' can be a pipeline step")
        operation_of[step_id] = name

    writers: dict[str, list[str]] = {}
    for step_id in ids:
        for artifact in declarations[operation_of[step_id]].writes:
            writers.setdefault(artifact, []).append(step_id)
    conflicts = {artifact: found for artifact, found in writers.items() if artifact in derived and len(found) > 1}
    if conflicts:
        detail = "; ".join(
            f"{artifact} by {', '.join(found)}" for artifact, found in sorted(conflicts.items())
        )
        raise PipelineError(f"One step produces each result; more than one would build {detail}")

    edges: list[Edge] = []
    inputs: dict[str, dict[str, tuple[str, ...]]] = {step_id: {} for step_id in ids}
    for step_id in ids:
        for artifact in declarations[operation_of[step_id]].reads:
            sources = tuple(writer for writer in writers.get(artifact, []) if writer != step_id)
            inputs[step_id][artifact] = sources
            edges.extend(Edge(writer, step_id, artifact) for writer in sources)

    position = {step_id: index for index, step_id in enumerate(ids)}
    rank = {step_id: (declarations[operation_of[step_id]].stage_rank, position[step_id]) for step_id in ids}
    waiting = {step_id: {edge.source for edge in edges if edge.target == step_id} for step_id in ids}
    order: list[str] = []
    while len(order) < len(ids):
        ready = sorted((step_id for step_id in ids if step_id not in order and not waiting[step_id]), key=rank.get)
        if not ready:
            cycle = sorted(step_id for step_id in ids if step_id not in order)
            raise PipelineError(
                f"Steps {', '.join(cycle)} each wait for another: what one writes another reads, round in a circle"
            )
        chosen = ready[0]
        order.append(chosen)
        for pending in waiting.values():
            pending.discard(chosen)
    return Ordered(order=tuple(order), edges=tuple(edges), inputs=inputs)
