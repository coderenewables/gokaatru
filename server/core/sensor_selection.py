"""sensor_selection — resolve a sensor-selection *policy* to concrete sensors.

Axis A of the analysis engine (design doc §3.A) asks which sensors a scenario fits
its shear profile on (A1) and which it extrapolates from (A2). Before this module
neither was expressible: ``_speed_height_map`` took *every* mapped sensor and
``_nearest_indices`` picked the nearest valid one per record, so "nearest 2" or
"everything above 90% availability" could not be stated at all.

Four policies, deliberately non-redundant — each probes a different failure mode:

======================  ====================================================
``nearest_2``           shortest extrapolation lever
``availability_90``     maximum data volume
``redundant_boom``      heights free of single-boom flow distortion
``widest_lever``        best-conditioned alpha fit
======================  ====================================================

**Policies resolve to concrete sensors, and the resolution travels with the
result.** A scenario runconfig records the policy name *and* the heights and
columns it resolved to (design doc §7.13), so a result stays interpretable even if
this resolver's behaviour later changes, and so two policies that happen to resolve
identically on a given mast can be deduplicated on what they resolved to rather
than on what they were called.

**Applicability is derived, never assumed.** ``redundant_boom`` is meaningless on a
lidar and cannot fit a shear exponent from a single height; both facts fall out of
the sensor inventory rather than the analyst having to know them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

NEAREST_2 = "nearest_2"
AVAILABILITY_90 = "availability_90"
REDUNDANT_BOOM = "redundant_boom"
WIDEST_LEVER = "widest_lever"

POLICIES: tuple[str, ...] = (NEAREST_2, AVAILABILITY_90, REDUNDANT_BOOM, WIDEST_LEVER)

#: Availability floor for ``availability_90``, as a percentage of total records.
AVAILABILITY_THRESHOLD_PCT = 90.0

#: A shear exponent needs two distinct heights; ln(z2/z1) is zero otherwise.
MIN_HEIGHTS_FOR_SHEAR_FIT = 2


@dataclass(frozen=True)
class SensorSelection:
    """One policy resolved against one session's sensors."""

    policy: str
    heights_m: tuple[float, ...] = ()
    columns: tuple[str, ...] = ()
    available: bool = True
    reason: str | None = None
    detail: dict[str, object] = field(default_factory=dict)

    @property
    def can_fit_shear(self) -> bool:
        """Whether this selection spans enough distinct heights to fit an exponent.

        False means the scenario needs an analyst-supplied shear value rather than a
        fitted one (design doc §3.A.1) — it does not mean the selection is unusable,
        because a single height is still a valid *extrapolation reference*.
        """
        return self.available and len(self.heights_m) >= MIN_HEIGHTS_FOR_SHEAR_FIT

    def to_runconfig(self) -> dict[str, object]:
        """Return the record written into a scenario runconfig for this selection."""
        return {
            "policy": self.policy,
            "available": self.available,
            "reason": self.reason,
            "resolved_heights_m": list(self.heights_m),
            "resolved_columns": list(self.columns),
            "can_fit_shear": self.can_fit_shear,
            **({"detail": self.detail} if self.detail else {}),
        }


def _unavailable(policy: str, reason: str, **detail: object) -> SensorSelection:
    """Return a selection that says why it cannot be used, rather than resolving to nothing."""
    return SensorSelection(policy=policy, available=False, reason=reason, detail=dict(detail))


def _speed_columns_by_height(state) -> dict[float, str]:
    """Return the mapped speed column for every height that has one in the loaded data."""
    if state.timeseries_df is None:
        return {}
    return {
        float(height): str(slots["speed_col"])
        for height, slots in state.sensor_mapping.items()
        if slots.get("speed_col") in state.timeseries_df.columns
    }


