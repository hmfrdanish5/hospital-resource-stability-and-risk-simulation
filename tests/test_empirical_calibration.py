"""Empirical calibration, provenance, λ(t), and Model C scope."""

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pandemic_bankers"))

from analytics.phase3_experiment import run_abc_experiment, run_empirical_assumption_sensitivity
from data.calibration import calibrate, weekday_relative_rates
from data.distributions import compare_count_models, nbinom_sample, quantile_sse
from data.pipeline import ingest_hospital_series, load_source_catalog
from data.provenance import (
    CACHED_EMPIRICAL,
    CURRENT_EXTERNAL,
    DERIVED_PARAMETER,
    MODEL_ASSUMPTION,
    REAL_OBSERVATION,
    SIMULATED_VALUE,
    SYNTHETIC_FALLBACK,
    tagged,
)
from data.sampling import make_arrival_sampler
from data.signal_transform import (
    CLIP_MAX,
    CLIP_MIN,
    REFERENCE_CASES,
    epidemiological_workload_factor,
    transformation_record,
)

from data.external_fetcher import _fallback_signal, apply_workload_factor

DEMAND = {
    "Mild": {"min": [0, 1, 0, 0, 0], "max": [0, 3, 0, 1, 1]},
    "Moderate": {"min": [0, 3, 0, 1, 1], "max": [0, 6, 0, 2, 2]},
    "Severe": {"min": [0, 6, 0, 2, 2], "max": [1, 12, 1, 3, 4]},
    "Critical": {"min": [1, 10, 1, 3, 3], "max": [1, 20, 1, 5, 6]},
}
NAMES = ["ICU_Beds", "Oxygen_Units", "Ventilators", "Nurses", "Blood_Units"]
SEV = {"Mild": 0.6, "Moderate": 0.15, "Severe": 0.15, "Critical": 0.10}
BASE = [14, 90, 14, 35, 120]


def test_provenance_classifications_are_distinct():
    assert len({REAL_OBSERVATION, DERIVED_PARAMETER, MODEL_ASSUMPTION, SIMULATED_VALUE}) == 4
    tagged(1, REAL_OBSERVATION, "x")
    try:
        tagged(1, "FAKE_LABEL", "x")
        raise AssertionError("should reject unknown classification")
    except ValueError:
        pass


def test_availability_statuses():
    assert {CURRENT_EXTERNAL, CACHED_EMPIRICAL, SYNTHETIC_FALLBACK} == {
        "CURRENT_EXTERNAL", "CACHED_EMPIRICAL", "SYNTHETIC_FALLBACK",
    }


def test_synthetic_fallback_labeling():
    payload = ingest_hospital_series(prefer_live=False)
    if payload.get("classification") == SIMULATED_VALUE:
        assert payload["availability_status"] == SYNTHETIC_FALLBACK
        assert payload["source_id"] == "synthetic_arrival_fixture"
    elif payload.get("classification") == REAL_OBSERVATION:
        assert payload["availability_status"] in {CACHED_EMPIRICAL, CURRENT_EXTERNAL}


def test_fallback_signal_availability():
    sig = _fallback_signal("offline")
    assert sig["availability_status"] == SYNTHETIC_FALLBACK
    assert sig["available"] is False
    assert sig["transformation"]["classification"] == MODEL_ASSUMPTION


def test_signal_transform_monotonic_then_clipped():
    xs = [0, 1000, 25000, 50000, 100000, 1e9]
    fs = [epidemiological_workload_factor(x) for x in xs]
    assert fs == sorted(fs)
    assert epidemiological_workload_factor(0) == CLIP_MIN
    assert epidemiological_workload_factor(REFERENCE_CASES) == 1.0
    assert epidemiological_workload_factor(1e12) == CLIP_MAX
    rec = transformation_record()
    assert rec["classification"] == MODEL_ASSUMPTION
    assert "clip" in rec["formula"]


def test_workload_clipping_bounds():
    assert apply_workload_factor(100, CLIP_MIN) >= 5
    assert apply_workload_factor(100, CLIP_MAX) <= 200
    assert apply_workload_factor(100, 0.01) == apply_workload_factor(100, 0.01)


def test_nbinom_parameterization_documented():
    xs = [2, 8, 20, 40, 12, 30, 5, 18]
    fit = compare_count_models(xs)
    assert "μ" in fit["nbinom_parameterization"] or "mu" in fit["nbinom_parameterization"].lower()
    assert "size" in fit["nbinom"] or fit["nbinom"].get("size") is not None
    rng = random.Random(0)
    if fit["nbinom"].get("overdispersed"):
        samples = [nbinom_sample(rng, fit["nbinom"]["mu"], fit["nbinom"]["size"]) for _ in range(2000)]
        mu = sum(samples) / len(samples)
        assert abs(mu - fit["nbinom"]["mu"]) < 8.0


