"""sweep — expand a scenario space, run it, and persist every scenario's record.

The engine's job (design doc §7.6): take a specification of which axis levels to cross,
build the leaves, run each in isolation, judge it, and write out a table plus one
materialised runconfig per scenario.

**Leaves are grouped by prefix, not run independently.** Every LTC choice downstream of a
given ``(shear-fit set, shear model)`` pair shares that pair's shear table and hub series,
so running N independent pipelines recomputes the most expensive upstream stage once per
downstream choice. Grouping is what turns thousands of leaves into tens of shear
computations (design doc §5).

**Nothing is dropped.** A scenario that cannot run becomes a row with ``status="failed"``
and the stage that refused. A sweep that silently omits what it could not compute reports
a spread over a set nobody can enumerate.

**Retention is total.** 90 scenarios means 90 runconfigs, kept, mapped through a manifest
and downloadable individually or together (design doc §7.13). A pruning policy would
delete exactly the file the analyst turns out to need.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from queue import Queue
from typing import Any, Callable, Iterator
from uuid import uuid4

from server.core.admissibility import DEFAULT_THRESHOLDS, GateThresholds, evaluate_gates
from server.core.scenario_context import SHEAR_STAGE_FIELDS, scenario_context
from server.core.scenario_pipeline import (
    ScenarioError,
    ScenarioSpec,
    build_shear,
    extrapolate,
    resolve_sensors,
    run_ltc,
    run_uncertainty,
)
from server.core.scenario_result import (
    ScenarioResult,
    build_result,
    failed_result,
    fixed_prefix_hash,
    scenario_runconfig,
)


@dataclass(frozen=True)
class SweepSpec:
    """Which levels of each axis to cross (design doc §4)."""

    shear_fit_policies: tuple[str, ...]
    reference_policies: tuple[str, ...]
    shear_models: tuple[str, ...]
    reference_sources: tuple[str, ...]
    ltc_algorithms: tuple[str, ...]
    hub_height_m: float | None = None
    analyst_shear_alpha: float | None = None

    def leaves(self) -> list[ScenarioSpec]:
        """Expand the full factorial over the selected levels."""
        return [
            ScenarioSpec(
                shear_fit_policy=fit,
                reference_policy=reference,
                shear_model=model,
                reference_source=source,
                ltc_algorithm=algorithm,
                hub_height_m=self.hub_height_m,
                analyst_shear_alpha=self.analyst_shear_alpha,
            )
            for fit, model in product(self.shear_fit_policies, self.shear_models)
            for reference in self.reference_policies
            for source in self.reference_sources
            for algorithm in self.ltc_algorithms
        ]

    def leaf_count(self) -> int:
        """Return the nominal leaf count, for the designer's cost counter (§9.1)."""
        return (
            len(self.shear_fit_policies)
            * len(self.reference_policies)
            * len(self.shear_models)
            * len(self.reference_sources)
            * len(self.ltc_algorithms)
        )

    def prefix_count(self) -> int:
        """Return how many shear tables the sweep actually needs.

        The number that makes the leaf count affordable, and the one worth showing beside
        it — a user who sees 8,960 leaves and 40 shear computations understands the shape
        of the run in a way the leaf count alone does not convey.
        """
        return len(self.shear_fit_policies) * len(self.shear_models)

    def as_runconfig(self) -> dict[str, Any]:
        return {
            "shear_fit_policies": list(self.shear_fit_policies),
            "reference_policies": list(self.reference_policies),
            "shear_models": list(self.shear_models),
            "reference_sources": list(self.reference_sources),
            "ltc_algorithms": list(self.ltc_algorithms),
            "hub_height_m": self.hub_height_m,
            "analyst_shear_alpha": self.analyst_shear_alpha,
            "leaf_count": self.leaf_count(),
            "prefix_count": self.prefix_count(),
        }


@dataclass
class SweepProgress:
    """A progress event, shaped for the SSE stream the Run Monitor consumes (§9.2)."""

    event: str
    completed: int
    total: int
    config_hash: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    #: Set on ``sweep_finished`` only. The client mints no sweep id of its own, so this
    #: is its only route from a finished run back to the persisted table.
    manifest: dict[str, Any] | None = None

    def as_record(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "completed": self.completed,
            "total": self.total,
            "config_hash": self.config_hash,
            **({"detail": self.detail} if self.detail else {}),
            **({"manifest": self.manifest} if self.manifest is not None else {}),
        }


