"""
Phase 3 principal experiment: Model A vs B vs C, plus parameter sensitivity.

Does not modify Banker's safety algorithm. Collapse probabilities use Phase 1
Monte Carlo; overflow uses the Phase 2 time model.
"""

from __future__ import annotations

import random
from typing import Any

from core.bankers_engine import BankersEngine
from data.calibration import calibrate
from data.sampling import (
    demand_fn_for_mode,
    make_arrival_sampler,
    make_los_sampler,
    p_icu_severe_from_occupancy,
)
from simulation.dynamic_hospital import DynamicHospitalSimulator
from simulation.monte_carlo import threshold_at_probability, wilson_ci
from simulation.time_model import merge_dynamic_config


def _trial_with_demand(
    total_resources: list[int],
    resource_names: list[str],
    n_patients: int,
    severity_dist: dict[str, float],
    demand_fn,
    rng: random.Random,
) -> tuple[bool, dict[str, float]]:
    engine = BankersEngine(total_resources, resource_names)
    n_res = len(total_resources)
    tiers = list(severity_dist.keys())
    weights = list(severity_dist.values())
    for i in range(n_patients):
        tier = rng.choices(tiers, weights=weights, k=1)[0]
        allocation, max_demand = demand_fn(tier, n_res, rng)
        try:
            engine.add_patient(f"P{i:04d}", allocation, max_demand)
        except ValueError:
            return True, engine.utilization()
    safe, _, _ = engine.is_safe()
    return (not safe), engine.utilization()


def _sweep_demand(
    total_resources: list[int],
    resource_names: list[str],
    severity_dist: dict[str, float],
    demand_fn,
    max_patients: int,
    trials_per_n: int,
    base_seed: int,
) -> dict:
    curve = []
    for n in range(1, max_patients + 1):
        collapse = 0
        util_acc = {name: 0.0 for name in resource_names}
        for t in range(trials_per_n):
            rng = random.Random(base_seed + n * 1000 + t)
            collapsed, util = _trial_with_demand(
                total_resources, resource_names, n, severity_dist, demand_fn, rng
            )
            if collapsed:
                collapse += 1
            for name in resource_names:
                util_acc[name] += util.get(name, 0.0)
        p, lo, hi = wilson_ci(collapse, trials_per_n)
        curve.append({
            "n": n,
            "p_collapse": p,
            "ci_lo": lo,
            "ci_hi": hi,
            "utilization": {k: v / trials_per_n for k, v in util_acc.items()},
        })
    n50 = threshold_at_probability(curve, "p_collapse", 0.50)
    peak_util = {}
    if curve:
        peak_util = curve[-1]["utilization"]
        if n50 is not None:
            peak_util = curve[n50 - 1]["utilization"]
    return {
        "probability_curve": curve,
        "n50": n50,
        "peak_utilization": peak_util,
        "trials_per_n": trials_per_n,
        "ci_method": "Wilson score interval (simulation uncertainty under a fixed model)",
    }


def _overflow_stats(
    base_capacity: list[int],
    resource_names: list[str],
    dynamic_cfg: dict,
    severity_dist: dict,
    demand_profiles: dict,
    seed: int,
    horizon: int,
    arrival_sampler,
    los_sampler,
) -> dict:
    cfg = merge_dynamic_config(dynamic_cfg)
    cfg["arrivals_per_step"] = 0
    sim = DynamicHospitalSimulator(
        base_capacity=base_capacity,
        resource_names=resource_names,
        dynamic_cfg=cfg,
        severity_dist=severity_dist,
        demand_profiles=demand_profiles,
        rng=random.Random(seed),
        arrival_sampler=arrival_sampler,
        los_sampler=los_sampler,
    )
    result = sim.run(horizon_hours=horizon)
    return result["secondary_metrics"]


def _scale_critical(dist: dict, new_crit: float, mu, p_icu):
    new_crit = min(0.5, max(0.01, new_crit))
    rest = {k: v for k, v in dist.items() if k != "Critical"}
    s = sum(rest.values()) or 1.0
    scaled = {k: v / s * (1 - new_crit) for k, v in rest.items()}
    scaled["Critical"] = new_crit
    return ("sev", mu, p_icu, scaled)


