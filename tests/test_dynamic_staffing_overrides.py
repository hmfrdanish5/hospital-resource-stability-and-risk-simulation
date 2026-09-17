"""Per-run dynamic staffing multiplier overrides (Time Model UI)."""

import copy
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pandemic_bankers"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from simulation.dynamic_hospital import run_dynamic_simulation
from simulation.time_model import (
    apply_staffing_overrides,
    merge_dynamic_config,
    nurse_capacity,
    staffing_multiplier,
)
from utils.config_loader import ConfigLoader

CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "pandemic_bankers", "hospital_config.json"
)
BASE = [14, 90, 14, 35, 120]
NAMES = ["ICU_Beds", "Oxygen_Units", "Ventilators", "Nurses", "Blood_Units"]
SEV = {"Mild": 0.6, "Moderate": 0.15, "Severe": 0.15, "Critical": 0.10}
DEMAND = {
    "Mild": {"min": [0, 1, 0, 0, 0], "max": [0, 3, 0, 1, 1]},
    "Moderate": {"min": [0, 3, 0, 1, 1], "max": [0, 6, 0, 2, 2]},
    "Severe": {"min": [0, 6, 0, 2, 2], "max": [1, 12, 1, 3, 4]},
    "Critical": {"min": [1, 10, 1, 3, 3], "max": [1, 20, 1, 5, 6]},
}


def _cfg():
    return ConfigLoader(CONFIG_PATH)


def _run_dynamic(dynamic_cfg, seed=42, horizon=16, arrivals=2):
    cfg = _cfg()
    return run_dynamic_simulation(
        base_capacity=cfg.resource_totals(cfg.simulation_mode),
        resource_names=cfg.resource_names,
        dynamic_cfg=dynamic_cfg,
        severity_dist=cfg.severity_distribution(cfg.severity_mode),
        demand_profiles=cfg.raw()["demand_profiles"],
        seed=seed,
        horizon_hours=horizon,
        arrivals_per_step=arrivals,
    )


def _dynamic_cfg_with_overrides(overrides=None):
    cfg = merge_dynamic_config(_cfg().dynamic_model())
    cfg["staffing"] = apply_staffing_overrides(cfg["staffing"], overrides or {})
    return cfg


def test_omitted_staffing_uses_config_defaults():
    cfg = merge_dynamic_config(_cfg().dynamic_model())
    staffing = cfg["staffing"]
    assert staffing_multiplier(7, staffing) == staffing["handover_multiplier"]
    assert nurse_capacity(35, 7, staffing) == 28


def test_explicit_defaults_match_config_behavior():
    baseline = _run_dynamic(merge_dynamic_config(_cfg().dynamic_model()))
    explicit = _run_dynamic(_dynamic_cfg_with_overrides({
        "normal_staffing_multiplier": 1.0,
        "handover_staffing_multiplier": 0.80,
        "weekend_staffing_multiplier": 0.90,
    }))
    assert baseline["secondary_metrics"] == explicit["secondary_metrics"]
    assert baseline["state_counts"] == explicit["state_counts"]


def test_staffing_override_propagates_to_capacity():
    cfg = _dynamic_cfg_with_overrides({
        "normal_staffing_multiplier": 1.20,
        "handover_staffing_multiplier": 0.96,
        "weekend_staffing_multiplier": 1.08,
    })
    staffing = cfg["staffing"]
    default = merge_dynamic_config(_cfg().dynamic_model())["staffing"]
    assert nurse_capacity(35, 8, staffing) > nurse_capacity(35, 8, default)


def test_staffing_override_changes_simulation():
    baseline = _run_dynamic(_dynamic_cfg_with_overrides({
        "normal_staffing_multiplier": 1.0,
        "handover_staffing_multiplier": 0.80,
        "weekend_staffing_multiplier": 0.90,
    }), horizon=168)
    reduced = _run_dynamic(_dynamic_cfg_with_overrides({
        "normal_staffing_multiplier": 0.80,
        "handover_staffing_multiplier": 0.64,
        "weekend_staffing_multiplier": 0.72,
    }), horizon=168)
    assert baseline["secondary_metrics"]["banker_unsafe_timesteps"] != reduced["secondary_metrics"]["banker_unsafe_timesteps"]


def test_apply_staffing_overrides_rejects_invalid():
    base = merge_dynamic_config({})["staffing"]
    for bad in ("x", None):
        try:
            apply_staffing_overrides(base, {"normal_staffing_multiplier": bad})
            assert False, f"expected rejection for {bad!r}"
        except ValueError:
            pass
    try:
        apply_staffing_overrides(base, {"normal_staffing_multiplier": -0.1})
        assert False
    except ValueError:
        pass
    try:
        apply_staffing_overrides(base, {"weekend_staffing_multiplier": 3.1})
        assert False
    except ValueError:
        pass


def test_flask_dynamic_staffing_validation_and_defaults():
    from pandemic_dashboard.app import app

    client = app.test_client()
    baseline = client.post(
        "/api/dynamic_simulation",
        json={"horizon_hours": 16, "arrivals_per_step": 2, "seed": 42},
    )
    assert baseline.status_code == 200
    explicit = client.post(
        "/api/dynamic_simulation",
        json={
            "horizon_hours": 16,
            "arrivals_per_step": 2,
            "seed": 42,
            "normal_staffing_multiplier": 1.0,
            "handover_staffing_multiplier": 0.80,
            "weekend_staffing_multiplier": 0.90,
        },
    )
    assert explicit.status_code == 200
    b = baseline.get_json()
    e = explicit.get_json()
    assert b["secondary_metrics"] == e["secondary_metrics"]

    bad = client.post(
        "/api/dynamic_simulation",
        json={"normal_staffing_multiplier": "not-a-number"},
    )
    assert bad.status_code == 400

    neg = client.post(
        "/api/dynamic_simulation",
        json={"normal_staffing_multiplier": -0.5},
    )
    assert neg.status_code == 400

    high = client.post(
        "/api/dynamic_simulation",
        json={"handover_staffing_multiplier": 3.5},
    )
    assert high.status_code == 400


def test_hospital_config_not_mutated_by_override():
    cfg = _cfg()
    before = copy.deepcopy(cfg.raw()["dynamic_model"]["staffing"])
    _dynamic_cfg_with_overrides({
        "normal_staffing_multiplier": 1.20,
        "handover_staffing_multiplier": 0.96,
        "weekend_staffing_multiplier": 1.08,
    })
    after = cfg.raw()["dynamic_model"]["staffing"]
    assert before == after
