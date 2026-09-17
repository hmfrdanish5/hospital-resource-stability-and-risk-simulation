"""
Hospital Resource Stability Lab — Flask Dashboard
Academic interface for Banker's Algorithm safety analysis,
Monte Carlo collapse estimation, and sensitivity analysis.
"""

from __future__ import annotations

import json
import logging
import os
import random
import sys
import time

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

BANKERS_PATH = os.path.join(os.path.dirname(__file__), "..", "pandemic_bankers")
sys.path.insert(0, os.path.abspath(BANKERS_PATH))

from analytics.phase3_experiment import run_abc_experiment, run_parameter_sensitivity  # noqa: E402
from analytics.sensitivity import run_sensitivity_analysis  # noqa: E402
from core.bankers_engine import BankersEngine  # noqa: E402
from data.calibration import calibrate  # noqa: E402
from data.external_fetcher import apply_workload_factor, fetch_external_signal  # noqa: E402
from data.pipeline import load_source_catalog, read_cache  # noqa: E402
from simulation.domain import HospitalSystem  # noqa: E402
from simulation.dynamic_hospital import run_dynamic_simulation  # noqa: E402
from simulation.time_model import apply_staffing_overrides, merge_dynamic_config  # noqa: E402
from simulation.monte_carlo import iter_monte_carlo_sweep, monte_carlo_sweep  # noqa: E402
from simulation.mc_experiment import (  # noqa: E402
    MODEL_LABELS,
    demand_fn_for_experiment,
    progress_batch_size,
    validate_experiment_params,
)
from simulation.mc_export import (  # noqa: E402
    build_export_payload,
    export_csv_text,
    export_json_text,
    parse_export_request,
)
from utils.config_loader import ConfigLoader, ConfigError  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(BANKERS_PATH, "hospital_config.json")

app = Flask(__name__)


def flask_debug_enabled() -> bool:
    """Debug is OFF by default; set FLASK_DEBUG=1 for local development only."""
    return os.environ.get("FLASK_DEBUG", "0") == "1"


def _error(message: str, details: str | None = None, status: int = 400) -> tuple:
    body: dict = {"error": message}
    if details:
        body["details"] = details
    return jsonify(body), status


def _load_config() -> ConfigLoader:
    return ConfigLoader(CONFIG_PATH)


def _parse_json() -> dict:
    if not request.is_json:
        raise ValueError("Request body must be JSON (Content-Type: application/json).")
    data = request.get_json(silent=True)
    if data is None:
        raise ValueError("Request body is empty or malformed JSON.")
    if not isinstance(data, dict):
        raise ValueError("Request body must be a JSON object.")
    return data


def _parse_resources(data: dict, cfg: ConfigLoader) -> list[int]:
    defaults = cfg.resource_totals(cfg.simulation_mode)
    names = cfg.resource_names
    key_map = {
        "icu_beds": "ICU_Beds",
        "oxygen_units": "Oxygen_Units",
        "ventilators": "Ventilators",
        "nurses": "Nurses",
        "blood_units": "Blood_Units",
    }
    resources = []
    for req_key, res_name in key_map.items():
        idx = names.index(res_name)
        if req_key in data:
            val = int(data[req_key])
            if val < 0:
                raise ValueError(f"{req_key} must be non-negative")
            if val == 0:
                raise ValueError(f"{req_key} must be at least 1")
        else:
            val = defaults[idx]
        resources.append(val)
    return resources


def _parse_severity(data: dict, cfg: ConfigLoader) -> dict[str, float]:
    raw = data.get("severity_distribution")
    if raw is None:
        return cfg.severity_distribution(cfg.severity_mode)
    total = sum(float(v) for v in raw.values())
    if total <= 0:
        raise ValueError("Severity distribution must sum to > 0")
    return {k: float(v) / total for k, v in raw.items()}


@app.route("/")
def index():
    return render_template("index.html", active_page="simulator")


@app.route("/mathematics")
def mathematics():
    return render_template("mathematics.html", active_page="mathematics")


@app.route("/api/config", methods=["GET"])
def get_config():
    try:
        cfg = _load_config()
        return jsonify({
            "model_name": cfg.hospital_name,
            "resource_names": cfg.resource_names,
            "simulation_mode": cfg.simulation_mode,
            "severity_mode": cfg.severity_mode,
            "resources": dict(zip(cfg.resource_names, cfg.resource_totals(cfg.simulation_mode))),
            "severity_distribution": cfg.severity_distribution(cfg.severity_mode),
            "max_patients": cfg.max_patients,
            "random_seed": cfg.random_seed,
            "total_beds": cfg.total_beds,
        })
    except ConfigError as exc:
        return _error("Configuration error", str(exc))


