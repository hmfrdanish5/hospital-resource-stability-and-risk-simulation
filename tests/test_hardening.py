"""Pre-hosting hardening: security, debug defaults, concurrency."""

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pandemic_bankers"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.distributions import fit_los_from_quantiles, quantile_sse
from data.pipeline import load_literature_los


def test_flask_debug_disabled_by_default():
    from pandemic_dashboard.app import flask_debug_enabled

    old = os.environ.get("FLASK_DEBUG")
    try:
        os.environ.pop("FLASK_DEBUG", None)
        assert flask_debug_enabled() is False
        os.environ["FLASK_DEBUG"] = "1"
        assert flask_debug_enabled() is True
    finally:
        if old is None:
            os.environ.pop("FLASK_DEBUG", None)
        else:
            os.environ["FLASK_DEBUG"] = old


def test_los_reconstruction_sse_is_computed_not_zero_claim():
    lit = load_literature_los()
    ward = lit["hospital_los_days"]
    fit = fit_los_from_quantiles(ward["q25"], ward["median"], ward["q75"])
    obs = {"q25": ward["q25"], "median": ward["median"], "q75": ward["q75"]}
    pred = fit["chosen"]["predicted"]
    sse = quantile_sse(pred, obs)
    assert fit["chosen"]["sse"] == sse
    assert sse >= 0.0
    if sse > 0:
        assert sse > 1e-12


def test_mc_stream_concurrency_isolated():
    from pandemic_dashboard.app import app
    from simulation.monte_carlo import monte_carlo_sweep

    demand = {
        "Mild": {"min": [0, 1, 0, 0, 0], "max": [0, 3, 0, 1, 1]},
        "Moderate": {"min": [0, 3, 0, 1, 1], "max": [0, 6, 0, 2, 2]},
        "Severe": {"min": [0, 6, 0, 2, 2], "max": [1, 12, 1, 3, 4]},
        "Critical": {"min": [1, 10, 1, 3, 3], "max": [1, 20, 1, 5, 6]},
    }
    sweep_kwargs = {
        "total_resources": [14, 90, 14, 35, 120],
        "resource_names": ["ICU_Beds", "Oxygen_Units", "Ventilators", "Nurses", "Blood_Units"],
        "severity_dist": {"Mild": 0.6, "Moderate": 0.15, "Severe": 0.15, "Critical": 0.10},
        "demand_profiles": demand,
        "max_patients": 4,
        "trials_per_n": 6,
        "min_patients": 2,
    }
    payload = {
        "min_patients": 2,
        "max_patients": 4,
        "trials_per_n": 6,
        "model": "A",
        "icu_beds": 14,
        "oxygen_units": 90,
        "ventilators": 14,
        "nurses": 35,
        "blood_units": 120,
    }
    expected_1 = monte_carlo_sweep(**sweep_kwargs, base_seed=1)
    expected_99 = monte_carlo_sweep(**sweep_kwargs, base_seed=99)
    assert expected_1["probability_curve"] != expected_99["probability_curve"]

    def _run(seed: int) -> dict:
        client = app.test_client()
        body = dict(payload, seed=seed)
        resp = client.post("/api/mc_experiment/stream", json=body)
        assert resp.status_code == 200
        complete = None
        for block in resp.get_data(as_text=True).split("\n\n"):
            if '"event": "complete"' in block:
                line = [ln for ln in block.split("\n") if ln.startswith("data: ")][0]
                complete = json.loads(line[6:])
        assert complete is not None
        return complete

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(_run, 1).result()
        b = pool.submit(_run, 99).result()

    assert a["experiment"]["seed"] == 1
    assert b["experiment"]["seed"] == 99
    for row, exp in zip(a["results"], expected_1["probability_curve"]):
        assert row["collapse_probability"] == exp["p_collapse"]
    for row, exp in zip(b["results"], expected_99["probability_curve"]):
        assert row["collapse_probability"] == exp["p_collapse"]


def test_smoke_routes_return_controlled_status():
    from pandemic_dashboard.app import app

    client = app.test_client()
    assert client.get("/").status_code == 200
    assert client.get("/mathematics").status_code == 200
    assert client.get("/api/config").status_code == 200
    assert client.post("/run_simulation", json={"trials_per_n": 5, "max_patients": 5}).status_code == 200
    assert client.post("/bankers_demo", json={}).status_code == 200
    assert client.post("/api/dynamic_simulation", json={"horizon_hours": 8}).status_code == 200
    assert client.post("/api/sensitivity", json={"trials_per_n": 5, "max_patients": 5}).status_code == 200
    assert client.get("/api/calibration").status_code == 200
    assert client.post("/api/phase3_experiment", json={"trials_per_n": 5, "max_patients": 6}).status_code == 200


def test_time_model_phase3_and_randomize_are_wired():
    root = os.path.join(os.path.dirname(__file__), "..", "pandemic_dashboard")
    with open(os.path.join(root, "static", "script.js"), encoding="utf-8") as fh:
        js = fh.read()
    with open(os.path.join(root, "templates", "index.html"), encoding="utf-8") as fh:
        html = fh.read()
    assert 'getElementById("btnDynamic")' in js
    assert "runDynamic" in js
    assert 'getElementById("btnPhase3")' in js
    assert "runPhase3" in js
    assert 'getElementById("btnRandomize")' in js
    assert "fillRandomInputs" in js
    assert "btnDynamic" in html
    assert "btnPhase3" in html
    assert "btnRandomize" in html
    assert "sim-tab" in html
    assert "switchTab" in js
    assert "autoRefresh" not in html
    assert "Live chart" not in html
    assert "section-comments" not in html
    assert "btnToggleFeedback" not in html
    assert "export.js" in html
    assert "data-export-kind" in html
    assert "HSLabExport" in js
