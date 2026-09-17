"""
Monte Carlo collapse-probability analysis.

Failure modes per trial:
  1. Admission failure: initial allocation exceeds Available.
  2. Unsafe state: all n admitted but Banker's algorithm reports UNSAFE.

Collapse = admission failure OR unsafe state.
P(unsafe) is estimated separately as unsafe_trials / T.
Wilson score 95% confidence intervals (z = 1.96).
"""

from __future__ import annotations

import math
import random
from typing import Optional

from core.bankers_engine import BankersEngine
from simulation.resource_generator import generate_patient_demands
from utils.config_loader import ConfigLoader

CI_METHOD = "Wilson score interval"
CI_Z = 1.96
CI_LEVEL = 0.95


def run_single_trial(
    total_resources: list[int],
    resource_names: list[str],
    n_patients: int,
    severity_dist: dict[str, float],
    demand_profiles: dict,
    rng: random.Random,
    demand_fn=None,
) -> tuple[bool, bool, bool, dict[str, float], int]:
    """
    Run one Monte Carlo trial with exactly n_patients admission attempts.

    Returns (collapsed, admission_failed, unsafe, utilization, admitted_count).
    demand_fn, if given, is (tier, n_resources, rng) -> (allocation, max_demand).
    Default: independent Phase 1 generator (Model A).
    """
    engine = BankersEngine(total_resources=total_resources, resource_names=resource_names)
    n_res = len(total_resources)

    tiers = list(severity_dist.keys())
    weights = list(severity_dist.values())

    for i in range(n_patients):
        tier = rng.choices(tiers, weights=weights, k=1)[0]
        if demand_fn is not None:
            allocation, max_demand = demand_fn(tier, n_res, rng)
        else:
            allocation, max_demand = generate_patient_demands(tier, demand_profiles, n_res, rng)
        try:
            engine.add_patient(f"P{i:04d}", allocation, max_demand)
        except ValueError:
            return True, True, False, engine.utilization(), engine.num_patients

    safe, _, _ = engine.is_safe()
    unsafe = not safe
    # Collapse = admission failure (handled above) OR unsafe Banker's state.
    collapsed = unsafe
    return collapsed, False, unsafe, engine.utilization(), n_patients


def wilson_ci(
    successes: int,
    trials: int,
    z: float = CI_Z,
) -> tuple[float, float, float]:
    """
    Wilson score interval for a binomial proportion.

    Returns (p_hat, ci_lower, ci_upper) with full floating-point precision.
    """
    if trials <= 0:
        return 0.0, 0.0, 0.0

    p_hat = successes / trials
    # Wilson score: centre = (p + z^2/(2n)) / (1 + z^2/n)
    # half = [z/(1+z^2/n)] * sqrt(p(1-p)/n + z^2/(4n^2))
    z2 = z * z
    centre = (p_hat + z2 / (2 * trials)) / (1 + z2 / trials)
    half = (z / (1 + z2 / trials)) * math.sqrt(
        p_hat * (1 - p_hat) / trials + z2 / (4 * trials * trials)
    )
    return p_hat, max(0.0, centre - half), min(1.0, centre + half)


def threshold_at_probability(
    probability_curve: list[dict],
    probability_key: str,
    target: float = 0.50,
) -> Optional[int]:
    """
    Discrete threshold: min { n : p_hat(n) >= target } among tested integer n.

    n50 uses target=0.50. No interpolation between n values.
    Returns None if no tested n reaches the target.
    """
    for entry in probability_curve:
        if entry.get(probability_key, 0.0) >= target:
            return entry["n"]
    return None


def monte_carlo_sweep(
    total_resources: list[int],
    resource_names: list[str],
    severity_dist: dict[str, float],
    demand_profiles: dict,
    max_patients: int,
    trials_per_n: int,
    base_seed: int = 42,
    min_patients: int = 1,
    demand_fn=None,
    progress_every: int = 0,
):
    """Sweep n = min_patients..max_patients with trials_per_n independent trials per n."""
    result = None
    for event in iter_monte_carlo_sweep(
        total_resources=total_resources,
        resource_names=resource_names,
        severity_dist=severity_dist,
        demand_profiles=demand_profiles,
        max_patients=max_patients,
        trials_per_n=trials_per_n,
        base_seed=base_seed,
        min_patients=min_patients,
        demand_fn=demand_fn,
        progress_every=progress_every,
    ):
        if event["event"] == "complete":
            result = event["result"]
    return result