ProgressCallback = Callable[[SweepProgress], None]


def _sweep_dir(state: Any, sweep_id: str) -> Path:
    return Path(state.get_data_dir()) / "sweeps" / sweep_id


def run_sweep(
    base_state: Any,
    spec: SweepSpec,
    *,
    thresholds: GateThresholds = DEFAULT_THRESHOLDS,
    sweep_id: str | None = None,
    on_progress: ProgressCallback | None = None,
    should_stop: Callable[[], bool] | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Run every leaf of a sweep and return its manifest.

    ``should_stop`` is polled between scenarios so a cancel takes effect promptly without
    interrupting a scenario mid-computation and leaving a half-written record.
    """
    identifier = sweep_id or uuid4().hex[:12]
    leaves = spec.leaves()
    prefix = fixed_prefix_hash(base_state)
    results: list[ScenarioResult] = []
    runconfigs: dict[str, dict[str, Any]] = {}
    started_at = datetime.now(timezone.utc)

    def emit(
        event: str,
        config_hash: str | None = None,
        *,
        manifest: dict[str, Any] | None = None,
        **detail: Any,
    ) -> None:
        if on_progress is not None:
            on_progress(
                SweepProgress(event, len(results), len(leaves), config_hash, detail, manifest)
            )

    emit("sweep_started")
    stopped = False
    for shear_key, group in _by_shear_prefix(leaves).items():
        if stopped:
            break
        emit("prefix_started", shear_prefix=list(shear_key))
        try:
            with scenario_context(base_state) as prefix_state:
                fit, _reference = resolve_sensors(prefix_state, group[0])
                build_shear(prefix_state, group[0], fit)
                emit("prefix_completed", shear_prefix=list(shear_key))
                for leaf in group:
                    if should_stop is not None and should_stop():
                        stopped = True
                        emit("sweep_stopped")
                        break
                    result, config = _run_leaf(prefix_state, leaf, prefix, thresholds)
                    results.append(result)
                    if config is not None:
                        runconfigs[result.config_hash] = config
                    emit(
                        "scenario_failed" if result.status == "failed" else "scenario_completed",
                        result.config_hash,
                        admissible=result.admissible,
                        error=result.error,
                    )
        except ScenarioError as error:
            # The shear stage failed, so every leaf sharing this prefix fails with it —
            # recorded individually so the table still enumerates the whole space.
            for leaf in group:
                results.append(
                    failed_result(leaf.as_runconfig(), prefix, error.stage, error.message)
                )
                emit("scenario_failed", results[-1].config_hash, error=error.message)

    manifest = _manifest(
        identifier, spec, thresholds, prefix, results, started_at, stopped=stopped
    )
    if persist:
        _persist(base_state, identifier, manifest, results, runconfigs)
    # Carried on the event, not merely returned: a streaming caller never sees the return
    # value, and without the id it cannot ask for the table that was just written.
    emit("sweep_finished", manifest=manifest)
    return {"manifest": manifest, "results": [result.as_row() for result in results]}


def _by_shear_prefix(leaves: list[ScenarioSpec]) -> dict[tuple[Any, ...], list[ScenarioSpec]]:
    """Group leaves by the inputs their shear table depends on.

    The table is a function of the shear-fit sensor set, the shear model, and any
    analyst-supplied exponent — nothing downstream. Every leaf in a group can therefore
    reuse one computation (design doc §5).
    """
    groups: dict[tuple[Any, ...], list[ScenarioSpec]] = {}
    for leaf in leaves:
        key = (leaf.shear_fit_policy, leaf.shear_model, leaf.analyst_shear_alpha)
        groups.setdefault(key, []).append(leaf)
    return groups


def _run_leaf(
    prefix_state: Any,
    leaf: ScenarioSpec,
    prefix: str,
    thresholds: GateThresholds,
) -> tuple[ScenarioResult, dict[str, Any] | None]:
    """Run one leaf from a prefix whose shear stage is already built.

    The fork carries the shear artefacts over rather than rebuilding them, and still
    isolates everything the leaf writes — so a leaf cannot disturb the prefix its
    siblings are about to reuse.
    """
    try:
        with scenario_context(prefix_state, keep_derived=SHEAR_STAGE_FIELDS) as scenario:
            _fit, reference = resolve_sensors(scenario, leaf)
            stages = [
                extrapolate(scenario, leaf, reference),
                run_ltc(scenario, leaf),
                run_uncertainty(scenario, leaf, reference),
            ]
            record = {
                "spec": leaf.as_runconfig(),
                "sensor_selection": {
                    "shear_fit": _fit.to_runconfig(),
                    "extrapolation_reference": reference.to_runconfig(),
                },
                "stages": {"build_shear": _prefix_shear_detail(scenario, leaf)}
                | {stage.stage: stage.detail for stage in stages},
            }
            report = evaluate_gates(scenario, record, thresholds)
            result = build_result(scenario, record, report)
            config = scenario_runconfig(scenario, record, result, thresholds)
            return result, config
    except ScenarioError as error:
        return failed_result(leaf.as_runconfig(), prefix, error.stage, error.message), None
    except Exception as error:  # noqa: BLE001 — one bad leaf must not end the sweep
        return failed_result(leaf.as_runconfig(), prefix, "unexpected", repr(error)), None


def _prefix_shear_detail(scenario: Any, leaf: ScenarioSpec) -> dict[str, Any]:
    """Describe the shear stage a leaf inherited, so its record is not missing a stage."""
    method = "log_law" if leaf.shear_model.startswith("log_law") else "power_law"
    source = "analyst_supplied" if leaf.analyst_shear_alpha is not None else "fitted"
    detail: dict[str, Any] = {
        "method": method,
        "shear_source": source,
        "reused_from_prefix": True,
    }
    if leaf.analyst_shear_alpha is not None:
        detail["alpha"] = float(leaf.analyst_shear_alpha)
    return detail


def _manifest(
    sweep_id: str,
    spec: SweepSpec,
    thresholds: GateThresholds,
    prefix: str,
    results: list[ScenarioResult],
    started_at: datetime,
    *,
    stopped: bool,
) -> dict[str, Any]:
    """Build the mapping from result row to runconfig file (design doc §7.13)."""
    completed = [result for result in results if result.status == "ok"]
    admissible = [result for result in completed if result.admissible]

    # Which gate did the excluded scenarios trip, and how often? A sweep where every
    # scenario fails the same gate has not measured a spread — it has measured a
    # threshold. Reported on the manifest because the alternative is an empty
    # distribution with nothing saying why, which reads as "no signal" rather than
    # "your admissibility rule excluded everything".
    tally: dict[str, int] = {}
    for result in completed:
        for name in result.failures:
            tally[name] = tally.get(name, 0) + 1
    diagnosis = None
    if completed and not admissible:
        worst = max(tally.items(), key=lambda item: item[1], default=(None, 0))
        diagnosis = (
            f"No scenario was admissible: all {len(completed)} completed scenarios failed at "
            f"least one gate"
            + (
                f", most often '{worst[0]}' ({worst[1]} of {len(completed)})."
                if worst[0]
                else "."
            )
            + " There is no spread to report. Either this campaign genuinely does not "
            "support the analysis, or a threshold is wrong for this site — check the gate "
            "tally before widening the sweep."
        )

    return {
        "sweep_id": sweep_id,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "stopped_early": stopped,
        "fixed_prefix_hash": prefix,
        "spec": spec.as_runconfig(),
        "thresholds": thresholds.as_runconfig(),
        "counts": {
            "planned": spec.leaf_count(),
            "run": len(results),
            "completed": len(completed),
            "failed": len(results) - len(completed),
            "admissible": len(admissible),
            "inadmissible": len(completed) - len(admissible),
        },
        "gate_failures": dict(sorted(tally.items(), key=lambda item: -item[1])),
        "diagnosis": diagnosis,
        "scenarios": [
            {
                "config_hash": result.config_hash,
                "status": result.status,
                "admissible": result.admissible,
                "runconfig": f"scenarios/{result.config_hash}/runconfig.json",
                **result.axes,
            }
            for result in results
        ],
    }


def _persist(
    base_state: Any,
    sweep_id: str,
    manifest: dict[str, Any],
    results: list[ScenarioResult],
    runconfigs: dict[str, dict[str, Any]],
) -> Path:
    """Write the manifest, the result table and every scenario runconfig."""
    root = _sweep_dir(base_state, sweep_id)
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    (root / "results.json").write_text(
        json.dumps([result.as_row() for result in results], indent=2, default=str), encoding="utf-8"
    )
    for config_hash, config in runconfigs.items():
        scenario_dir = root / "scenarios" / config_hash
        scenario_dir.mkdir(parents=True, exist_ok=True)
        (scenario_dir / "runconfig.json").write_text(
            json.dumps(config, indent=2, default=str), encoding="utf-8"
        )
    return root


def load_sweep(base_state: Any, sweep_id: str) -> dict[str, Any]:
    """Read back a persisted sweep's manifest and result table."""
    root = _sweep_dir(base_state, sweep_id)
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        raise ValueError(f"Sweep '{sweep_id}' is not available")
    return {
        "manifest": json.loads(manifest_path.read_text(encoding="utf-8")),
        "results": json.loads((root / "results.json").read_text(encoding="utf-8")),
    }


def load_scenario_runconfig(base_state: Any, sweep_id: str, config_hash: str) -> dict[str, Any]:
    """Read one scenario's materialised runconfig — the file an analyst takes away."""
    path = _sweep_dir(base_state, sweep_id) / "scenarios" / config_hash / "runconfig.json"
    if not path.exists():
        raise ValueError(f"Scenario '{config_hash}' is not available in sweep '{sweep_id}'")
    return json.loads(path.read_text(encoding="utf-8"))


def list_sweeps(base_state: Any) -> list[dict[str, Any]]:
    """Summarise every persisted sweep, newest first."""
    root = Path(base_state.get_data_dir()) / "sweeps"
    if not root.is_dir():
        return []
    summaries: list[dict[str, Any]] = []
    for child in root.iterdir():
        manifest_path = child / "manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        summaries.append(
            {
                "sweep_id": manifest.get("sweep_id", child.name),
                "started_at": manifest.get("started_at"),
                "finished_at": manifest.get("finished_at"),
                "counts": manifest.get("counts", {}),
                "fixed_prefix_hash": manifest.get("fixed_prefix_hash"),
            }
        )
    return sorted(summaries, key=lambda entry: str(entry.get("started_at")), reverse=True)


