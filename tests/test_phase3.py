"""Phase 3: ingestion, fitting, calibration, sampling, fallback, experiment."""

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pandemic_bankers"))

from analytics.phase3_experiment import run_abc_experiment, run_parameter_sensitivity
from data.calibration import calibrate
from data.distributions import compare_count_models, fit_los_from_quantiles, poisson_sample
from data.pipeline import (
    _validate_rows,
    ingest_hospital_series,
    load_literature_los,
    load_source_catalog,
    synthetic_arrival_fixture,
)
from data.provenance import DERIVED_PARAMETER, REAL_OBSERVATION, SIMULATED_VALUE
from data.sampling import generate_demands_independent, generate_demands_severity_conditioned

DEMAND = {
    "Mild": {"min": [0, 1, 0, 0, 0], "max": [0, 3, 0, 1, 1]},
    "Moderate": {"min": [0, 3, 0, 1, 1], "max": [0, 6, 0, 2, 2]},
    "Severe": {"min": [0, 6, 0, 2, 2], "max": [1, 12, 1, 3, 4]},
    "Critical": {"min": [1, 10, 1, 3, 3], "max": [1, 20, 1, 5, 6]},
}
NAMES = ["ICU_Beds", "Oxygen_Units", "Ventilators", "Nurses", "Blood_Units"]
SEV = {"Mild": 0.6, "Moderate": 0.15, "Severe": 0.15, "Critical": 0.10}
BASE = [14, 90, 14, 35, 120]


def test_source_catalog_loads():
    cat = load_source_catalog()
    ids = {s["id"] for s in cat["sources"]}
    assert "owid_covid" in ids
    assert "rees_2020_los" in ids
    for src in cat["sources"]:
        assert src.get("license")
        assert src.get("current_vs_historical")
        assert src.get("url")


def test_literature_los_is_observation_summary():
    lit = load_literature_los()
    assert lit["classification"] == REAL_OBSERVATION
    assert lit["hospital_los_days"]["median"] == 5
    assert lit["icu_los_days"]["q75"] == 11


def test_validate_rows_drops_malformed_and_missing():
    rows = [
        {"date": "2020-01-01", "newAdmissions": "10", "hospitalCases": "20", "covidOccupiedMVBeds": "3"},
        {"date": "", "newAdmissions": "10"},
        {"date": "2020-01-02", "newAdmissions": "not-a-number", "hospitalCases": "", "covidOccupiedMVBeds": None},
        {"date": "2020-01-03", "newAdmissions": "-5", "hospitalCases": "1", "covidOccupiedMVBeds": "0"},
        "bad",
    ]
    cleaned = _validate_rows(rows, ["newAdmissions", "hospitalCases", "covidOccupiedMVBeds"])
    dates = [r["date"] for r in cleaned]
    assert "2020-01-01" in dates
    assert "2020-01-02" not in dates


def test_poisson_preferred_when_equidispersed():
    rng = random.Random(0)
    xs = [poisson_sample(rng, 6.0) for _ in range(400)]
    result = compare_count_models(xs)
    assert result["dispersion"] < 1.4
    assert result["chosen_family"] == "poisson"


def test_nbinom_preferred_when_overdispersed():
    fixture = synthetic_arrival_fixture(n_days=120, seed=2020)
    xs = [int(r["newAdmissions"]) for r in fixture["rows"]]
    result = compare_count_models(xs)
    assert result["overdispersion"] is True
    assert result["chosen_family"] == "nbinom"


def test_poisson_sample_moments_small_and_large():
    for lam in (0.5, 4.0, 35.0):
        rng = random.Random(0)
        xs = [poisson_sample(rng, lam) for _ in range(4000)]
        mu = sum(xs) / len(xs)
        var = sum((x - mu) ** 2 for x in xs) / (len(xs) - 1)
        assert abs(mu - lam) < 0.25 + 0.08 * lam
        assert abs(var - lam) < 0.4 + 0.12 * lam
        assert min(xs) >= 0


