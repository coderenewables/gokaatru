"""Published-numbers snapshot of the three reference campaigns (Phase 1 gate, P1-0).

Runs the pipeline on Boxkite, Horns Rev and Launakalana and records every number each step
returns, plus a SHA-256 of every series it produces, so a refactor that changes any
published number, down to the last bit, fails ``tests/test_published_numbers.py``.

Boxkite and Horns Rev have no reanalysis in the local caches, so their record stops at the
hub-height series. Launakalana carries the whole chain against its cached ERA5 and MERRA-2:
the long-term corrections, the ensemble, clipping, uncertainty and a fixed sweep.

Refresh the snapshot only when a number is meant to move, and record the move in CLAUDE.md:

    python -m tests.published_numbers --write
    python -m tests.published_numbers --check
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import server.main  # noqa: F401 — establishes tool-module import order
from server.core.sweep import SweepSpec, run_sweep
from server.core.uncertainty_inputs import derive_uncertainty_inputs, uncertainty_call_args
from server.state.session import session
from server.tools.cleaning import _apply_cleaning_rule, _undo_cleaning_rule
from server.tools.clipping import _run_clipping_analysis
from server.tools.data_io import _get_data_coverage, _get_period_of_record, _parse_datamodel, _parse_timeseries
from server.tools.diagnostics import _compute_qc_diagnostics
from server.tools.ensemble import _run_ensemble
from server.tools.era5 import _era5_key, _interpolate_era5_to_site
from server.tools.extrapolation import _extrapolate_to_hub_height
from server.tools.ltc import (
    _run_ltc_linear_least_squares,
    _run_ltc_speedsort,
    _run_ltc_total_least_squares,
    _run_ltc_variance_ratio,
)
from server.tools.shear import (
    _build_roughness_table,
    _build_sector_shear_tables,
    _build_shear_table,
    _calculate_roughness_timeseries,
    _calculate_shear_timeseries,
    _compute_vertical_structure,
)
from server.tools.statistics import _compute_monthly_stats, _compute_weibull_params, _compute_wind_climate
from server.tools.uncertainty import _calculate_uncertainty
from tests.conftest import REPO_ROOT, UPLOADS_DIR

SNAPSHOT_PATH = Path(__file__).resolve().parent / "snapshots" / "published_numbers.json"
REANALYSIS_CACHE = REPO_ROOT / "data" / "e2e-real" / "brighthub_cache"

# Run identities, file locations and wall-clock times differ between runs by design.
VOLATILE_KEYS = frozenset({
    "applied_at", "created_at", "duration_s", "elapsed_s", "file", "finished_at", "path", "persisted",
    "result_file", "run_id", "started_at", "sweep_id", "timestamp", "updated_at",
})
# Labels and column names are part of what is published; prose notes are not numbers and
# change with wording edits, so only identifier-like strings are kept.
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:+\-]{1,64}$")


@dataclass(frozen=True)
class Campaign:
    stem: str
    hub_height_m: float
    shear_sensors: dict[str, str]
    direction_sensor: str
    rule_speed_sensor: str
    excluded_week: tuple[str, str]
    reanalysis: dict[str, list[tuple[float, float]]] = field(default_factory=dict)

    def files(self) -> tuple[Path, Path]:
        return (
            UPLOADS_DIR / f"{self.stem}_timeseries_data.csv",
            UPLOADS_DIR / f"{self.stem}_data_model.json",
        )

    def missing_files(self) -> list[Path]:
        needed = list(self.files())
        for source, nodes in self.reanalysis.items():
            needed += [REANALYSIS_CACHE / f"{source}_{lat}_{lon}.parquet" for lat, lon in nodes]
        return [path for path in needed if not path.exists()]


CAMPAIGNS: dict[str, Campaign] = {
    "boxkite": Campaign(
        stem="HKW-B-FLS-Boxkite",
        hub_height_m=150.0,
        shear_sensors={"100": "Spd_100m", "200": "Spd_200m"},
        direction_sensor="Dir_100m",
        rule_speed_sensor="Spd_100m",
        excluded_week=("2019-06-01", "2019-06-07"),
    ),
    "horns_rev": Campaign(
        stem="HornsRev-MAST",
        hub_height_m=70.0,
        shear_sensors={"45": "Spd_NE_45m", "62": "Spd_62m"},
        direction_sensor="Dir_58m",
        rule_speed_sensor="Spd_58m",
        excluded_week=("2002-03-01", "2002-03-07"),
    ),
    "launakalana": Campaign(
        stem="WB-ESMAP_Launakalana",
        hub_height_m=120.0,
        shear_sensors={"60": "Spd3_60m_25deg", "80": "Spd1_80m_25deg"},
        direction_sensor="Dir1_77m_25deg",
        rule_speed_sensor="Spd1_80m_25deg",
        excluded_week=("2018-09-01", "2018-09-07"),
        reanalysis={
            "ERA5": [(-9.977, 147.656), (-9.977, 147.938), (-9.696, 147.656), (-9.696, 147.938)],
            "MERRA-2": [(-10.0, 147.5), (-10.0, 148.125), (-9.5, 147.5), (-9.5, 148.125)],
        },
    ),
}

SWEEP_SPEC = SweepSpec(
    shear_fit_policies=("nearest_2", "widest_lever"),
    reference_policies=("nearest_2",),
    shear_models=("power_law_mean", "log_law_momm"),
    reference_sources=("era5", "merra2"),
    ltc_algorithms=("linear_least_squares", "total_least_squares", "speedsort", "variance_ratio"),
    hub_height_m=120.0,
)


def _number(value: float) -> float | str:
    if math.isnan(value):
        return "nan"
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return value


def series_digest(series: pd.Series) -> dict[str, object]:
    """Count, NaN count, mean and a SHA-256 over the float64 values and the UTC index."""
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype="float64", na_value=np.nan)
    canonical = np.where(np.isnan(values), np.float64("nan"), values) + 0.0
    digest = hashlib.sha256(canonical.tobytes())
    if isinstance(series.index, pd.DatetimeIndex):
        digest.update(series.index.as_unit("ns").asi8.tobytes())
    finite = np.isfinite(canonical)
    return {
        "count": int(finite.sum()),
        "nan": int(np.isnan(canonical).sum()),
        "mean": _number(float(canonical[finite].mean())) if finite.any() else "nan",
        "sha256": digest.hexdigest(),
    }


def frame_digest(frame: pd.DataFrame) -> dict[str, object]:
    return {str(column): series_digest(frame[column]) for column in frame.columns}


def flatten(value: Any, prefix: str = "") -> dict[str, object]:
    """Every number, boolean and identifier-like string, keyed by its path in the response."""
    out: dict[str, object] = {}
    if isinstance(value, dict):
        for key in sorted(value, key=str):
            if str(key) in VOLATILE_KEYS:
                continue
            out.update(flatten(value[key], f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            out.update(flatten(item, f"{prefix}[{index}]"))
    elif isinstance(value, pd.DataFrame):
        out.update(flatten(frame_digest(value), prefix))
    elif isinstance(value, pd.Series):
        out.update(flatten(series_digest(value), prefix))
    elif isinstance(value, (bool, np.bool_)):
        out[prefix] = bool(value)
    elif isinstance(value, (int, np.integer)):
        out[prefix] = int(value)
    elif isinstance(value, (float, np.floating)):
        out[prefix] = _number(float(value))
    elif isinstance(value, str):
        if IDENTIFIER.match(value):
            out[prefix] = value
    elif value is None:
        out[prefix] = None
    return out


def mapped_columns(frame: pd.DataFrame, extra: tuple[str, ...] = ()) -> pd.DataFrame:
    """The columns the pipeline reads: every mapped sensor slot, plus any hub series.

    Logger diagnostics and statistic channels nothing consumes would triple the snapshot
    without guarding a published number.
    """
    columns = {
        str(column)
        for mapping in session.sensor_mapping.values()
        for column in mapping.values()
        if column
    } | set(extra)
    keep = [column for column in frame.columns if column in columns or str(column).endswith("_hub")]
    return frame[keep]


class Recorder:
    def __init__(self) -> None:
        self.numbers: dict[str, object] = {}

    def step(self, name: str, call: Callable[[], Any]) -> Any:
        """Run one step and record its response; a refusal is recorded, not raised."""
        try:
            response = call()
        except ValueError as exc:
            self.numbers[f"{name}.refused"] = type(exc).__name__
            return None
        self.numbers.update(flatten(response, name))
        return response

    def record(self, name: str, value: Any) -> None:
        self.numbers.update(flatten(value, name))


def _load(campaign: Campaign, rec: Recorder) -> None:
    timeseries, datamodel = campaign.files()
    session.reset()
    session.persist_result_files = False
    rec.step("ingest.timeseries", lambda: _parse_timeseries(session, str(timeseries)))
    rec.step("ingest.datamodel", lambda: _parse_datamodel(session, str(datamodel)))
    rec.record("ingest.sensor_mapping", {str(h): m for h, m in sorted(session.sensor_mapping.items())})
    rec.record("ingest.series", mapped_columns(session.timeseries_df, (campaign.direction_sensor,)))
    rec.step("ingest.period_of_record", lambda: _get_period_of_record(session))


def _clean(campaign: Campaign, rec: Recorder) -> None:
    speed, direction = campaign.rule_speed_sensor, campaign.direction_sensor
    start, end = campaign.excluded_week
    rules = [
        ("range_check", speed, "{}", "", ""),
        ("range_check", direction, "{}", "", ""),
        ("stuck_sensor", speed, "{}", "", ""),
        ("icing_filter", speed, "{}", "", ""),
        ("tower_shadow", speed, "{}", "", ""),
        ("custom_period_exclude", speed, "{}", start, end),
        ("expression_filter", speed, json.dumps({"expression": f"{speed} > 40"}), "", ""),
    ]
    for index, (rule, sensor, params, rule_start, rule_end) in enumerate(rules):
        rec.step(
            f"cleaning.apply[{index}].{rule}",
            lambda rule=rule, sensor=sensor, params=params, rule_start=rule_start, rule_end=rule_end:
                _apply_cleaning_rule(session, rule, sensor, params, rule_start, rule_end),
        )
    rec.record("cleaning.after_apply.series", mapped_columns(session.timeseries_df, (campaign.direction_sensor,)))
    rec.step("cleaning.undo[1]", lambda: _undo_cleaning_rule(session, 1))
    rec.record("cleaning.after_undo.series", mapped_columns(session.timeseries_df, (campaign.direction_sensor,)))
    rec.record("cleaning.log", session.cleaning_log)


def _statistics(campaign: Campaign, rec: Recorder) -> None:
    for height, mapping in sorted(session.sensor_mapping.items()):
        column = mapping.get("speed_col")
        if not column:
            continue
        rec.step(f"statistics.coverage.{column}", lambda column=column: _get_data_coverage(session, column))
        rec.step(f"statistics.weibull.{column}", lambda column=column: _compute_weibull_params(session, column))
        rec.step(f"statistics.monthly.{column}", lambda column=column: _compute_monthly_stats(session, column))
    rec.step(
        "statistics.wind_climate",
        lambda: _compute_wind_climate(session, campaign.rule_speed_sensor, campaign.direction_sensor),
    )
    rec.step("statistics.qc_diagnostics", lambda: _compute_qc_diagnostics(session))


def _shear(campaign: Campaign, rec: Recorder) -> None:
    pair = json.dumps(campaign.shear_sensors)
    rec.step("shear.timeseries", lambda: _calculate_shear_timeseries(session, pair))
    rec.step("shear.table.momm", lambda: _build_shear_table(session, "momm"))
    rec.step("shear.table.mean", lambda: _build_shear_table(session, "mean"))
    rec.step(
        "shear.sector_tables",
        lambda: _build_sector_shear_tables(session, campaign.direction_sensor),
    )
    rec.step("shear.roughness.timeseries", lambda: _calculate_roughness_timeseries(session, pair))
    rec.step("shear.roughness.table", lambda: _build_roughness_table(session, "mean"))
    rec.step("shear.vertical_structure", lambda: _compute_vertical_structure(session))


def _extrapolate(campaign: Campaign, rec: Recorder) -> str | None:
    reference = list(campaign.shear_sensors.values())
    hub = None
    for model in ("log_law", "power_law"):
        response = rec.step(
            f"extrapolation.{model}",
            lambda model=model: _extrapolate_to_hub_height(
                session, campaign.hub_height_m, model, reference_columns=reference
            ),
        )
        if response is not None:
            hub = str(response["column_name"])
            rec.record(f"extrapolation.{model}.hub_series", session.timeseries_df[hub])
    return hub


def _load_reanalysis(campaign: Campaign, rec: Recorder) -> None:
    def frames(source: str) -> dict[str, pd.DataFrame]:
        return {
            f"{float(lat)}_{float(lon)}": pd.read_parquet(REANALYSIS_CACHE / f"{source}_{lat}_{lon}.parquet")
            for lat, lon in campaign.reanalysis[source]
        }

    session.era5_nodes = [{"latitude": lat, "longitude": lon} for lat, lon in campaign.reanalysis["ERA5"]]
    session.era5_data = {_era5_key(lat, lon): frame for (lat, lon), frame in zip(
        campaign.reanalysis["ERA5"], frames("ERA5").values()
    )}
    session.merra_nodes = [{"latitude": lat, "longitude": lon} for lat, lon in campaign.reanalysis["MERRA-2"]]
    session.merra_data = frames("MERRA-2")
    # ERA5 last: both write the single LTC reference, and ERA5 is the default source.
    rec.step("reanalysis.merra2", lambda: _interpolate_era5_to_site(session, "merra2"))
    rec.step("reanalysis.era5", lambda: _interpolate_era5_to_site(session, "era5"))


def _long_term(campaign: Campaign, rec: Recorder, hub: str) -> None:
    runs: list[tuple[str, str, Callable[[], dict]]] = [
        ("linear_least_squares", "linear_least_squares",
         lambda: _run_ltc_linear_least_squares(session, hub, "Spd_100m")),
        ("total_least_squares", "total_least_squares",
         lambda: _run_ltc_total_least_squares(session, hub, "Spd_100m")),
        ("variance_ratio", "variance_ratio", lambda: _run_ltc_variance_ratio(session, hub, "Spd_100m")),
        ("speedsort_directional", "speedsort",
         lambda: _run_ltc_speedsort(session, hub, "Spd_100m", long_dir_col="Dir_100m")),
        ("speedsort", "speedsort", lambda: _run_ltc_speedsort(session, hub, "Spd_100m")),
    ]
    try:
        from server.tools.ltc_ml import _run_ltc_xgboost

        runs.append(("xgboost", "xgboost", lambda: _run_ltc_xgboost(session, hub, "Spd_100m")))
    except ImportError:
        rec.numbers["ltc.xgboost.refused"] = "ImportError"
    for label, key, call in runs:
        if rec.step(f"ltc.{label}", call) is not None:
            rec.record(f"ltc.{label}.corrected", session.ltc_results[key]["df"]["corrected_wind_speed"])

    rec.step("ensemble", lambda: _run_ensemble(session, hub))
    rec.step("clipping", lambda: _run_clipping_analysis(session, "Ensemble_Speed", "ensemble"))
    reference_heights = [float(height) for height in campaign.shear_sensors]
    for algorithm in ("speedsort", "variance_ratio"):
        inputs = rec.step(
            f"uncertainty.{algorithm}.inputs",
            lambda algorithm=algorithm: derive_uncertainty_inputs(
                session, algorithm, hub_height_m=campaign.hub_height_m, reference_heights=reference_heights
            ),
        )
        if inputs is not None:
            arguments = uncertainty_call_args(inputs)
            rec.step(
                f"uncertainty.{algorithm}.result",
                lambda arguments=arguments: _calculate_uncertainty(session, **arguments),
            )


def _sweep(rec: Recorder) -> None:
    try:
        outcome = run_sweep(session, SWEEP_SPEC, persist=False)
    except ValueError as exc:
        rec.numbers["sweep.refused"] = type(exc).__name__
        return
    rec.record("sweep.manifest", outcome["manifest"])
    for row in sorted(outcome["results"], key=lambda item: str(item.get("config_hash"))):
        rec.record(f"sweep.rows.{row.get('config_hash')}", row)


def capture(name: str) -> dict[str, object]:
    """Run the pipeline on one campaign and return every recorded number."""
    campaign = CAMPAIGNS[name]
    rec = Recorder()
    _load(campaign, rec)
    if campaign.reanalysis:
        _load_reanalysis(campaign, rec)
    _clean(campaign, rec)
    _statistics(campaign, rec)
    _shear(campaign, rec)
    hub = _extrapolate(campaign, rec)
    if campaign.reanalysis and hub is not None:
        _long_term(campaign, rec, hub)
        _sweep(rec)
    session.reset()
    return dict(sorted(rec.numbers.items()))


def load_snapshot() -> dict[str, dict[str, object]]:
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def differences(expected: dict[str, object], actual: dict[str, object]) -> list[str]:
    lines = []
    for key in sorted(set(expected) | set(actual)):
        if key not in actual:
            lines.append(f"missing  {key} (was {expected[key]!r})")
        elif key not in expected:
            lines.append(f"new      {key} = {actual[key]!r}")
        elif expected[key] != actual[key]:
            lines.append(f"changed  {key}: {expected[key]!r} -> {actual[key]!r}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="capture and overwrite the snapshot")
    mode.add_argument("--check", action="store_true", help="capture and compare with the snapshot")
    parser.add_argument("campaigns", nargs="*", default=list(CAMPAIGNS))
    args = parser.parse_args(argv)

    snapshot = load_snapshot() if SNAPSHOT_PATH.exists() else {}
    failed = False
    for name in args.campaigns:
        missing = CAMPAIGNS[name].missing_files()
        if missing:
            print(f"{name}: skipped, missing {', '.join(str(path) for path in missing)}")
            continue
        numbers = capture(name)
        if args.write:
            snapshot[name] = numbers
            print(f"{name}: {len(numbers)} numbers captured")
            continue
        diff = differences(snapshot.get(name, {}), numbers)
        failed = failed or bool(diff)
        print(f"{name}: {'identical' if not diff else f'{len(diff)} differences'} ({len(numbers)} numbers)")
        for line in diff[:40]:
            print("   ", line)
    if args.write:
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