def run_abc_experiment(
    base_capacity: list[int],
    resource_names: list[str],
    severity_dist: dict[str, float],
    demand_profiles: dict,
    dynamic_cfg: dict | None,
    max_patients: int = 20,
    trials_per_n: int = 12,
    horizon_hours: int = 24,
    base_seed: int = 42,
    prefer_live: bool = False,
    mu_hourly: float | None = None,
    include_empirical_sensitivity: bool = True,
) -> dict[str, Any]:
    calibration = calibrate(prefer_live=prefer_live, rng=random.Random(base_seed))
    p_occ = calibration["parameters"]["p_icu_given_hospital_occupancy"]["value"]
    mapping = p_icu_severe_from_occupancy(p_occ, severity_dist)
    p_icu_severe = mapping["p_icu_severe"]
    cfg = merge_dynamic_config(dynamic_cfg)
    mu = float(mu_hourly if mu_hourly is not None else cfg["arrivals_per_step"])
    weekday_rel = (
        (calibration.get("parameters") or {})
        .get("weekday_relative_rates", {})
        .get("value", {})
        .get("relative_rates")
    )

    models = {}
    for mode in ("A", "B", "C"):
        demand_fn = demand_fn_for_mode(mode, demand_profiles, p_icu_severe)
        sweep = _sweep_demand(
            base_capacity, resource_names, severity_dist, demand_fn,
            max_patients, trials_per_n, base_seed + (ord(mode) * 17),
        )
        overflow = _overflow_stats(
            base_capacity, resource_names, cfg, severity_dist, demand_profiles,
            seed=base_seed + 99 + ord(mode),
            horizon=horizon_hours,
            arrival_sampler=make_arrival_sampler(
                calibration, mu, mode,
                weekday_relative=weekday_rel if mode == "C" else None,
            ),
            los_sampler=make_los_sampler(calibration, mode, cfg["los_hours"]),
        )
        models[mode] = {
            "label": {
                "A": "MODEL A — Independent Synthetic Demand",
                "B": "MODEL B — Severity-Conditioned Demand",
                "C": "MODEL C — Empirically Informed Dynamic Model",
            }[mode],
            "description": {
                "A": (
                    "Independent synthetic demand given severity (Phase 1 generator). "
                    "No empirical dependence structure. Static collapse sweep only for n50. "
                    "Dynamic: configured arrivals and uniform LOS."
                ),
                "B": (
                    "Severity-conditioned joint ICU/ventilator demand (static collapse sweep). "
                    "Occupancy mapping may inform P(ICU|Severe); that is not complete empirical "
                    "calibration of individual hospital census. Dynamic overflow uses the same "
                    "arrivals/LOS as A, not this joint demand."
                ),
                "C": (
                    "Static Banker's n-sweep uses the same demand generator as B "
                    "(not a fully calibrated collapse model). Calibrated arrival family, "
                    "weekday λ(t)=λ_0 r_dow(t), and quantile-reconstructed LOS apply only "
                    "to the dynamic overflow experiment. Simulation-based; not actual "
                    "individual-hospital census."
                ),
            }[mode],
            "n50": sweep["n50"],
            "n50_experiment": "static_banker_collapse",
            "p_collapse_at_max_n": sweep["probability_curve"][-1]["p_collapse"] if sweep["probability_curve"] else None,
            "peak_utilization": sweep["peak_utilization"],
            "overflow": {
                "mean_overflow_duration": overflow["mean_overflow_duration"],
                "maximum_overflow_duration": overflow["maximum_overflow_duration"],
                "fraction_overflowed": overflow["fraction_of_patients_experiencing_overflow"],
                "overflow_event_rate": overflow["overflow_event_rate"],
                "fatigue_duration": overflow.get("fatigue_duration"),
                "fatigue_events": overflow.get("fatigue_events"),
            },
            "dynamic_metrics_note": (
                "Overflow, duration, and related rates are from the time model. "
                "They are not Banker's UNSAFE and are not n50."
            ),
            "probability_curve": sweep["probability_curve"],
        }

    availability = (calibration.get("series_provenance") or {}).get(
        "availability_status"
    )
    empirical_sens = None
    if include_empirical_sensitivity:
        empirical_sens = run_empirical_assumption_sensitivity(
            base_capacity, resource_names, severity_dist, demand_profiles, cfg,
            calibration=calibration, mu_hourly=mu, horizon_hours=horizon_hours,
            base_seed=base_seed + 800, weekday_relative=weekday_rel,
        )

    return {
        "phase": 3,
        "calibration": calibration,
        "p_icu_severe_mapping": mapping,
        "copula_used": False,
        "copula": calibration["dependence"]["copula"],
        "models": models,
        "experiment_families": {
            "static_banker_collapse": {
                "id": "A",
                "title": "Static Banker collapse analysis",
                "metrics": ["p_hat(n)", "Wilson CI", "n50", "isolated elasticity (separate experiment)"],
                "note": (
                    "Calibrated arrival/LOS do not enter this family. "
                    "Do not label the static n-sweep as a fully calibrated collapse model."
                ),
            },
            "dynamic_empirically_informed": {
                "id": "B",
                "title": "Dynamic empirically informed simulation",
                "metrics": [
                    "overflow probability/rate",
                    "mean overflow duration",
                    "fatigue exposure (Phase 2)",
                    "LOS samples",
                    "resource utilization in the time model",
                ],
                "note": (
                    "Model C uses calibrated arrival family and quantile LOS. "
                    "Does not represent actual individual-hospital census."
                ),
            },
        },
        "comparison_notes": {
            "collapse": (
                "Static Banker's/admission-failure Monte Carlo at fixed n. "
                "Wilson CI is simulation uncertainty. Arrival rate and LOS are unused here. "
                "Observed differences among A/B/C n50 are simulation differences, not "
                "statistically tested real-world effects."
            ),
            "overflow": (
                "Phase 2 time model. Overflow is not Banker's UNSAFE. "
                "Calibrated arrivals/LOS affect Model C overflow only."
            ),
            "independent_vs_dependent": (
                "A vs B isolates joint ICU/vent sampling in the static collapse sweep. "
                "C vs B isolates calibrated arrivals/LOS in the dynamic overflow run."
            ),
        },
        "experiment_scope": {
            "static_banker_collapse": {
                "A": "independent demand",
                "B": "severity-conditioned joint ICU/vent demand",
                "C": "same demand as B (not a separately calibrated static collapse)",
            },
            "dynamic_overflow": {
                "A": "configured arrivals; uniform LOS; bundle admission",
                "B": "same dynamic inputs as A",
                "C": "calibrated arrival family + weekday λ(t) + quantile-reconstructed LOS; bundle admission",
            },
            "external_data": (
                "LOS quantiles from Rees et al. 2020 (published summaries; quantile calibration). "
                "Arrival family/size and weekday relatives from ingested series "
                f"({availability or 'unknown availability'}). "
                "Hospital λ_0 remains a model assumption."
            ),
        },
        "empirical_assumption_sensitivity": empirical_sens,
        "reproducibility": {
            "random_seed": base_seed,
            "trial_count": trials_per_n,
            "horizon_hours": horizon_hours,
            "max_patients": max_patients,
            "prefer_live": prefer_live,
            "data_source": (calibration.get("series_provenance") or {}).get("source_id"),
            "availability_status": availability,
            "calibration_timestamp": calibration.get("calibrated_at"),
            "mu_hourly_model_assumption": mu,
        },
    }


