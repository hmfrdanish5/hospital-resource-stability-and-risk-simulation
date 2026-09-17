"""Interactive Monte Carlo experiment: streaming, export, reproducibility."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pandemic_bankers"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from simulation.mc_experiment import validate_experiment_params
from simulation.mc_export import (
    build_export_payload,
    export_csv_text,
    export_json_text,
    parse_export_request,
)
from simulation.monte_carlo import iter_monte_carlo_sweep, monte_carlo_sweep, wilson_ci

DEMAND = {
    "Mild": {"min": [0, 1, 0, 0, 0], "max": [0, 3, 0, 1, 1]},
    "Moderate": {"min": [0, 3, 0, 1, 1], "max": [0, 6, 0, 2, 2]},
    "Severe": {"min": [0, 6, 0, 2, 2], "max": [1, 12, 1, 3, 4]},
    "Critical": {"min": [1, 10, 1, 3, 3], "max": [1, 20, 1, 5, 6]},
}
RESOURCES = [14, 90, 14, 35, 120]
NAMES = ["ICU_Beds", "Oxygen_Units", "Ventilators", "Nurses", "Blood_Units"]
SEV = {"Mild": 0.6, "Moderate": 0.15, "Severe": 0.15, "Critical": 0.10}


def _sweep(**kwargs):
    defaults = dict(
        total_resources=RESOURCES,
        resource_names=NAMES,
        severity_dist=SEV,
        demand_profiles=DEMAND,
        max_patients=5,
        trials_per_n=8,
        base_seed=42,
        min_patients=2,
    )
    defaults.update(kwargs)
    return monte_carlo_sweep(**defaults)


def test_progress_reporting_does_not_alter_results():
    a = _sweep(progress_every=0)
    b = _sweep(progress_every=1)
    assert a["probability_curve"] == b["probability_curve"]
    assert a["risk_summary"]["n50"] == b["risk_summary"]["n50"]


def test_reproducibility_identical_seed():
    a = _sweep(base_seed=7)
    b = _sweep(base_seed=7)
    assert a["probability_curve"] == b["probability_curve"]


def test_running_p_hat_matches_backend_wilson():
    last_progress = None
    result = None
    for ev in iter_monte_carlo_sweep(
        RESOURCES, NAMES, SEV, DEMAND,
        max_patients=3, trials_per_n=6, base_seed=1,
        min_patients=3, progress_every=1,
    ):
        if ev["event"] == "progress":
            last_progress = ev
            p, lo, hi = wilson_ci(ev["collapse_trials"], ev["trial"])
            assert ev["p_hat"] == p
            assert ev["wilson_lower"] == lo
            assert ev["wilson_upper"] == hi
        if ev["event"] == "complete":
            result = ev["result"]
    assert last_progress is not None
    assert result is not None
    row = result["probability_curve"][-1]
    p, lo, hi = wilson_ci(row["collapse_trials"], row["trials"])
    assert row["p_collapse"] == p
    assert row["ci_lo"] == lo
    assert row["ci_hi"] == hi


def test_export_csv_json_contains_seed_model_trials_and_probabilities():
    sweep = _sweep(base_seed=11)
    experiment = {
        "model": "A",
        "seed": 11,
        "trials_per_load": 8,
        "patient_range": {"min": 2, "max": 5},
    }
    payload = build_export_payload(
        experiment, {"data_source": "fixture", "availability_status": "SYNTHETIC_FALLBACK"},
        sweep["probability_curve"], sweep["risk_summary"]["n50"], 11, "A", "fixture",
    )
    assert payload["experiment"]["seed"] == 11
    assert payload["experiment"]["model"] == "A"
    assert payload["experiment"]["trials_per_load"] == 8
    assert payload["results"]
    csv_text = export_csv_text(payload)
    json_text = export_json_text(payload)
    assert "patient_count" in csv_text
    assert "collapse_probability" in csv_text
    assert "11" in csv_text
    parsed = json.loads(json_text)
    assert parsed["experiment"]["seed"] == 11
    row0 = sweep["probability_curve"][0]
    exp0 = parsed["results"][0]
    assert exp0["collapse_probability"] == row0["p_collapse"]
    assert exp0["wilson_lower"] == row0["ci_lo"]
    assert exp0["wilson_upper"] == row0["ci_hi"]
    assert parsed["n50"] == sweep["risk_summary"]["n50"]
    assert "ADMIN_TOKEN" not in json_text
    assert "password" not in json_text.lower()


def test_exported_probability_equals_backend():
    sweep = _sweep()
    payload = build_export_payload(
        {"model": "B", "seed": 42, "trials_per_load": 8, "patient_range": {"min": 2, "max": 5}},
        {"data_source": "x"},
        sweep["probability_curve"],
        sweep["risk_summary"]["n50"],
        42, "B", "x",
    )
    for backend, exported in zip(sweep["probability_curve"], payload["results"]):
        assert exported["collapse_probability"] == backend["p_collapse"]
        assert exported["patient_count"] == backend["n"]


def test_n50_in_export_matches_backend():
    sweep = _sweep()
    payload = build_export_payload(
        {"model": "A", "seed": 42, "trials_per_load": 8, "patient_range": {"min": 2, "max": 5}},
        {},
        sweep["probability_curve"],
        sweep["risk_summary"]["n50"],
        42, "A", "x",
    )
    assert payload["n50"] == sweep["risk_summary"]["n50"]


def test_invalid_experiment_params():
    try:
        validate_experiment_params(10, 5, 10, "A", 1)
        assert False
    except ValueError:
        pass
    try:
        validate_experiment_params(1, 5, 0, "A", 1)
        assert False
    except ValueError:
        pass
    try:
        validate_experiment_params(1, 5, 10, "Z", 1)
        assert False
    except ValueError:
        pass


def test_parse_export_rejects_non_object():
    try:
        parse_export_request([])
        assert False
    except ValueError:
        pass


def test_flask_validation_not_500():
    from pandemic_dashboard.app import app
    client = app.test_client()
    resp = client.post(
        "/api/mc_experiment/stream",
        json={"min_patients": 20, "max_patients": 5, "trials_per_n": 8, "model": "A", "seed": 1},
    )
    assert resp.status_code == 400
    resp2 = client.post(
        "/api/mc_experiment/stream",
        json={"min_patients": 1, "max_patients": 3, "trials_per_n": 0, "model": "A", "seed": 1},
    )
    assert resp2.status_code == 400
    resp3 = client.post(
        "/api/mc_experiment/stream",
        json={"min_patients": 1, "max_patients": 3, "trials_per_n": 5, "model": "Q", "seed": 1},
    )
    assert resp3.status_code == 400


def test_flask_stream_and_export_roundtrip():
    from pandemic_dashboard.app import app
    client = app.test_client()
    resp = client.post(
        "/api/mc_experiment/stream",
        json={
            "min_patients": 2,
            "max_patients": 4,
            "trials_per_n": 6,
            "model": "A",
            "seed": 42,
            "icu_beds": 14,
            "oxygen_units": 90,
            "ventilators": 14,
            "nurses": 35,
            "blood_units": 120,
        },
    )
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    complete = None
    for block in text.split("\n\n"):
        if "\"event\": \"complete\"" in block or '"event": "complete"' in block:
            line = [ln for ln in block.split("\n") if ln.startswith("data: ")][0]
            complete = json.loads(line[6:])
    assert complete is not None
    assert complete["experiment"]["seed"] == 42
    csv_resp = client.post("/api/mc_experiment/export.csv", json=complete)
    json_resp = client.post("/api/mc_experiment/export.json", json=complete)
    assert csv_resp.status_code == 200
    assert json_resp.status_code == 200
    assert b"collapse_probability" in csv_resp.data
    body = json_resp.get_json()
    assert body["experiment"]["seed"] == 42
    assert body["n50"] == complete["n50"]
    sweep = _sweep(min_patients=2, max_patients=4, trials_per_n=6, base_seed=42)
    assert complete["n50"] == sweep["risk_summary"]["n50"]
    for a, b in zip(complete["results"], sweep["probability_curve"]):
        assert a["collapse_probability"] == b["p_collapse"]
        assert a["wilson_lower"] == b["ci_lo"]
