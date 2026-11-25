"""A project reopens intact after the server process is killed and restarted (P1-14, the
Phase 1 gate's third condition).

Everything goes over HTTP to a real uvicorn process: upload, data model build, a
configuration change, cleaning, shear and hub-height extrapolation. The server is then
killed outright, not shut down, so only the saves made after each change can carry the
project across. A new server process on the same workspace must answer every read the same.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

from server.core.datamodel_builder import spec_from_draft

REPO_ROOT = Path(__file__).resolve().parents[1]
STARTUP_SECONDS = 180


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _start(workdir: Path, port: int) -> subprocess.Popen:
    log = (workdir / f"server-{port}-{time.time_ns()}.log").open("wb")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.api.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=workdir,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    deadline = time.monotonic() + STARTUP_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"the server exited during start-up; see {log.name}")
        try:
            if httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=2).status_code == 200:
                return process
        except httpx.HTTPError:
            time.sleep(0.5)
    process.kill()
    raise RuntimeError(f"the server did not answer within {STARTUP_SECONDS} s; see {log.name}")


def _kill(process: subprocess.Popen) -> None:
    process.kill()
    process.wait(timeout=60)


def _campaign_csv(path: Path) -> None:
    rng = np.random.default_rng(29)
    index = pd.date_range("2023-01-01", periods=90 * 144, freq="10min")
    top = rng.weibull(2.0, len(index)) * 8.0
    top[400:410] = 80.0
    pd.DataFrame(
        {
            "Timestamp": index.strftime("%Y-%m-%d %H:%M:%S"),
            "Spd_100m": top,
            "Spd_80m": top * 0.8 ** 0.14,
            "Spd_60m": top * 0.6 ** 0.14,
            "Dir_100m": rng.uniform(0, 360, len(index)),
        }
    ).to_csv(path, index=False)


def _ok(response: httpx.Response) -> dict:
    assert response.status_code == 200, (response.request.url, response.text)
    return response.json()


def _reads(client: httpx.Client, session_id: str) -> dict[str, object]:
    base = f"/api/sessions/{session_id}/operations"
    reads = {
        "run_config": ("get_run_config", {}),
        "cleaning_log": ("get_cleaning_log", {}),
        "weibull_hub": ("compute_weibull_params", {"sensor_name": "Spd_120m_hub"}),
        "monthly_hub": ("compute_monthly_stats", {"sensor_name": "Spd_120m_hub"}),
        "coverage": ("get_data_coverage", {"sensor_name": "Spd_100m"}),
        "sensors": ("list_sensors", {}),
    }
    out = {key: _ok(client.post(f"{base}/{name}", json=body)) for key, (name, body) in reads.items()}
    log = _ok(client.post(f"{base}/get_operation_log", json={"limit": 1000}))
    out["changes"] = [
        (entry["seq"], entry["operation"], entry["actor"], entry["parameters"], entry["data_version_after"])
        for entry in log["entries"]
        if entry["effect"] == "change"
    ]
    # updated_at is bookkeeping, set again on every change and on reopening; it is not saved.
    summary = _ok(client.get(f"/api/sessions/{session_id}"))
    out["summary"] = {key: value for key, value in summary.items() if key != "updated_at"}
    return out


def test_a_project_reopens_intact_after_the_server_is_killed(tmp_path: Path) -> None:
    port = _free_port()
    csv_path = tmp_path / "campaign.csv"
    _campaign_csv(csv_path)

    server = _start(tmp_path, port)
    try:
        client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=120)
        session_id = _ok(client.post("/api/sessions"))["session_id"]
        client.headers["X-GoKaatru-Session"] = session_id
        with csv_path.open("rb") as handle:
            files = {"file": ("campaign.csv", handle)}
            _ok(client.post(f"/api/sessions/{session_id}/uploads/timeseries", files=files))
        draft = _ok(client.get(f"/api/sessions/{session_id}/datamodel/draft"))
        columns = [column["name"] for column in draft["columns"]]
        spec = spec_from_draft(columns, {"name": "Synthetic", "offset_from_utc_hrs": 0})
        _ok(client.post(f"/api/sessions/{session_id}/datamodel/build", json=spec))
        hub = {"updates": [{"key": "hub_height_m", "value": 120}]}
        _ok(client.put(f"/api/sessions/{session_id}/config", json=hub))
        base = f"/api/sessions/{session_id}/operations"
        pair = json.dumps({"80": "Spd_80m", "100": "Spd_100m"})
        for name, body in [
            ("apply_cleaning_rule", {"rule_type": "range_check", "sensor": "Spd_100m", "params": "{}"}),
            ("calculate_shear_timeseries", {"height_sensors": pair}),
            ("build_shear_table", {}),
            ("extrapolate_to_hub_height", {"hub_height_m": 120.0}),
        ]:
            _ok(client.post(f"{base}/{name}", json=body))
        before = _reads(client, session_id)
        client.close()
    finally:
        _kill(server)

    server = _start(tmp_path, port)
    try:
        client = httpx.Client(
            base_url=f"http://127.0.0.1:{port}", timeout=120, headers={"X-GoKaatru-Session": session_id}
        )
        after = _reads(client, session_id)
        client.close()
    finally:
        _kill(server)

    assert before["cleaning_log"]["flags"]["flagged_records"] == 10
    assert any(name.startswith("http POST") and "uploads" in name for _, name, *_ in before["changes"])
    for key in before:
        assert after[key] == before[key], key