def run_parameter_sensitivity(
    base_capacity: list[int],
    resource_names: list[str],
    severity_dist: dict[str, float],
    demand_profiles: dict,
    dynamic_cfg: dict | None,
    max_patients: int = 16,
    trials_per_n: int = 8,
    base_seed: int = 42,
    prefer_live: bool = False,
) -> dict[str, Any]:
    experiment = run_abc_experiment(
        base_capacity, resource_names, severity_dist, demand_profiles, dynamic_cfg,
        max_patients=max_patients, trials_per_n=trials_per_n,
        horizon_hours=16, base_seed=base_seed, prefer_live=prefer_live,
    )
    baseline_n50 = experiment["models"]["C"]["n50"]
    calibration = experiment["calibration"]
    cfg = merge_dynamic_config(dynamic_cfg)
    mu0 = float(cfg["arrivals_per_step"])
    p_icu0 = experiment["p_icu_severe_mapping"]["p_icu_severe"]
    crit0 = float(severity_dist.get("Critical", 0.1))
    perturbations = (-0.20, -0.10, -0.05, 0.05, 0.10, 0.20)

    def _n50_for(p_icu, sev):
        demand_fn = demand_fn_for_mode("C", demand_profiles, p_icu)
        sweep = _sweep_demand(
            base_capacity, resource_names, sev, demand_fn,
            max_patients, trials_per_n, base_seed + 500,
        )
        return sweep["n50"], sweep["probability_curve"][-1]["p_collapse"]

    makers = {
        "p_icu_severe": lambda f: (min(1.0, max(0.0, p_icu0 * (1 + f))), dict(severity_dist)),
        "critical_share": lambda f: (
            p_icu0,
            _scale_critical(severity_dist, crit0 * (1 + f), mu0, p_icu0)[3],
        ),
    }

    rows = []
    for name, maker in makers.items():
        for frac in perturbations:
            p_icu, sev = maker(frac)
            n50, pmax = _n50_for(p_icu, sev)
            delta = None if n50 is None or baseline_n50 is None else n50 - baseline_n50
            rows.append({
                "parameter": name,
                "perturbation": frac,
                "n50": n50,
                "delta_n50": delta,
                "p_collapse_at_max_n": pmax,
            })

    impact_n50: dict[str, list[float]] = {}
    impact_p: dict[str, list[float]] = {}
    p0 = experiment["models"]["C"]["p_collapse_at_max_n"] or 0.0
    for row in rows:
        if row["delta_n50"] is not None:
            impact_n50.setdefault(row["parameter"], []).append(abs(row["delta_n50"]))
        if row["p_collapse_at_max_n"] is not None:
            impact_p.setdefault(row["parameter"], []).append(abs(row["p_collapse_at_max_n"] - p0))
    ranking_n50 = sorted(
        ((k, sum(v) / len(v)) for k, v in impact_n50.items() if v),
        key=lambda kv: kv[1],
        reverse=True,
    )
    ranking_p = sorted(
        ((k, sum(v) / len(v)) for k, v in impact_p.items() if v),
        key=lambda kv: kv[1],
        reverse=True,
    )
    ranking = ranking_n50 or ranking_p
    return {
        "baseline_n50_model_c": baseline_n50,
        "baseline_p_collapse_at_max_n": p0,
        "baseline_overflow_model_c": experiment["models"]["C"]["overflow"],
        "rows": rows,
        "most_sensitive": ranking[0][0] if ranking else None,
        "sensitivity_ranking": [{"parameter": k, "mean_abs_delta_n50": v} for k, v in ranking_n50],
        "sensitivity_ranking_p_collapse": [
            {"parameter": k, "mean_abs_delta_p_collapse": v} for k, v in ranking_p
        ],
        "metric_used_for_most_sensitive": "mean_abs_delta_n50" if ranking_n50 else "mean_abs_delta_p_collapse",
        "uncertainty_label": (
            "These ranges are parameter-sensitivity results, not sampling CIs and not real-world CIs."
        ),
        "calibration_source": calibration["series_provenance"],
        "does_not_replace": (
            "Isolated one-resource discrete marginal sensitivity ε_k remains the Phase 1 "
            "sensitivity experiment. This parameter sweep is additional, not a replacement. "
            "Arrival-rate perturbations are omitted here because static n50 sweeps do not "
            "use the arrival process; use empirical-assumption sensitivity for λ₀ effects."
        ),
    }


