"""Tests for external data fetcher."""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pandemic_bankers"))

from data.external_fetcher import _fallback_signal, apply_workload_factor, fetch_external_signal
from data.signal_transform import CLIP_MAX, CLIP_MIN, epidemiological_workload_factor


def test_fallback_signal():
    sig = _fallback_signal("network error")
    assert sig["available"] is False
    assert sig["workload_factor"] == 1.0
    assert "fallback_reason" in sig
    assert sig["data_type"] == "synthetic_fallback"
    assert sig["data_status"] == "SYNTHETIC_FALLBACK"


def test_apply_workload_factor_bounds():
    assert apply_workload_factor(60, 0.1) >= 5
    assert apply_workload_factor(60, 10.0) <= 200


def test_workload_factor_monotonic_then_clipped():
    xs = [10_000.0, 25_000.0, 50_000.0, 100_000.0, 500_000.0]
    factors = [epidemiological_workload_factor(x) for x in xs]
    for a, b in zip(factors, factors[1:]):
        assert a <= b
    assert all(CLIP_MIN <= f <= CLIP_MAX for f in factors)
    assert factors[0] == CLIP_MIN
    assert factors[-1] == CLIP_MAX


def _mock_rows(avg_value: float) -> list[dict[str, str]]:
    rows = []
    for i in range(20):
        rows.append({
            "iso_code": "OWID_WRL",
            "date": f"2020-03-{i + 1:02d}",
            "new_cases_smoothed": str(avg_value + i),
        })
    return rows


@patch("data.external_fetcher.write_cache")
@patch("data.external_fetcher.read_cache", return_value=None)
@patch("data.external_fetcher._fetch_global_rows")
def test_external_signal_live_differs_by_payload(mock_fetch, _read, _write):
    mock_fetch.side_effect = [_mock_rows(20_000.0), _mock_rows(80_000.0)]
    a = fetch_external_signal(prefer_live=True)
    b = fetch_external_signal(prefer_live=True)
    assert a["data_status"] == "LIVE_EXTERNAL"
    assert b["data_status"] == "LIVE_EXTERNAL"
    assert a["derived_workload_factor"] != b["derived_workload_factor"]
    assert a["external_signal_value"] != b["external_signal_value"]


@patch("data.external_fetcher._fetch_global_rows")
def test_external_signal_cached_is_reproducible(mock_fetch):
    cached = {
        "avg_new_cases_smoothed_14d": 42_000.0,
        "workload_factor": epidemiological_workload_factor(42_000.0),
        "last_data_date": "2020-03-20",
        "source": "cache",
    }
    with patch("data.external_fetcher.read_cache", return_value=cached):
        a = fetch_external_signal(prefer_live=False)
        b = fetch_external_signal(prefer_live=False)
    mock_fetch.assert_not_called()
    assert a["data_status"] == "CACHED_EMPIRICAL"
    assert a == b
    assert a["reproducibility"] == "REPRODUCIBLE_CACHED"
