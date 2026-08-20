"""brighthub — BrightHub API authentication and data-access client.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import requests

from server.core.spatial import bearing_compass, haversine_km

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


def select_grid_nodes(nodes: list[dict], lat: float, lon: float, count: int = 4) -> list[dict]:
    """Pick ``count`` nodes for spatial interpolation, preferring ones that bracket the site.

    Nearest-N is not the same as bracketing-N. Sorting purely by distance can return
    four nodes all on one side of the site when it sits near a grid-cell corner, which
    silently degrades bilinear interpolation to extrapolation — the interpolator still
    returns a number, and nothing in the result says the site was outside the hull.

    So prefer a set that straddles the site in both axes: take the nearest nodes from
    each of the four quadrants around it where they exist, then backfill by distance.
    On a regular grid with the site inside a cell this returns exactly the cell corners.
    Near a data boundary it degrades to nearest-N, which is the honest fallback.
    """
    by_distance = sorted(nodes, key=lambda n: float(n["distance_km"]))
    if len(by_distance) <= count:
        # Still distance-sorted: callers rely on the order, and returning the raw
        # payload order here would make the sort depend on how many nodes came back.
        return by_distance
    selected: list[dict] = []
    seen: set[int] = set()
    # One node per quadrant first, so the selection straddles the site where it can.
    for want_north in (True, False):
        for want_east in (True, False):
            for index, node in enumerate(by_distance):
                if index in seen:
                    continue
                is_north = float(node["latitude_ddeg"]) >= lat
                is_east = float(node["longitude_ddeg"]) >= lon
                if is_north is want_north and is_east is want_east:
                    selected.append(node)
                    seen.add(index)
                    break
    for index, node in enumerate(by_distance):
        if len(selected) >= count:
            break
        if index not in seen:
            selected.append(node)
            seen.add(index)
    selected.sort(key=lambda n: float(n["distance_km"]))
    return selected[:count]


def fetch_reanalysis_nodes(token: str, lat: float, lon: float) -> dict[str, list[dict]]:
    """Fetch the four nearest ERA5 and four nearest MERRA-2 reanalysis nodes near a coordinate.

    MERRA-2 used to return a single node, which made spatial interpolation impossible
    and left it usable only as a raw node series (design doc §6.1). Both sources now
    return four, selected to bracket the site where the grid allows.

    The search box is sized per source. MERRA-2's grid is 0.5 deg latitude by 0.625 deg
    longitude, so the +/-0.5 deg box that comfortably holds 25 ERA5 nodes can fail to
    hold four MERRA-2 nodes; its longitude half-width is widened accordingly.
    """
    headers = _auth_headers(token)

    def _fetch(dataset: str, half_lat: float, half_lon: float) -> list[dict]:
        response = requests.get(
            f"{BRIGHTHUB_BASE_URL}/reanalysis/{dataset}/nodes",
            headers=headers,
            params={
                "min_latitude_ddeg": lat - half_lat,
                "max_latitude_ddeg": lat + half_lat,
                "min_longitude_ddeg": lon - half_lon,
                "max_longitude_ddeg": lon + half_lon,
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    era5_nodes: list[dict] = _fetch("ERA5", 0.5, 0.5)
    merra2_nodes: list[dict] = _fetch("MERRA-2", 0.75, 0.875)

    for node in era5_nodes:
        node_lat = float(node["latitude_ddeg"])
        node_lon = float(node["longitude_ddeg"])
        node["distance_sq"] = (node_lat - lat) ** 2 + (node_lon - lon) ** 2
        node["distance_km"] = haversine_km(lat, lon, node_lat, node_lon)
        node["bearing"] = bearing_compass(lat, lon, node_lat, node_lon)
    for node in merra2_nodes:
        node_lat = float(node["latitude_ddeg"])
        node_lon = float(node["longitude_ddeg"])
        node["distance_sq"] = (node_lat - lat) ** 2 + (node_lon - lon) ** 2
        node["distance_km"] = haversine_km(lat, lon, node_lat, node_lon)
        node["bearing"] = bearing_compass(lat, lon, node_lat, node_lon)

    return {
        "era5_nodes": select_grid_nodes(era5_nodes, lat, lon, 4),
        "merra2_nodes": select_grid_nodes(merra2_nodes, lat, lon, 4),
    }


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