@app.route("/api/external-data", methods=["GET"])
def external_data():
    """Return external epidemiological demand signal (cached by default; ?live=1 for live fetch)."""
    prefer_live = request.args.get("live", "0") == "1"
    signal = fetch_external_signal(prefer_live=prefer_live)
    return jsonify(signal)


@app.route("/run_simulation", methods=["POST"])
def run_simulation():
    try:
        cfg = _load_config()
    except ConfigError as exc:
        return _error("Configuration error", str(exc))

    try:
        data = _parse_json()
        resources = _parse_resources(data, cfg)
        severity_dist = _parse_severity(data, cfg)
        max_patients = min(200, max(5, int(data.get("max_patients", cfg.max_patients))))
        trials_per_n = min(200, max(5, int(data.get("trials_per_n", 20))))
        base_seed = int(data.get("seed", cfg.random_seed))
        external_signal = None
        if data.get("use_external_signal"):
            prefer_live = bool(data.get("live_external") or data.get("prefer_live_external"))
            external_signal = fetch_external_signal(prefer_live=prefer_live)
            max_patients = apply_workload_factor(max_patients, external_signal["workload_factor"])
    except (TypeError, ValueError) as exc:
        return _error("Invalid input", str(exc))

    result = monte_carlo_sweep(
        total_resources=resources,
        resource_names=cfg.resource_names,
        severity_dist=severity_dist,
        demand_profiles=cfg.raw()["demand_profiles"],
        max_patients=max_patients,
        trials_per_n=trials_per_n,
        base_seed=base_seed,
    )

    if data.get("use_external_signal") and external_signal is not None:
        result["external_signal"] = external_signal

    return jsonify(result)


def _mc_experiment_provenance() -> dict:
    cached = read_cache("calibration.json") or {}
    prov = cached.get("series_provenance") or {}
    return {
        "data_source": prov.get("source_id") or "unspecified",
        "availability_status": prov.get("availability_status") or "unknown",
        "classification": prov.get("classification"),
        "calibrated_at": cached.get("calibrated_at"),
        "note": (
            "Static Monte Carlo uses demand generators A/B/C. Arrival/LOS calibration "
            "does not enter p_hat or n50. Provenance is session metadata only."
        ),
    }


def _parse_mc_experiment_body(cfg: ConfigLoader) -> dict:
    data = _parse_json()
    resources = _parse_resources(data, cfg)
    severity_dist = _parse_severity(data, cfg)
    min_patients = int(data.get("min_patients", 1))
    max_patients = int(data.get("max_patients", cfg.max_patients))
    trials_per_n = int(data.get("trials_per_n", 20))
    base_seed = int(data.get("seed", cfg.random_seed))
    model = str(data.get("model", "A")).strip().upper()
    p_icu = float(data.get("p_icu_severe", 0.35))
    if p_icu < 0 or p_icu > 1:
        raise ValueError("p_icu_severe must be between 0 and 1.")
    validate_experiment_params(min_patients, max_patients, trials_per_n, model, base_seed)
    return {
        "resources": resources,
        "severity_dist": severity_dist,
        "min_patients": min_patients,
        "max_patients": max_patients,
        "trials_per_n": trials_per_n,
        "base_seed": base_seed,
        "model": model,
        "p_icu_severe": p_icu,
        "demand_profiles": cfg.raw()["demand_profiles"],
        "resource_names": cfg.resource_names,
    }


