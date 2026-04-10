"""ltc — WindKit long-term correction MCP tools.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json

import windkit
import windkit.ltc
from server.main import mcp
from server.tools.windkit._serializers import _ok, ds_to_dict, dict_to_ds


@mcp.tool()
def windkit_ltc_linreg_mcp(measured_dataset: str, reference_dataset: str,
                             ws_cutoff: float = 0.0, n_sectors: int = 12) -> dict:
    """Run sectorwise MCP using linear regression (WindKit LTC).

    Args:
        measured_dataset: JSON-serialized TSWC xarray Dataset of measured data.
        reference_dataset: JSON-serialized TSWC xarray Dataset of reference data.
        ws_cutoff: Wind speed cutoff for fitting (default 0.0).
        n_sectors: Number of direction sectors (default 12).
    """
    meas = dict_to_ds(json.loads(measured_dataset))
    ref = dict_to_ds(json.loads(reference_dataset))
    model = windkit.ltc.LinRegMCP(ws_cutoff=ws_cutoff)
    model.fit(meas, ref, n_sectors=n_sectors)
    predicted = model.predict(ref)
    return _ok({
        "predicted": ds_to_dict(predicted),
        "scores": {k: float(v) for k, v in windkit.ltc.calc_scores(meas, predicted).items()}
        if hasattr(windkit.ltc, "calc_scores") else {},
    })


@mcp.tool()
def windkit_ltc_varrat_mcp(measured_dataset: str, reference_dataset: str,
                             fit_intercept: bool = True, ws_cutoff: float = 0.0,
                             n_sectors: int = 12) -> dict:
    """Run sectorwise MCP using variance ratio regression (WindKit LTC).

    Args:
        measured_dataset: JSON-serialized TSWC xarray Dataset of measured data.
        reference_dataset: JSON-serialized TSWC xarray Dataset of reference data.
        fit_intercept: Whether to fit intercept (default True).
        ws_cutoff: Wind speed cutoff (default 0.0).
        n_sectors: Number of direction sectors (default 12).
    """
    meas = dict_to_ds(json.loads(measured_dataset))
    ref = dict_to_ds(json.loads(reference_dataset))
    model = windkit.ltc.VarRatMCP(fit_intercept=fit_intercept, ws_cutoff=ws_cutoff)
    model.fit(meas, ref, n_sectors=n_sectors)
    predicted = model.predict(ref)
    return _ok({
        "predicted": ds_to_dict(predicted),
        "scores": {k: float(v) for k, v in windkit.ltc.calc_scores(meas, predicted).items()}
        if hasattr(windkit.ltc, "calc_scores") else {},
    })