def availability_pct(state, column: str) -> float:
    """Return a column's non-null share of the loaded record count, as a percentage."""
    if state.timeseries_df is None or column not in state.timeseries_df.columns:
        return 0.0
    total = len(state.timeseries_df)
    if total == 0:
        return 0.0
    return float(state.timeseries_df[column].notna().sum()) / total * 100.0


def redundant_boom_heights(state) -> dict[float, list[str]]:
    """Return heights carrying more than one wind-speed sensor, with their sensor names.

    Read from ``sensor_inventory``, which lists every named measurement point, rather
    than from ``sensor_mapping`` — the mapping has already collapsed each boom pair to
    a single chosen sensor via ``_resolve_boom_pair``, so the redundancy is invisible
    there by construction.
    """
    by_height: dict[float, list[str]] = {}
    for name, metadata in (state.sensor_inventory or {}).items():
        if str(metadata.get("sensor_type")) != "wind_speed":
            continue
        height = metadata.get("height_m")
        if not isinstance(height, (int, float)):
            continue
        by_height.setdefault(float(height), []).append(str(name))
    return {height: sorted(names) for height, names in by_height.items() if len(names) > 1}


def _resolve_nearest_2(state, heights: dict[float, str], hub_height_m: float | None) -> SensorSelection:
    """Pick the two heights closest to hub height."""
    if hub_height_m is None:
        return _unavailable(
            NEAREST_2,
            "Hub height is not set, so 'nearest to hub' has nothing to measure against.",
        )
    ordered = sorted(heights, key=lambda h: (abs(h - hub_height_m), -h))
    chosen = tuple(sorted(ordered[:2]))
    return SensorSelection(
        policy=NEAREST_2,
        heights_m=chosen,
        columns=tuple(heights[h] for h in chosen),
        detail={
            "hub_height_m": float(hub_height_m),
            "distance_to_hub_m": [round(abs(h - hub_height_m), 3) for h in chosen],
        },
    )


def _resolve_availability(state, heights: dict[float, str]) -> SensorSelection:
    """Take every height whose speed column clears the availability floor."""
    measured = {h: availability_pct(state, column) for h, column in heights.items()}
    chosen = tuple(sorted(h for h, pct in measured.items() if pct >= AVAILABILITY_THRESHOLD_PCT))
    if not chosen:
        best = max(measured.values(), default=0.0)
        return _unavailable(
            AVAILABILITY_90,
            f"No sensor reaches {AVAILABILITY_THRESHOLD_PCT:g}% availability "
            f"(best is {best:.1f}%).",
            availability_pct={str(h): round(pct, 2) for h, pct in sorted(measured.items())},
        )
    return SensorSelection(
        policy=AVAILABILITY_90,
        heights_m=chosen,
        columns=tuple(heights[h] for h in chosen),
        detail={
            "threshold_pct": AVAILABILITY_THRESHOLD_PCT,
            "availability_pct": {str(h): round(measured[h], 2) for h in chosen},
            "excluded_heights_m": [h for h in sorted(measured) if h not in chosen],
        },
    )


def _resolve_redundant_boom(state, heights: dict[float, str]) -> SensorSelection:
    """Take the heights that carry boom redundancy, if any do."""
    redundant = redundant_boom_heights(state)
    usable = tuple(sorted(h for h in redundant if h in heights))
    if not usable:
        measurement_type = state.get_measurement_type() or "unknown"
        if not state.sensor_inventory:
            reason = (
                "No sensor inventory is loaded, so boom redundancy cannot be "
                "determined. A data model with named measurement points is required."
            )
        else:
            reason = (
                f"No height carries more than one wind-speed sensor, so there is no boom "
                f"redundancy to select on (measurement type: {measurement_type}). This is "
                "expected for a lidar or profiler, which has no booms."
            )
        return _unavailable(REDUNDANT_BOOM, reason, measurement_type=measurement_type)
    selection = SensorSelection(
        policy=REDUNDANT_BOOM,
        heights_m=usable,
        columns=tuple(heights[h] for h in usable),
        detail={"sensors_by_height": {str(h): redundant[h] for h in usable}},
    )
    if len(usable) < MIN_HEIGHTS_FOR_SHEAR_FIT:
        # Still usable as an extrapolation reference; only the shear *fit* is blocked,
        # and the caller supplies an exponent instead (design doc §3.A.1).
        return SensorSelection(
            policy=selection.policy,
            heights_m=selection.heights_m,
            columns=selection.columns,
            detail={
                **selection.detail,
                "requires_analyst_shear": True,
                "note": (
                    "Boom redundancy exists at a single height. A shear exponent cannot be "
                    "fitted from one height, so a scenario using this as its shear-fit set "
                    "must supply one. It remains valid as an extrapolation reference."
                ),
            },
        )
    return selection


