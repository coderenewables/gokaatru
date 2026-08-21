"""End-to-end sweep against real campaign data *and* real BrightHub reanalysis.

This is the first exercise of the S6 MERRA-2 promotion against the live API. Everything
in S6 was built against fixtures, so the things worth watching are:

  * does BrightHub actually return four MERRA-2 nodes for the widened search box, or
    fewer - the S6.1 change assumes four are reachable;
  * are those four nodes distributed around the site or all on one side;
  * does MERRA-2 arrive at 50 m (``Spd_50m``), as the descriptor asserts;
  * do both sources interpolate to site and coexist (S6.4);
  * does a real ERA5 reference give the LTC genuine skill, so the R^2 gate reflects the
    data rather than a synthetic reference.

Credentials are read from the environment and never written to a file or printed::

    BRIGHTHUB_CLIENT_ID
    BRIGHTHUB_CLIENT_SECRET

Usage::

    python scripts/e2e_real_reanalysis.py [dataset-stem]

Defaults to the Launakalana mast. Downloaded reanalysis is cached under the workspace,
so a second run does not re-fetch.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server.main  # noqa: F401,E402  - establishes tool-module import order
from server.core.brighthub import authenticate  # noqa: E402
from server.core.reanalysis import get_reference_source, reference_source_names  # noqa: E402
from server.core.scenario_context import fork_cost_bytes  # noqa: E402
from server.core.sweep import (  # noqa: E402
    SweepSpec,
    load_scenario_runconfig,
    load_sweep,
    run_sweep,
)
from server.state.session import SessionState  # noqa: E402
from server.tools.brighthub import _prepare_brighthub_reanalysis  # noqa: E402
from server.tools.data_io import _parse_datamodel, _parse_timeseries  # noqa: E402

UPLOADS = Path("data/uploads").resolve()
WORKSPACE = Path("data/e2e-real").resolve()
DEFAULT_STEM = "WB-ESMAP_Launakalana"


#: Optional credential file: client id on the first line, secret on the second.
#: Lives under `data/`, which is gitignored, so it cannot reach the repository.
CREDENTIAL_FILE = Path("data/bhcred.txt")


def require_credentials() -> tuple[str, str]:
    """Read the BrightHub client credentials, from the environment or the credential file.

    The value is never printed, logged or written anywhere by this script — it is read at
    the moment it is needed and passed straight to the auth call.
    """
    client_id = os.environ.get("BRIGHTHUB_CLIENT_ID", "").strip()
    client_secret = os.environ.get("BRIGHTHUB_CLIENT_SECRET", "").strip()
    if client_id and client_secret:
        return client_id, client_secret

    if CREDENTIAL_FILE.is_file():
        lines = [
            line.strip()
            for line in CREDENTIAL_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if len(lines) >= 2:
            return lines[0], lines[1]
        sys.exit(
            f"{CREDENTIAL_FILE} must hold the client id on the first line and the client "
            "secret on the second."
        )

    sys.exit(
        "No BrightHub credentials found.\n"
        "Either set BRIGHTHUB_CLIENT_ID and BRIGHTHUB_CLIENT_SECRET in the environment,\n"
        f"or put the client id and secret on two lines in {CREDENTIAL_FILE}.\n"
        "Both are read at runtime; no credential is written into the repository or echoed\n"
        "into this script's output."
    )


def load_campaign(stem: str) -> SessionState:
    """Load one checked-in campaign, then point the workspace at the run directory."""
    state = SessionState()
    state.reset()
    state.workspace_dir = UPLOADS.parent
    _parse_timeseries(state, str(UPLOADS / f"{stem}_timeseries_data.csv"))
    _parse_datamodel(state, str(UPLOADS / f"{stem}_data_model.json"))
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    state.workspace_dir = WORKSPACE
    return state


def report_nodes(state: SessionState) -> None:
    """S6.1: four nodes per source, and do they straddle the site or sit on one side?"""
    coordinate = state.get_coordinate()
    print("\n--- S6.1 node acquisition ---")
    for label, nodes in (("ERA5", state.era5_nodes), ("MERRA-2", state.merra_nodes)):
        nodes = nodes or []
        print(f"  {label}: {len(nodes)} node(s)")
        if not nodes:
            continue
        north = sum(1 for n in nodes if float(n["latitude"]) >= coordinate.latitude)
        east = sum(1 for n in nodes if float(n["longitude"]) >= coordinate.longitude)
        for node in nodes:
            print(
                f"      {float(node['latitude']):8.4f}, {float(node['longitude']):9.4f}"
                f"   {float(node['distance_km']):6.1f} km  {node.get('bearing', '?')}"
            )
        brackets = 0 < north < len(nodes) and 0 < east < len(nodes)
        print(f"      brackets the site in both axes: {brackets}")
        if not brackets:
            print("      ^ nearest-N fallback: the interpolation is extrapolating here")


def report_series(state: SessionState) -> None:
    """S6.3/S6.4: both sources reach site, each at its own native height, and coexist."""
    print("\n--- S6.3/S6.4 interpolated site series ---")
    for name in reference_source_names():
        frame = state.reanalysis_interpolated.get(name)
        descriptor = get_reference_source(name)
        if frame is None:
            print(f"  {descriptor.label}: MISSING")
            continue
        speed = frame[descriptor.speed_col]
        print(
            f"  {descriptor.label:<8s} {len(frame):>7,} h  "
            f"{frame.index.min().date()} -> {frame.index.max().date()}  "
            f"{descriptor.speed_col} mean {speed.mean():.3f} m/s "
            f"(native {descriptor.native_height_m:g} m)"
        )
    era5 = state.reanalysis_interpolated.get("era5")
    merra = state.reanalysis_interpolated.get("merra2")
    if era5 is None or merra is None:
        return
    overlap = era5.join(merra, how="inner", lsuffix="_e", rsuffix="_m").dropna()
    if overlap.empty:
        print("  the two sources share no timestamps")
        return
    correlation = overlap["Spd_100m"].corr(overlap["Spd_50m"])
    ratio = overlap["Spd_50m"].mean() / overlap["Spd_100m"].mean()
    print(f"  inter-source correlation over {len(overlap):,} h: {correlation:.4f}")
    print(f"  MERRA-2 50 m / ERA5 100 m mean ratio: {ratio:.4f}")
    print("      (a ratio below 1 is the expected shear signature of the lower height)")


def report_sweep(state: SessionState, spec: SweepSpec, rows: list, counts: dict) -> None:
    """Summarise the sweep, with the axis-C spread the S8.1 additive term rests on."""
    ok = [row for row in rows if row["status"] == "ok"]

    r_squared = [row["ltc_r_squared"] for row in ok if row["ltc_r_squared"] is not None]
    if r_squared:
        print(f"  LTC R^2 range   : {min(r_squared):.3f} - {max(r_squared):.3f}   (real reference)")
    speeds = [row["long_term_mean_speed_mps"] for row in ok if row["long_term_mean_speed_mps"]]
    if speeds:
        spread = 100 * (max(speeds) - min(speeds)) / float(np.mean(speeds))
        print(
            f"  LT mean speed   : {min(speeds):.3f} - {max(speeds):.3f} m/s"
            f"   (spread {spread:.2f}% of mean)"
        )
    aeps = [row["indicative_gross_aep_mwh"] for row in ok if row["indicative_gross_aep_mwh"]]
    if aeps:
        print(f"  indicative AEP  : {min(aeps):,.0f} - {max(aeps):,.0f} MWh/yr")

    def source_speeds(source: str) -> list[float]:
        return [
            row["long_term_mean_speed_mps"]
            for row in ok
            if row["reference_source"] == source and row["long_term_mean_speed_mps"]
        ]

    print("\n--- axis C: does the reference source move the answer? ---")
    for source in reference_source_names():
        values = source_speeds(source)
        if not values:
            print(f"  {source:<8s} no admissible scenario carried a long-term mean")
            continue
        scores = [
            row["ltc_r_squared"]
            for row in ok
            if row["reference_source"] == source and row["ltc_r_squared"] is not None
        ]
        line = f"  {source:<8s} n={len(values):>3}  mean {np.mean(values):.3f} m/s"
        if scores:
            line += f"   R^2 {min(scores):.3f}-{max(scores):.3f}"
        print(line)

    era5_mean = float(np.mean(source_speeds("era5") or [np.nan]))
    merra_mean = float(np.mean(source_speeds("merra2") or [np.nan]))
    if np.isfinite(era5_mean) and np.isfinite(merra_mean):
        gap = abs(era5_mean - merra_mean)
        print(
            f"  inter-source spread: {gap:.4f} m/s "
            f"({100 * gap / np.mean([era5_mean, merra_mean]):.2f}%)"
        )
        print("      this is the S8.1 additive uncertainty term, measured for the first time")

    gates: dict[str, dict[str, int]] = {}
    for row in ok:
        for key, value in row.items():
            if key.startswith("gate_"):
                gates.setdefault(key[5:], {}).setdefault(str(value), 0)
                gates[key[5:]][str(value)] += 1
    print("\n--- gate outcomes on real data ---")
    for name, tally in sorted(gates.items()):
        print(f"  {name:<24s} {tally}")

    failures = [row for row in rows if row["status"] == "failed"]
    if failures:
        print(f"\n--- {len(failures)} failed ---")
        for reason in sorted({str(row["error"])[:120] for row in failures}):
            print(f"  {reason}")
    del spec, counts


def main() -> None:
    stem = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_STEM
    client_id, client_secret = require_credentials()

    print(f"Loading campaign: {stem}")
    state = load_campaign(stem)
    coordinate = state.get_coordinate()
    heights = sorted(
        height
        for height, slots in state.sensor_mapping.items()
        if slots.get("speed_col") in state.timeseries_df.columns
    )
    print(f"  {len(state.timeseries_df):,} records, heights {heights}")
    print(f"  site: {coordinate.latitude:.5f}, {coordinate.longitude:.5f}")

    print("\nAuthenticating with BrightHub...")
    state.brighthub_token = authenticate(client_id, client_secret)["id_token"]
    print("  ok (token held in memory only)")

    print("\nFetching ERA5 + MERRA-2 and interpolating both to site...")
    started = time.perf_counter()
    prepared = _prepare_brighthub_reanalysis(state, coordinate.latitude, coordinate.longitude)
    print(f"  done in {time.perf_counter() - started:.1f}s  (cached: {prepared['cached']})")
    print(f"  era5_nodes={prepared['era5_nodes']}  merra2_nodes={prepared['merra2_nodes']}")

    report_nodes(state)
    report_series(state)

    hub = max(heights) * 1.5
    state.set_hub_height_m(hub)
    spec = SweepSpec(
        shear_fit_policies=("nearest_2", "widest_lever"),
        reference_policies=("nearest_2",),
        shear_models=("power_law_mean", "power_law_momm", "log_law_mean"),
        reference_sources=tuple(reference_source_names()),
        ltc_algorithms=("variance_ratio", "linear_least_squares", "total_least_squares"),
        hub_height_m=hub,
    )
    print(
        f"\n--- sweep: hub {hub:g} m, {spec.leaf_count()} leaves, "
        f"{spec.prefix_count()} prefixes ---"
    )
    print(f"  fork cost / leaf: {fork_cost_bytes(state)['total'] / 1e6:.1f} MB")

    started = time.perf_counter()
    outcome = run_sweep(state, spec, sweep_id="real")
    elapsed = time.perf_counter() - started
    counts = outcome["manifest"]["counts"]
    rows = outcome["results"]
    print(f"  ran in {elapsed:.1f}s ({elapsed / max(1, counts['run']):.2f}s per leaf)")
    print(f"  counts: {counts}")

    report_sweep(state, spec, rows, counts)

    reloaded = load_sweep(state, "real")
    assert len(reloaded["results"]) == len(rows)
    admissible = [row for row in rows if row["status"] == "ok" and row["admissible"]]
    if admissible:
        config = load_scenario_runconfig(state, "real", admissible[0]["config_hash"])
        assert config["scenario"]["config_hash"] == admissible[0]["config_hash"]
    print(
        f"\n  persistence round-trips; "
        f"{len(reloaded['manifest']['scenarios'])} runconfigs written to {WORKSPACE}"
    )


if __name__ == "__main__":
    main()