def iter_monte_carlo_sweep(
    total_resources: list[int],
    resource_names: list[str],
    severity_dist: dict[str, float],
    demand_profiles: dict,
    max_patients: int,
    trials_per_n: int,
    base_seed: int = 42,
    min_patients: int = 1,
    demand_fn=None,
    progress_every: int = 0,
):
    """
    Same estimator as monte_carlo_sweep. Yields progress dicts; RNG order is
    unchanged because each trial uses Random(base_seed + n * 1000 + t).

    Events:
      progress — batched running p_hat_t = K_t / t for the current n (Wilson from backend)
      n_complete — finished load n
      complete — full result (same shape as monte_carlo_sweep)
    """
    if min_patients < 1:
        raise ValueError("min_patients must be >= 1")
    if max_patients < min_patients:
        raise ValueError("max_patients must be >= min_patients")
    if trials_per_n < 1:
        raise ValueError("trials_per_n must be >= 1")

    probability_curve: list[dict] = []
    loads = list(range(min_patients, max_patients + 1))
    total_planned = len(loads) * trials_per_n
    completed_global = 0
    every = int(progress_every) if progress_every else 0

    for n in loads:
        collapse_count = 0
        admission_fail_count = 0
        unsafe_count = 0
        util_accum = {name: 0.0 for name in resource_names}

        for t in range(trials_per_n):
            seed = base_seed + n * 1000 + t
            rng = random.Random(seed)
            collapsed, admission_failed, unsafe, util, _ = run_single_trial(
                total_resources, resource_names, n,
                severity_dist, demand_profiles, rng,
                demand_fn=demand_fn,
            )
            if collapsed:
                collapse_count += 1
            if admission_failed:
                admission_fail_count += 1
            if unsafe:
                unsafe_count += 1
            for name in resource_names:
                util_accum[name] += util.get(name, 0.0)

            completed_global += 1
            trial_no = t + 1
            if every > 0 and (trial_no % every == 0 or trial_no == trials_per_n):
                p_hat, lo, hi = wilson_ci(collapse_count, trial_no)
                yield {
                    "event": "progress",
                    "n": n,
                    "trial": trial_no,
                    "trials_per_n": trials_per_n,
                    "collapse_trials": collapse_count,
                    "safe_trials": trial_no - collapse_count,
                    "unsafe_trials": unsafe_count,
                    "admission_fail_trials": admission_fail_count,
                    "p_hat": p_hat,
                    "wilson_lower": lo,
                    "wilson_upper": hi,
                    "completed_trials": completed_global,
                    "planned_trials": total_planned,
                }

        p_collapse, ci_lo, ci_hi = wilson_ci(collapse_count, trials_per_n)
        p_admit, ci_admit_lo, ci_admit_hi = wilson_ci(admission_fail_count, trials_per_n)
        p_unsafe, ci_unsafe_lo, ci_unsafe_hi = wilson_ci(unsafe_count, trials_per_n)
        avg_util = {name: util_accum[name] / trials_per_n for name in resource_names}
        row = {
            "n": n,
            "p_collapse": p_collapse,
            "ci_lo": ci_lo,
            "ci_hi": ci_hi,
            "p_admission_failure": p_admit,
            "p_admission_failure_ci_lo": ci_admit_lo,
            "p_admission_failure_ci_hi": ci_admit_hi,
            "p_unsafe": p_unsafe,
            "p_unsafe_ci_lo": ci_unsafe_lo,
            "p_unsafe_ci_hi": ci_unsafe_hi,
            "utilization": avg_util,
            "trials": trials_per_n,
            "collapse_trials": collapse_count,
            "safe_trials": trials_per_n - collapse_count,
            "unsafe_trials": unsafe_count,
            "admission_fail_trials": admission_fail_count,
        }
        probability_curve.append(row)
        yield {"event": "n_complete", "row": row, "n50": threshold_at_probability(probability_curve, "p_collapse", 0.50)}

    threshold_10 = threshold_at_probability(probability_curve, "p_collapse", 0.10)
    threshold_50 = threshold_at_probability(probability_curve, "p_collapse", 0.50)
    threshold_70 = threshold_at_probability(probability_curve, "p_collapse", 0.70)
    threshold_50_unsafe = threshold_at_probability(probability_curve, "p_unsafe", 0.50)

    by_n = {entry["n"]: entry for entry in probability_curve}
    collapse_util: dict[str, float] = {}
    if threshold_50 is not None and threshold_50 in by_n:
        collapse_util = by_n[threshold_50]["utilization"]

    risk_summary = {
        "threshold_10pct": threshold_10,
        "threshold_50pct": threshold_50,
        "n50": threshold_50,
        "n50_definition": "min { n tested : p_hat(n) >= 0.50 } among integer loads min..max; no interpolation.",
        "threshold_70pct": threshold_70,
        "threshold_50pct_unsafe": threshold_50_unsafe,
        "max_safe_patients": (threshold_10 - 1) if threshold_10 else max_patients,
        "collapse_utilization": collapse_util,
    }

    result = {
        "probability_curve": probability_curve,
        "risk_summary": risk_summary,
        "ci_method": CI_METHOD,
        "ci_z": CI_Z,
        "ci_level": CI_LEVEL,
        "trials_per_n": trials_per_n,
        "min_patients": min_patients,
        "max_patients": max_patients,
        "base_seed": base_seed,
        "seed_policy": "trial t at load n uses Random(base_seed + n * 1000 + t)",
        "probability_estimator": "p_hat = K_n / T where K_n is collapse trials (admission failure or unsafe)",
    }
    yield {"event": "complete", "result": result}


def monte_carlo_from_config(
    config: ConfigLoader,
    trials_per_n: int = 100,
) -> dict:
    return monte_carlo_sweep(
        total_resources=config.resource_totals(config.simulation_mode),
        resource_names=config.resource_names,
        severity_dist=config.severity_distribution(config.severity_mode),
        demand_profiles=config.raw()["demand_profiles"],
        max_patients=config.max_patients,
        trials_per_n=trials_per_n,
        base_seed=config.random_seed,
    )
