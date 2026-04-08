"""conftest — Shared pytest fixtures for GoKaatru Phase 1 tests.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from server.state.session import session
from server.tools.data_io import _parse_datamodel, _parse_timeseries


REPO_ROOT = Path(__file__).resolve().parents[1]
UPLOADS_DIR = REPO_ROOT / "data" / "uploads"


@pytest.fixture(autouse=True)
def reset_session() -> None:
    """Reset the singleton session before and after each test per the Phase 1 test pattern."""
    session.reset()
    yield
    session.reset()


@pytest.fixture
def sample_timeseries_df() -> pd.DataFrame:
    """Create a synthetic one-year 10-minute dataset with a known power-law shear coefficient."""
    np.random.seed(42)
    index = pd.date_range("2023-01-01", "2023-12-31 23:50", freq="10min")
    alpha = 0.14
    wind_100m = np.random.weibull(2.0, len(index)) * 8.0
    wind_80m = wind_100m * (80 / 100) ** alpha
    wind_60m = wind_100m * (60 / 100) ** alpha
    directions = np.random.uniform(0, 360, len(index))
    return pd.DataFrame(
        {
            "Timestamp": index,
            "Spd_100m": wind_100m,
            "Spd_80m": wind_80m,
            "Spd_60m": wind_60m,
            "Dir_100m": directions,
            "Spd_100m_sd": wind_100m * 0.1,
        }
    ).set_index("Timestamp")


@pytest.fixture(scope="session")
def uploaded_timeseries_path() -> Path:
    """Return the checked-in Boxkite timeseries dataset used for realistic workflow tests."""
    path = UPLOADS_DIR / "HKW-B-FLS-Boxkite_timeseries_data.csv"
    assert path.exists()
    return path


@pytest.fixture(scope="session")
def uploaded_datamodel_path() -> Path:
    """Return the checked-in Boxkite datamodel used for realistic workflow tests."""
    path = UPLOADS_DIR / "HKW-B-FLS-Boxkite_data_model.json"
    assert path.exists()
    return path


@pytest.fixture
def uploaded_dataset_session(uploaded_timeseries_path: Path, uploaded_datamodel_path: Path):
    """Load the real uploaded dataset into the singleton session for helper-level tests."""
    _parse_timeseries(session, str(uploaded_timeseries_path))
    _parse_datamodel(session, str(uploaded_datamodel_path))
    return session