def iter_progress(
    base_state: Any, spec: SweepSpec, **kwargs: Any
) -> Iterator[dict[str, Any]]:
    """Run a sweep, yielding progress records **as they occur**.

    The sweep runs on a worker thread and its callback feeds a queue this generator
    drains, so an event reaches the client at the moment the scenario finishes. Collecting
    the events and replaying them afterwards would satisfy the same signature while
    delivering nothing until the run was already over — which is precisely what the Run
    Monitor exists to avoid (design doc §9.2).

    Scenario state is bound through a ``ContextVar``, so running on another thread is safe:
    the worker gets its own binding and cannot disturb the caller's session.
    """
    queue: Queue[dict[str, Any] | None] = Queue()
    outcome: dict[str, Any] = {}

    def worker() -> None:
        try:
            outcome["result"] = run_sweep(
                base_state,
                spec,
                on_progress=lambda event: queue.put(event.as_record()),
                **kwargs,
            )
        except Exception as error:  # noqa: BLE001 — surfaced to the client as an event
            outcome["error"] = repr(error)
        finally:
            queue.put(None)

    thread = threading.Thread(target=worker, name="gokaatru-sweep", daemon=True)
    thread.start()
    while True:
        event = queue.get()
        if event is None:
            break
        yield event
    thread.join()

    if "error" in outcome:
        yield {"event": "sweep_error", "error": outcome["error"]}
        return
    yield {"event": "sweep_result", "manifest": outcome["result"]["manifest"]}
