"""Every published number on the three reference campaigns is unchanged (Phase 1 gate, P1-0).

The snapshot belongs to the environment it was captured in: a library upgrade that moves a
number fails here too, and is itself a change to record. Refresh deliberately with
``python -m tests.published_numbers --write`` and note the move in CLAUDE.md.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tests.published_numbers import (
    CAMPAIGNS,
    SNAPSHOT_PATH,
    capture,
    differences,
    load_snapshot,
    series_digest,
)


@pytest.mark.parametrize("name", sorted(CAMPAIGNS))
def test_published_numbers_are_identical(name: str) -> None:
    missing = CAMPAIGNS[name].missing_files()
    if missing:
        pytest.skip(f"campaign files not present: {', '.join(str(path) for path in missing)}")
    snapshot = load_snapshot()
    assert name in snapshot, f"{SNAPSHOT_PATH} has no entry for {name}"

    diff = differences(snapshot[name], capture(name))

    assert not diff, (
        f"{len(diff)} published numbers moved on {name}:\n  "
        + "\n  ".join(diff[:30])
        + "\nIf the move is intended: python -m tests.published_numbers --write, and record it."
    )


def test_a_one_ulp_change_alters_the_series_fingerprint() -> None:
    index = pd.date_range("2021-01-01", periods=1000, freq="10min", tz="UTC")
    values = np.linspace(3.0, 15.0, 1000)
    nudged = values.copy()
    nudged[517] = np.nextafter(nudged[517], np.inf)

    assert series_digest(pd.Series(values, index=index)) != series_digest(pd.Series(nudged, index=index))
    assert series_digest(pd.Series(values, index=index)) == series_digest(pd.Series(values.copy(), index=index))


def test_differences_reports_changed_missing_and_new_numbers() -> None:
    expected = {"a": 1.0, "b": 2.0, "c": "nan"}
    actual = {"a": 1.0, "b": 2.0000000000000004, "d": 3}

    report = differences(expected, actual)

    assert report == [
        "changed  b: 2.0 -> 2.0000000000000004",
        "missing  c (was 'nan')",
        "new      d = 3",
    ]