@app.route("/api/mc_experiment/stream", methods=["POST"])
def mc_experiment_stream():
    try:
        cfg = _load_config()
    except ConfigError as exc:
        return _error("Configuration error", str(exc))
    try:
        spec = _parse_mc_experiment_body(cfg)
    except (TypeError, ValueError) as exc:
        return _error("Invalid input", str(exc))

    demand_fn = demand_fn_for_experiment(
        spec["model"], spec["demand_profiles"], spec["p_icu_severe"]
    )
    provenance = _mc_experiment_provenance()
    every = progress_batch_size(spec["trials_per_n"])
    experiment_meta = {
        "model": spec["model"],
        "model_label": MODEL_LABELS[spec["model"]],
        "seed": spec["base_seed"],
        "trials_per_load": spec["trials_per_n"],
        "patient_range": {"min": spec["min_patients"], "max": spec["max_patients"]},
        "resource_capacities": dict(zip(spec["resource_names"], spec["resources"])),
        "resource_names": spec["resource_names"],
        "severity_distribution": spec["severity_dist"],
        "p_icu_severe": spec["p_icu_severe"],
        "seed_policy": "trial t at load n uses Random(base_seed + n * 1000 + t)",
        "probability_estimator": "p_hat = K_n / T (collapse = admission failure or unsafe)",
        "ci_method": "Wilson score interval",
        "ci_z": 1.96,
        "ci_level": 0.95,
    }

    def generate():
        try:
            start = {
                "event": "started",
                "experiment": experiment_meta,
                "provenance": provenance,
                "progress_every": every,
            }
            yield f"data: {json.dumps(start)}\n\n"
            for event in iter_monte_carlo_sweep(
                total_resources=spec["resources"],
                resource_names=spec["resource_names"],
                severity_dist=spec["severity_dist"],
                demand_profiles=spec["demand_profiles"],
                max_patients=spec["max_patients"],
                trials_per_n=spec["trials_per_n"],
                base_seed=spec["base_seed"],
                min_patients=spec["min_patients"],
                demand_fn=demand_fn,
                progress_every=every,
            ):
                if event["event"] == "complete":
                    result = event["result"]
                    n50 = result["risk_summary"].get("n50")
                    payload = build_export_payload(
                        experiment_meta,
                        provenance,
                        result["probability_curve"],
                        n50,
                        spec["base_seed"],
                        spec["model"],
                        provenance.get("data_source") or "unspecified",
                    )
                    payload["risk_summary"] = {
                        "n50": n50,
                        "threshold_10pct": result["risk_summary"].get("threshold_10pct"),
                        "threshold_70pct": result["risk_summary"].get("threshold_70pct"),
                        "n50_definition": result["risk_summary"].get("n50_definition"),
                    }
                    payload["ci_method"] = result.get("ci_method")
                    payload["event"] = "complete"
                    yield f"data: {json.dumps(payload)}\n\n"
                else:
                    yield f"data: {json.dumps(event)}\n\n"
        except Exception:
            logger.exception("Monte Carlo experiment failed")
            yield f"data: {json.dumps({'event': 'error', 'error': 'Simulation failed.'})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/api/mc_experiment/export.csv", methods=["POST"])
def mc_experiment_export_csv():
    try:
        payload = parse_export_request(_parse_json())
    except (TypeError, ValueError) as exc:
        return _error("Invalid input", str(exc))
    text = export_csv_text(payload)
    return Response(
        text,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=mc_experiment.csv"},
    )


@app.route("/api/mc_experiment/export.json", methods=["POST"])
def mc_experiment_export_json():
    try:
        payload = parse_export_request(_parse_json())
    except (TypeError, ValueError) as exc:
        return _error("Invalid input", str(exc))
    text = export_json_text(payload)
    return Response(
        text,
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=mc_experiment.json"},
    )


@app.route("/api/sensitivity", methods=["POST"])
def sensitivity():
    try:
        cfg = _load_config()
    except ConfigError as exc:
        return _error("Configuration error", str(exc))

    try:
        data = _parse_json()
        resources = _parse_resources(data, cfg)
        severity_dist = _parse_severity(data, cfg)
        max_patients = min(80, max(5, int(data.get("max_patients", 40))))
        trials_per_n = min(100, max(5, int(data.get("trials_per_n", 25))))
        base_seed = int(data.get("seed", cfg.random_seed))
    except (TypeError, ValueError) as exc:
        return _error("Invalid input", str(exc))

    result = run_sensitivity_analysis(
        base_resources=resources,
        resource_names=cfg.resource_names,
        severity_dist=severity_dist,
        demand_profiles=cfg.raw()["demand_profiles"],
        max_patients=max_patients,
        trials_per_n=trials_per_n,
        base_seed=base_seed,
    )
    return jsonify(result)


@app.route("/bankers_demo", methods=["POST"])
def bankers_demo():
    try:
        cfg = _load_config()
    except ConfigError as exc:
        return _error("Configuration error", str(exc))

    try:
        data = _parse_json()
        n_patients = int(data.get("patients", 10))
        seed = int(data.get("seed", cfg.random_seed))
        has_resource_overrides = any(
            k in data for k in ("icu_beds", "oxygen_units", "ventilators", "nurses", "blood_units")
        )
        resources = (
            _parse_resources(data, cfg)
            if has_resource_overrides
            else cfg.resource_totals(cfg.simulation_mode)
        )
        severity_dist = _parse_severity(data, cfg)
    except (TypeError, ValueError) as exc:
        return _error("Invalid input", str(exc))

    if n_patients < 1:
        return _error("Invalid patient count", "'patients' must be >= 1")
    if n_patients > 200:
        return _error("Invalid patient count", "'patients' must be <= 200")

    engine = BankersEngine(total_resources=resources, resource_names=cfg.resource_names)
    rng = random.Random(seed)
    hospital = HospitalSystem(cfg, engine, rng, severity_dist=severity_dist)
    admitted = hospital.admit_n_patients(n_patients)

    try:
        engine.validate_invariants()
    except ValueError as exc:
        logger.error("Invariant violation: %s", exc)
        return _error("Internal state error", str(exc), status=500)

    safe, safe_sequence, blocking, steps, post_mortem = engine.is_safe_with_trace()
    snap = engine.snapshot()

    return jsonify({
        "safe": safe,
        "safe_sequence": safe_sequence,
        "blocking_resource": blocking,
        "post_mortem": post_mortem,
        "patients_requested": n_patients,
        "patients_admitted": len(admitted),
        "total": snap["total"],
        "available": snap["available"],
        "resource_names": snap["resource_names"],
        "allocation": snap["allocation"],
        "max_demand": snap["max_demand"],
        "need": snap["need"],
        "steps": steps,
        "severity_breakdown": hospital.severity_breakdown(),
    })