def run_empirical_assumption_sensitivity(
    base_capacity: list[int],
    resource_names: list[str],
    severity_dist: dict[str, float],
    demand_profiles: dict,
    dynamic_cfg: dict | None,
    calibration: dict,
    mu_hourly: float,
    horizon_hours: int,
    base_seed: int,
    weekday_relative: list[float] | None,
    scales: tuple[float, ...] = (0.9, 1.0, 1.1, 1.2),
) -> dict:
    """
    Sensitivity of Model C *dynamic* metrics to empirical/model assumptions.

    Does not replace isolated resource elasticity. n50 is not a target here.
    Results are simulation sensitivity, not confidence statements about hospitals.
    """
    cfg0 = merge_dynamic_config(dynamic_cfg)
    alpha0 = float(cfg0["fatigue"]["delay_factor_alpha"])
    rows = []
    axes = (
        ("arrival_intensity", "arrival_scale"),
        ("los_multiplier", "los_scale"),
        ("fatigue_penalty", "fatigue_scale"),
    )
    seed = base_seed
    for name, key in axes:
        for scale in scales:
            arrival_scale = scale if key == "arrival_scale" else 1.0
            los_scale = scale if key == "los_scale" else 1.0
            fatigue_scale = scale if key == "fatigue_scale" else 1.0
            cfg = merge_dynamic_config(dynamic_cfg)
            cfg["fatigue"]["delay_factor_alpha"] = alpha0 * fatigue_scale
            ov = _overflow_stats(
                base_capacity, resource_names, cfg, severity_dist, demand_profiles,
                seed=seed,
                horizon=horizon_hours,
                arrival_sampler=make_arrival_sampler(
                    calibration, mu_hourly, "C",
                    weekday_relative=weekday_relative,
                    intensity_scale=arrival_scale,
                ),
                los_sampler=make_los_sampler(
                    calibration, "C", cfg["los_hours"], los_scale=los_scale
                ),
            )
            rows.append({
                "parameter": name,
                "scale": scale,
                "n50": None,
                "n50_note": "not applicable (dynamic overflow experiment)",
                "overflow_event_rate": ov["overflow_event_rate"],
                "mean_overflow_duration": ov["mean_overflow_duration"],
                "fraction_overflowed": ov["fraction_of_patients_experiencing_overflow"],
                "fatigue_duration": ov.get("fatigue_duration"),
            })
            seed += 1
    return {
        "kind": "simulation_sensitivity_around_model_assumptions",
        "not_a_confidence_statement": True,
        "not_statistical_significance": True,
        "scales": list(scales),
        "rows": rows,
        "note": (
            "Factors 0.9×–1.2× on hospital λ_0, LOS, and fatigue α. "
            "These are sensitivity analyses around model assumptions, not "
            "confidence statements about real hospitals. Isolated resource "
            "elasticity ε_k is unchanged."
        ),
    }
