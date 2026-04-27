"""brighthub — BrightHub API authentication and data-access client.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import requests

BRIGHTHUB_BASE_URL = "https://api.brighthub.io"
BRIGHTHUB_AUTH_URL = f"{BRIGHTHUB_BASE_URL}/auth/token"


def authenticate(client_id: str, client_secret: str) -> dict[str, str | None]:
    """Obtain an id_token via the BrightHub client_credentials flow.

    Returns a dict with ``id_token`` (str) and ``refresh_token`` (always None).
    Raises on HTTP or auth failure.
    """
    response = requests.post(
        BRIGHTHUB_AUTH_URL,
        auth=(client_id, client_secret),
        data={"grant_type": "client_credentials"},
        timeout=30,
    )
    response.raise_for_status()
    token_data = response.json()
    id_token = token_data.get("id_token")
    if not id_token:
        raise ValueError("Authentication succeeded but id_token was not present in the response.")
    return {"id_token": id_token, "refresh_token": None}


def _auth_headers(token: str) -> dict[str, str]:
    """Build the Authorization header dict for a BrightHub Bearer token."""
    return {"Authorization": f"Bearer {token}"}


def list_measurement_locations(token: str) -> list[dict]:
    """Return all measurement locations visible to the authenticated user."""
    resp = requests.get(
        f"{BRIGHTHUB_BASE_URL}/measurement-locations/",
        headers=_auth_headers(token),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_data_model(token: str, uuid: str) -> dict:
    """Fetch the data model for a measurement location."""
    resp = requests.get(
        f"{BRIGHTHUB_BASE_URL}/measurement-locations/{uuid}/data-model",
        headers=_auth_headers(token),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_measurement_location(token: str, uuid: str) -> dict:
    """Fetch metadata for a single measurement location."""
    resp = requests.get(
        f"{BRIGHTHUB_BASE_URL}/measurement-locations/{uuid}",
        headers=_auth_headers(token),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, list) and data:
        return data[0]
    return data


def fetch_timeseries_csv(
    token: str,
    uuid: str,
    *,
    apply_cleaning_log: bool = True,
    apply_cleaning_rules: bool = False,
    apply_calibration: bool = False,
    apply_deadband_offset: bool = False,
    apply_orientation_offset: bool = False,
) -> str:
    """Download the assembled timeseries CSV text for a measurement location.

    BrightHub returns a presigned URL which is then downloaded.
    Returns the raw CSV text.
    """
    headers = _auth_headers(token)
    params: dict[str, str] = {}
    if apply_cleaning_log:
        params["apply_cleaning_log"] = "true"
    if apply_cleaning_rules:
        params["apply_cleaning_rules"] = "true"
    if apply_calibration:
        params["apply_calibration_slope_and_offset"] = "true"
    if apply_deadband_offset:
        params["apply_wind_vane_deadband_offset"] = "true"
    if apply_orientation_offset:
        params["apply_device_orientation_offset"] = "true"
    resp = requests.get(
        f"{BRIGHTHUB_BASE_URL}/measurement-locations/{uuid}/timeseries-data",
        headers=headers,
        params=params,
        timeout=60,
    )
    resp.raise_for_status()
    presigned_url = resp.json().get("url")
    if not presigned_url:
        raise RuntimeError("BrightHub did not return a download URL for this dataset.")

    # Stream the presigned download with a hard byte cap so a malicious or
    # accidentally huge response cannot exhaust server memory.
    max_bytes = 500 * 1024 * 1024  # 500 MiB
    download_resp = requests.get(presigned_url, timeout=300, stream=True)
    download_resp.raise_for_status()

    declared = download_resp.headers.get("Content-Length")
    if declared is not None:
        try:
            if int(declared) > max_bytes:
                download_resp.close()
                raise RuntimeError(
                    f"BrightHub timeseries download exceeds the {max_bytes} byte limit"
                )
        except ValueError:
            pass

    chunks: list[bytes] = []
    received = 0
    try:
        for chunk in download_resp.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            received += len(chunk)
            if received > max_bytes:
                raise RuntimeError(
                    f"BrightHub timeseries download exceeds the {max_bytes} byte limit"
                )
            chunks.append(chunk)
    finally:
        download_resp.close()
    encoding = download_resp.encoding or "utf-8"
    return b"".join(chunks).decode(encoding, errors="replace")


def fetch_reanalysis_nodes(token: str, lat: float, lon: float) -> dict[str, list[dict]]:
    """Fetch nearest ERA5 (×4) and MERRA-2 (×1) reanalysis nodes near a coordinate."""
    params = {
        "min_latitude_ddeg": lat - 0.5,
        "max_latitude_ddeg": lat + 0.5,
        "min_longitude_ddeg": lon - 0.5,
        "max_longitude_ddeg": lon + 0.5,
    }
    headers = _auth_headers(token)

    era5_resp = requests.get(
        f"{BRIGHTHUB_BASE_URL}/reanalysis/ERA5/nodes",
        headers=headers,
        params=params,
        timeout=30,
    )
    era5_resp.raise_for_status()
    era5_nodes: list[dict] = era5_resp.json()

    merra2_resp = requests.get(
        f"{BRIGHTHUB_BASE_URL}/reanalysis/MERRA-2/nodes",
        headers=headers,
        params=params,
        timeout=30,
    )
    merra2_resp.raise_for_status()
    merra2_nodes: list[dict] = merra2_resp.json()

    for node in era5_nodes:
        node["distance_sq"] = (node["latitude_ddeg"] - lat) ** 2 + (node["longitude_ddeg"] - lon) ** 2
    for node in merra2_nodes:
        node["distance_sq"] = (node["latitude_ddeg"] - lat) ** 2 + (node["longitude_ddeg"] - lon) ** 2

    era5_nodes.sort(key=lambda n: n["distance_sq"])
    merra2_nodes.sort(key=lambda n: n["distance_sq"])

    return {"era5_nodes": era5_nodes[:4], "merra2_nodes": merra2_nodes[:1]}


def download_reanalysis_data(
    token: str,
    nodes: list[dict],
    dataset_name: str,
) -> list[dict]:
    """Download reanalysis timeseries for a list of nodes.

    Returns a list of dicts with ``latitude``, ``longitude``, ``timeseries_data``,
    and optional ``metadata`` for each node that responded successfully.
    """
    headers = _auth_headers(token)
    if dataset_name not in {"ERA5", "MERRA-2"}:
        raise ValueError(f"Unsupported reanalysis dataset: {dataset_name!r}")
    results: list[dict] = []
    for node in nodes:
        try:
            nlat = float(node["latitude_ddeg"])
            nlon = float(node["longitude_ddeg"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (-90.0 <= nlat <= 90.0) or not (-180.0 <= nlon <= 180.0):
            continue
        if dataset_name == "ERA5":
            variables = "Spd_100m_mps,Dir_100m_deg,Tmp_2m_degC,Prs_0m_hPa"
        else:
            variables = "Spd_50m_mps,Dir_50m_deg,Tmp_2m_degC,Prs_0m_hPa"
        url = f"{BRIGHTHUB_BASE_URL}/reanalysis/{dataset_name}/nodes/{nlat}/{nlon}/data"
        try:
            r = requests.get(url, headers=headers, params={"variables": variables}, timeout=120)
            if r.status_code == 200:
                data = r.json()
                results.append({
                    "latitude": nlat,
                    "longitude": nlon,
                    "timeseries_data": data.get("timeseries_data"),
                    "metadata": data.get("metadata"),
                })
        except (requests.RequestException, ValueError):
            continue
    return results