def _resolve_widest_lever(state, heights: dict[float, str]) -> SensorSelection:
    """Pick the height pair with the largest separation in ln(z)."""
    ordered = sorted(heights)
    if len(ordered) < 2:
        return _unavailable(
            WIDEST_LEVER,
            "A widest-lever pair needs at least two measurement heights.",
            heights_available=len(ordered),
        )
    positive = [h for h in ordered if h > 0.0]
    if len(positive) < 2:
        return _unavailable(
            WIDEST_LEVER,
            "A widest-lever pair needs two positive heights; ln(z) is undefined at or below zero.",
            heights_available=len(positive),
        )
    chosen = (positive[0], positive[-1])
    return SensorSelection(
        policy=WIDEST_LEVER,
        heights_m=chosen,
        columns=tuple(heights[h] for h in chosen),
        detail={"delta_ln_z": round(float(np.log(chosen[1] / chosen[0])), 6)},
    )


def resolve_policy(state, policy: str, hub_height_m: float | None = None) -> SensorSelection:
    """Resolve one policy against a session's sensors.

    ``hub_height_m`` defaults to the session's own hub height; it is a parameter so a
    sweep can resolve a policy for a hub height it has not yet committed to the session.
    """
    if policy not in POLICIES:
        valid = ", ".join(POLICIES)
        raise ValueError(f"sensor policy must be one of {valid}, got '{policy}'")
    heights = _speed_columns_by_height(state)
    if not heights:
        return _unavailable(policy, "No mapped wind-speed sensor is present in the loaded data.")
    hub = state.get_hub_height_m() if hub_height_m is None else float(hub_height_m)
    if policy == NEAREST_2:
        return _resolve_nearest_2(state, heights, hub)
    if policy == AVAILABILITY_90:
        return _resolve_availability(state, heights)
    if policy == REDUNDANT_BOOM:
        return _resolve_redundant_boom(state, heights)
    return _resolve_widest_lever(state, heights)


def resolve_all(state, hub_height_m: float | None = None) -> dict[str, SensorSelection]:
    """Resolve every policy, so a caller can see the whole axis at once."""
    return {policy: resolve_policy(state, policy, hub_height_m) for policy in POLICIES}


def available_policies(state, hub_height_m: float | None = None) -> tuple[str, ...]:
    """Return the policies that resolve to at least one sensor on this session."""
    resolved = resolve_all(state, hub_height_m)
    return tuple(policy for policy, selection in resolved.items() if selection.available)


def distinct_selections(
    resolved: dict[str, SensorSelection],
) -> dict[tuple[str, ...], list[str]]:
    """Group policies by the columns they actually resolved to.

    Deduplication on *resolved* sensors rather than on policy names (design doc §4).
    On a sparse mast several policies routinely collapse to the same sensor list, and
    running the identical computation once per name is pure waste; on a profiling lidar
    they rarely collapse at all, which is why this returns the grouping rather than
    promising a saving.
    """
    groups: dict[tuple[str, ...], list[str]] = {}
    for policy, selection in resolved.items():
        if not selection.available:
            continue
        groups.setdefault(selection.columns, []).append(policy)
    return groups