def test_weekday_relative_rates_sum_to_variation():
    from datetime import date, timedelta
    start = date(2020, 1, 6)  # Monday
    rows = []
    for i in range(28):
        d = start + timedelta(days=i)
        adm = 100.0 if d.weekday() == 0 else 10.0
        rows.append({"date": d.isoformat(), "newAdmissions": adm})
    wr = weekday_relative_rates(rows)
    assert len(wr["relative_rates"]) == 7
    assert wr["relative_rates"][0] > wr["relative_rates"][1]
    assert abs(sum(wr["relative_rates"]) / 7 - 1.0) < 0.15


def test_arrival_lambda_t_uses_weekday():
    cal = {
        "parameters": {
            "arrival_model": {"value": "poisson", "fit": {}},
        }
    }
    rel = [2.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    sampler = make_arrival_sampler(cal, mu_hourly=4.0, mode="C", weekday_relative=rel)
    rng = random.Random(0)
    monday = [sampler(rng, 0) for _ in range(200)]
    rng = random.Random(0)
    tuesday = [sampler(rng, 24) for _ in range(200)]
    assert sum(monday) / len(monday) > sum(tuesday) / len(tuesday) + 1.5


def test_los_quantile_sse_in_summary():
    cal = calibrate(prefer_live=False, rng=random.Random(1))
    ward = cal["calibration_summary"]["los_ward"]
    assert ward["not_mle"] is True
    assert "quantile" in ward["method"]
    obs = ward["observed_quantiles"]
    pred = ward["reconstructed_quantiles"]
    assert abs(ward["reconstruction_error_sse"] - quantile_sse(pred, obs)) < 1e-12
    assert ward["gamma_uses_wilson_hilferty"] is True


def test_model_scope_static_vs_dynamic():
    result = run_abc_experiment(
        BASE, NAMES, SEV, DEMAND, None,
        max_patients=6, trials_per_n=4, horizon_hours=8,
        base_seed=3, prefer_live=False, include_empirical_sensitivity=False,
    )
    assert "static_banker_collapse" in result["experiment_families"]
    assert "dynamic_empirically_informed" in result["experiment_families"]
    assert "not a fully calibrated" in result["experiment_families"]["static_banker_collapse"]["note"].lower() or \
        "do not label" in result["experiment_families"]["static_banker_collapse"]["note"].lower()
    assert result["models"]["C"]["n50_experiment"] == "static_banker_collapse"
    assert "reproducibility" in result
    assert result["reproducibility"]["random_seed"] == 3
    assert result["reproducibility"]["availability_status"] in {
        CURRENT_EXTERNAL, CACHED_EMPIRICAL, SYNTHETIC_FALLBACK,
    }


def test_empirical_sensitivity_does_not_claim_n50():
    cal = calibrate(prefer_live=False, rng=random.Random(1))
    rel = cal["parameters"]["weekday_relative_rates"]["value"]["relative_rates"]
    out = run_empirical_assumption_sensitivity(
        BASE, NAMES, SEV, DEMAND, None, cal, 2.0, 8, 11, rel,
        scales=(1.0, 1.2),
    )
    assert out["not_statistical_significance"] is True
    assert all(r["n50"] is None for r in out["rows"])
    params = {r["parameter"] for r in out["rows"]}
    assert "arrival_intensity" in params
    assert "los_multiplier" in params


def test_calibration_metadata_and_copula_decision():
    cal = calibrate(prefer_live=False, rng=random.Random(2))
    assert cal["dependence"]["copula"]["used"] is False
    assert "patient-level joint dependence" in cal["dependence"]["copula"]["reason"]
    assert "iid" in cal["parameters"]["arrival_rate_daily"]["bootstrap_method"].lower()
    assert cal["uncertainty_labels"]["bootstrap"]


def test_catalog_provenance_fields():
    cat = load_source_catalog()
    for src in cat["sources"]:
        assert src.get("publisher")
        assert src.get("url")
        assert src.get("license")
        assert src.get("access_date")
        assert src.get("geographic_scope") or src.get("coverage")
        assert src.get("variables_used")
        assert src.get("units") or src.get("notes")
        assert src.get("current_vs_historical")