def test_los_compares_three_families():
    fit = fit_los_from_quantiles(3, 5, 9)
    families = {c["family"] for c in fit["candidates"]}
    assert families == {"gamma", "weibull", "lognormal"}
    assert fit["chosen_family"] in families
    assert fit["chosen"]["sse"] == min(c["sse"] for c in fit["candidates"])
    assert fit["comparison_metric"] == "quantile_reconstruction_sse"
    assert fit["not_a_gof_test"] is True
    expected = sum((fit["chosen"]["predicted"][k] - fit["target_quantiles"][k]) ** 2 for k in ("q25", "median", "q75"))
    assert abs(fit["chosen"]["sse"] - expected) < 1e-15


def test_fallback_ingest_is_labeled_simulated():
    payload = ingest_hospital_series(prefer_live=False)
    if payload["source_id"] == "synthetic_arrival_fixture":
        assert payload["classification"] == SIMULATED_VALUE
        from data.provenance import SYNTHETIC_FALLBACK
        assert payload["availability_status"] == SYNTHETIC_FALLBACK


def test_calibration_separates_raw_and_derived():
    cal = calibrate(prefer_live=False, rng=random.Random(1))
    assert "rows" not in cal
    assert cal["parameters"]["arrival_rate_hourly"]["classification"] == DERIVED_PARAMETER
    assert cal["dependence"]["copula"]["used"] is False
    assert cal["los_provenance"]["classification"] == REAL_OBSERVATION
    assert "calibration_summary" in cal
    assert cal["calibration_summary"]["availability_status"] in {
        "CURRENT_EXTERNAL", "CACHED_EMPIRICAL", "SYNTHETIC_FALLBACK",
    }
    assert cal["parameters"]["weekday_relative_rates"]["value"]["relative_rates"]


def test_calibration_reproducible():
    a = calibrate(prefer_live=False, rng=random.Random(7))
    b = calibrate(prefer_live=False, rng=random.Random(7))
    assert a["parameters"]["arrival_rate_daily"]["value"] == b["parameters"]["arrival_rate_daily"]["value"]


def test_joint_sampling_couples_icu_and_vent():
    rng = random.Random(3)
    for _ in range(40):
        alloc, mx = generate_demands_severity_conditioned("Severe", DEMAND, 5, rng, p_icu_severe=1.0)
        assert mx[0] == mx[2] == 1
        assert alloc[0] == alloc[2] == 1
        _, mx0 = generate_demands_severity_conditioned("Mild", DEMAND, 5, rng, p_icu_severe=1.0)
        assert mx0[0] == mx0[2] == 0


def test_independent_sampling_can_split_severe_icu_vent():
    rng = random.Random(0)
    split = False
    for _ in range(80):
        _, mx = generate_demands_independent("Severe", DEMAND, 5, rng)
        if mx[0] != mx[2]:
            split = True
            break
    assert split is True


def test_abc_experiment_structure():
    result = run_abc_experiment(
        BASE, NAMES, SEV, DEMAND, None,
        max_patients=6, trials_per_n=5, horizon_hours=8,
        base_seed=2, prefer_live=False, include_empirical_sensitivity=False,
    )
    assert set(result["models"]) == {"A", "B", "C"}
    assert result["copula_used"] is False
    for mode in ("A", "B", "C"):
        assert "overflow" in result["models"][mode]
        assert len(result["models"][mode]["probability_curve"]) == 6
    assert "experiment_scope" in result
    assert "experiment_families" in result
    assert "same demand generator as B" in result["models"]["C"]["description"]


def test_parameter_sensitivity_ranks():
    result = run_parameter_sensitivity(
        BASE, NAMES, SEV, DEMAND, None,
        max_patients=6, trials_per_n=4, base_seed=2, prefer_live=False,
    )
    assert result["rows"]
    params = {r["parameter"] for r in result["rows"]}
    assert "p_icu_severe" in params
    assert "critical_share" in params
