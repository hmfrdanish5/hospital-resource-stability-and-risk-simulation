"""Tests for isolated resource sensitivity analysis."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pandemic_bankers"))

from analytics.sensitivity import (
    compute_elasticity,
    default_delta,
    perturb_resource,
    run_isolated_sensitivity,
    run_sensitivity_analysis,
)

RESOURCES = [14, 90, 14, 35, 120]
NAMES = ["ICU_Beds", "Oxygen_Units", "Ventilators", "Nurses", "Blood_Units"]
SEV = {"Mild": 0.6, "Moderate": 0.15, "Severe": 0.15, "Critical": 0.10}
DEMAND = {
    "Mild": {"min": [0, 1, 0, 0, 0], "max": [0, 3, 0, 1, 1]},
    "Moderate": {"min": [0, 3, 0, 1, 1], "max": [0, 6, 0, 2, 2]},
    "Severe": {"min": [0, 6, 0, 2, 2], "max": [1, 12, 1, 3, 4]},
    "Critical": {"min": [1, 10, 1, 3, 3], "max": [1, 20, 1, 5, 6]},
}


def test_default_delta_minimum_one():
    assert default_delta(10) >= 1
    assert default_delta(100) == 10


def test_perturb_resource_isolated():
    base = [10, 20, 30]
    perturbed = perturb_resource(base, 1, 5)
    assert perturbed == [10, 25, 30]
    assert base == [10, 20, 30]


def test_elasticity_arithmetic():
    delta_n50, eps = compute_elasticity(40, 44, 10)
    assert delta_n50 == 4
    assert abs(eps - 0.4) < 1e-12


def test_elasticity_zero_delta_undefined():
    try:
        compute_elasticity(10, 12, 0)
        assert False, "Should have raised"
    except ValueError:
        pass


def test_elasticity_negative_delta():
    delta_n50, eps = compute_elasticity(50, 46, -4)
    assert delta_n50 == -4
    assert abs(eps - 1.0) < 1e-12


def test_elasticity_missing_n50():
    assert compute_elasticity(None, 10, 5) == (None, None)
    assert compute_elasticity(10, None, 5) == (None, None)


def test_isolated_sensitivity_structure():
    result = run_isolated_sensitivity(
        RESOURCES, NAMES, SEV, DEMAND,
        max_patients=8, trials_per_n=5, base_seed=1,
    )
    assert result["analysis_type"] == "isolated_resource_sensitivity"
    assert len(result["rows"]) == len(NAMES)
    assert "elasticity_formula" in result
    for row in result["rows"]:
        assert "resource" in row
        assert "baseline_capacity" in row
        assert "added_capacity" in row
        assert "elasticity" in row
        assert row["new_capacity"] == row["baseline_capacity"] + row["added_capacity"]


def test_elasticity_formula_when_thresholds_exist():
    result = run_isolated_sensitivity(
        RESOURCES, NAMES, SEV, DEMAND,
        max_patients=12, trials_per_n=15, base_seed=7,
    )
    for row in result["rows"]:
        if row["n50_baseline"] is not None and row["n50_perturbed"] is not None:
            expected = row["delta_n50"] / row["added_capacity"]
            assert abs(row["elasticity"] - expected) < 1e-9


def test_run_sensitivity_analysis_alias():
    result = run_sensitivity_analysis(
        RESOURCES, NAMES, SEV, DEMAND,
        max_patients=6, trials_per_n=5, base_seed=2,
    )
    assert "rows" in result
    assert "results" not in result
