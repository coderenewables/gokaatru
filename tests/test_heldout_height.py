"""test_heldout_height — pipeline-level held-out height oracle on real campaigns.

Part of GoKaatru MCP Server.

Fit the shear table on the sensors below a height, extrapolate to a sensor that was
withheld from the fit, and compare the predicted series mean with the measured one. The
measured sensor is the truth, so this checks the whole shear-to-hub path end to end on real
data rather than one formula on synthetic data.

Horns Rev is deliberately absent: its sensors were installed at different dates, so the
comparison confounds extrapolation error with installation history.
"""
from __future__ import annotations

import json

from server.state.session import session
from server.tools.data_io import _parse_datamodel, _parse_timeseries
from server.tools.extrapolation import _extrapolate_to_hub_height
from server.tools.shear import _build_shear_table, _calculate_shear_timeseries
from tests.conftest import require_campaign_file

MAX_ABS_BIAS = 0.01
MIN_COVERAGE = 0.99
# Speed above which a record counts as valid for the nearest fit sensor; matches the
# extrapolation's own valid-record mask so coverage is judged on the same population.
VALID_SPEED_MPS = 0.1


def _held_out_bias(state, fit_columns: dict[str, str], target: str, hub: float, nearest: str) -> dict:
    """Fit on ``fit_columns`` (height key -> column), predict ``target``'s height, compare means."""
    _calculate_shear_timeseries(state, json.dumps(fit_columns))
    _build_shear_table(state, "mean")
    result = _extrapolate_to_hub_height(
        state, hub, "power_law", reference_columns=list(fit_columns.values())
    )
    pred = state.timeseries_df[result["column_name"]]
    truth = state.timeseries_df[target]
    # Means over each series' own records, deliberately not restricted to common records: a
    # comparison on common records hides a truncated prediction, which is the defect this
    # test exists to catch (dropping low-wind records moves the predicted mean by +23%).
    nearest_valid = state.timeseries_df[nearest] > VALID_SPEED_MPS
    return {
        "bias": float(pred.mean() / truth.mean() - 1.0),
        "coverage": float(pred[nearest_valid].notna().sum() / nearest_valid.sum()),
        "result": result,
        "pred": pred,
    }


def _load_launakalana():
    timeseries = require_campaign_file("WB-ESMAP_Launakalana_timeseries_data.csv")
    datamodel = require_campaign_file("WB-ESMAP_Launakalana_data_model.json")
    _parse_timeseries(session, str(timeseries))
    _parse_datamodel(session, str(datamodel))
    return session


def test_launakalana_held_out_80m_from_40_and_60m_is_unbiased():
    """Predict the withheld 80 m sensor from 40 m and 60 m on the 2-year Launakalana campaign."""
    state = _load_launakalana()
    fit = {"40": "Spd5_40m_25deg", "60": "Spd3_60m_25deg"}
    target = "Spd1_80m_25deg"

    out = _held_out_bias(state, fit, target, 80.001, nearest="Spd3_60m_25deg")

    assert out["result"]["status"] == "ok"
    assert abs(out["bias"]) < MAX_ABS_BIAS, f"held-out bias {out['bias']:.4%}"
    assert out["coverage"] >= MIN_COVERAGE, f"coverage {out['coverage']:.4%}"


def test_boxkite_held_out_250m_from_180m_and_200m_is_unbiased(uploaded_dataset_session):
    """Predict the withheld 250 m lidar height from 180 m and 200 m on the Boxkite campaign."""
    state = uploaded_dataset_session
    fit = {"180": "Spd_180m", "200": "Spd_200m"}
    target = "Spd_250m"

    out = _held_out_bias(state, fit, target, 250.001, nearest="Spd_200m")

    assert out["result"]["status"] == "ok"
    assert abs(out["bias"]) < MAX_ABS_BIAS, f"held-out bias {out['bias']:.4%}"
    assert out["coverage"] >= MIN_COVERAGE, f"coverage {out['coverage']:.4%}"
