"""Tests for Monte Carlo simulation and Wilson CI."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pandemic_bankers"))

from simulation.monte_carlo import (
    monte_carlo_sweep,
    run_single_trial,
    threshold_at_probability,
    wilson_ci,
    CI_METHOD,
)
import random


DEMAND = {
    "Mild": {"min": [0, 1, 0, 0, 0], "max": [0, 3, 0, 1, 1]},
    "Moderate": {"min": [0, 3, 0, 1, 1], "max": [0, 6, 0, 2, 2]},
    "Severe": {"min": [0, 6, 0, 2, 2], "max": [1, 12, 1, 3, 4]},
    "Critical": {"min": [1, 10, 1, 3, 3], "max": [1, 20, 1, 5, 6]},
}
RESOURCES = [14, 90, 14, 35, 120]
NAMES = ["ICU_Beds", "Oxygen_Units", "Ventilators", "Nurses", "Blood_Units"]
SEV = {"Mild": 0.6, "Moderate": 0.15, "Severe": 0.15, "Critical": 0.10}


def test_wilson_ci_p_zero():
    p, lo, hi = wilson_ci(0, 100)
    assert p == 0.0
    assert lo == 0.0
    assert hi >= 0.0


def test_wilson_ci_p_one():
    p, lo, hi = wilson_ci(50, 50)
    assert p == 1.0
    assert hi == 1.0


def test_wilson_ci_zero_trials():
    p, lo, hi = wilson_ci(0, 0)
    assert p == 0.0 and lo == 0.0 and hi == 0.0


def test_wilson_ci_small_trials():
    p, lo, hi = wilson_ci(1, 3)
    assert 0.0 <= p <= 1.0
    assert lo <= p <= hi


def test_seed_reproducibility():
    rng1 = random.Random(99)
    rng2 = random.Random(99)
    r1 = run_single_trial(RESOURCES, NAMES, 10, SEV, DEMAND, rng1)
    r2 = run_single_trial(RESOURCES, NAMES, 10, SEV, DEMAND, rng2)
    assert r1 == r2


def test_run_single_trial_return_shape():
    rng = random.Random(1)
    result = run_single_trial(RESOURCES, NAMES, 5, SEV, DEMAND, rng)
    assert len(result) == 5
    collapsed, admission_failed, unsafe, util, admitted = result
    assert isinstance(collapsed, bool)
    assert isinstance(admission_failed, bool)
    assert isinstance(unsafe, bool)
    assert isinstance(util, dict)
    assert admitted <= 5


def test_monte_carlo_sweep_structure():
    result = monte_carlo_sweep(
        RESOURCES, NAMES, SEV, DEMAND,
        max_patients=5, trials_per_n=10, base_seed=42,
    )
    assert result["ci_method"] == CI_METHOD
    assert len(result["probability_curve"]) == 5
    entry = result["probability_curve"][0]
    assert 0.0 <= entry["p_collapse"] <= 1.0
    assert entry["ci_lo"] <= entry["p_collapse"] <= entry["ci_hi"] or entry["p_collapse"] in (0.0, 1.0)
    assert "p_unsafe" in entry
    assert "p_admission_failure" in entry


def test_threshold_at_probability():
    curve = [
        {"n": 1, "p_collapse": 0.05},
        {"n": 2, "p_collapse": 0.55},
        {"n": 3, "p_collapse": 0.80},
    ]
    assert threshold_at_probability(curve, "p_collapse", 0.50) == 2
    assert threshold_at_probability(curve, "p_collapse", 0.90) is None


def test_n50_is_discrete_min_without_interpolation():
    curve = [
        {"n": 37, "p_collapse": 0.47},
        {"n": 38, "p_collapse": 0.53},
    ]
    assert threshold_at_probability(curve, "p_collapse", 0.50) == 38


def test_p_hat_equals_k_over_t():
    p, _, _ = wilson_ci(0, 40)
    assert p == 0.0
    p, _, _ = wilson_ci(40, 40)
    assert p == 1.0
    p, _, _ = wilson_ci(13, 40)
    assert p == 13 / 40


def test_wilson_formula_matches_definition():
    import math
    k, n, z = 8, 20, 1.96
    p = k / n
    z2 = z * z
    centre = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = (z / (1 + z2 / n)) * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    got_p, lo, hi = wilson_ci(k, n, z)
    assert got_p == p
    assert abs(lo - max(0.0, centre - half)) < 1e-15
    assert abs(hi - min(1.0, centre + half)) < 1e-15