@app.route("/api/dynamic_simulation", methods=["POST"])
def dynamic_simulation():
    """Phase 2 time-dependent hospital run. Does not replace Banker's SAFE/UNSAFE."""
    try:
        cfg = _load_config()
    except ConfigError as exc:
        return _error("Configuration error", str(exc))

    try:
        data = _parse_json()
        resources = _parse_resources(data, cfg)
        severity_dist = _parse_severity(data, cfg)
        horizon = min(168, max(8, int(data.get("horizon_hours", 48))))
        arrivals = min(10, max(0, int(data.get("arrivals_per_step", 2))))
        seed = int(data.get("seed", cfg.random_seed))
        dynamic_cfg = merge_dynamic_config(cfg.dynamic_model())
        dynamic_cfg["staffing"] = apply_staffing_overrides(dynamic_cfg["staffing"], data)
    except (TypeError, ValueError) as exc:
        return _error("Invalid input", str(exc))

    result = run_dynamic_simulation(
        base_capacity=resources,
        resource_names=cfg.resource_names,
        dynamic_cfg=dynamic_cfg,
        severity_dist=severity_dist,
        demand_profiles=cfg.raw()["demand_profiles"],
        seed=seed,
        horizon_hours=horizon,
        arrivals_per_step=arrivals,
    )
    # Keep the response bounded for the dashboard; full conservation checks stay in tests.
    history = result.get("history") or []
    result["history"] = history[-24:]
    result["history_truncated"] = len(history) > 24
    result["patients"] = result.get("patients", [])[-40:]
    return jsonify(result)


@app.route("/api/data-sources", methods=["GET"])
def data_sources():
    return jsonify(load_source_catalog())


@app.route("/api/calibration", methods=["GET"])
def get_calibration():
    prefer_live = request.args.get("live", "0") == "1"
    result = calibrate(prefer_live=prefer_live)
    return jsonify(result)


@app.route("/api/phase3_experiment", methods=["POST"])
def phase3_experiment():
    try:
        cfg = _load_config()
    except ConfigError as exc:
        return _error("Configuration error", str(exc))
    try:
        data = _parse_json()
        resources = _parse_resources(data, cfg)
        severity_dist = _parse_severity(data, cfg)
        max_patients = min(24, max(6, int(data.get("max_patients", 16))))
        trials_per_n = min(20, max(5, int(data.get("trials_per_n", 8))))
        horizon = min(48, max(8, int(data.get("horizon_hours", 16))))
        seed = int(data.get("seed", cfg.random_seed))
        include_sensitivity = bool(data.get("include_sensitivity", False))
    except (TypeError, ValueError) as exc:
        return _error("Invalid input", str(exc))

    abc = run_abc_experiment(
        base_capacity=resources,
        resource_names=cfg.resource_names,
        severity_dist=severity_dist,
        demand_profiles=cfg.raw()["demand_profiles"],
        dynamic_cfg=cfg.dynamic_model(),
        max_patients=max_patients,
        trials_per_n=trials_per_n,
        horizon_hours=horizon,
        base_seed=seed,
        prefer_live=False,
        include_empirical_sensitivity=True,
    )
    # Bound curve size for the dashboard
    for mode in abc.get("models", {}):
        curve = abc["models"][mode].get("probability_curve") or []
        abc["models"][mode]["probability_curve"] = curve
    if include_sensitivity:
        abc["parameter_sensitivity"] = run_parameter_sensitivity(
            base_capacity=resources,
            resource_names=cfg.resource_names,
            severity_dist=severity_dist,
            demand_profiles=cfg.raw()["demand_profiles"],
            dynamic_cfg=cfg.dynamic_model(),
            max_patients=max_patients,
            trials_per_n=max(5, trials_per_n // 2),
            base_seed=seed,
            prefer_live=False,
        )
    return jsonify(abc)


if __name__ == "__main__":
    debug = flask_debug_enabled()
    print("\n  Hospital Resource Stability Lab")
    print("  -------------------------------")
    print("  Open: http://127.0.0.1:5000")
    if debug:
        print("  FLASK_DEBUG=1 — development mode (do not use in public hosting)\n")
    else:
        print("  Debug OFF (set FLASK_DEBUG=1 for local debugger)\n")
    app.run(host="127.0.0.1", port=5000, debug=debug)
