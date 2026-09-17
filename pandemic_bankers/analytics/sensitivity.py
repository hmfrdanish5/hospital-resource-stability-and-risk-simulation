"""
Isolated resource sensitivity analysis.

For each resource k, perturb only capacity C_k while holding others fixed:

    C' = C + delta_k * e_k

Estimate n_50 (smallest n with P(collapse) >= 0.50) at baseline C and perturbed C',
then compute discrete marginal sensitivity:

    epsilon_k = (n_50(C') - n_50(C)) / delta_k

Interpretation: estimated additional patients supported per additional resource unit
near the tested baseline (local discrete sensitivity / finite difference, not standard
dimensionless elasticity or a global bottleneck ranking).
"""

from __future__ import annotations

from simulation.monte_carlo import monte_carlo_sweep, threshold_at_probability


def default_delta(capacity: int, fraction: float = 0.10) -> int:
    """Positive integer perturbation for one resource dimension."""
    return max(1, int(round(capacity * fraction)))


def compute_elasticity(
    n50_baseline: int | None,
    n50_perturbed: int | None,
    delta_k: int,
) -> tuple[int | None, float | None]:
    """
    epsilon_k = (n50(C + delta_k e_k) - n50(C)) / delta_k

    n50 is the discrete min { n : p_hat(n) >= 0.50 }. Elasticity is therefore
    an empirical discrete sensitivity from finite Monte Carlo, not a physical
    constant. delta_k == 0 is undefined.
    """
    if delta_k == 0:
        raise ValueError("delta_k must be non-zero; elasticity is undefined at 0.")
    if n50_baseline is None or n50_perturbed is None:
        return None, None
    delta_n50 = n50_perturbed - n50_baseline
    return delta_n50, delta_n50 / delta_k


def perturb_resource(
    base: list[int],
    resource_index: int,
    delta: int,
) -> list[int]:
    """C' = C + delta * e_k. Only index resource_index changes."""
    if resource_index < 0 or resource_index >= len(base):
        raise IndexError("resource_index out of range")
    perturbed = list(base)
    perturbed[resource_index] = perturbed[resource_index] + delta
    return perturbed


def run_isolated_sensitivity(
    base_resources: list[int],
    resource_names: list[str],
    severity_dist: dict[str, float],
    demand_profiles: dict,
    max_patients: int = 40,
    trials_per_n: int = 30,
    base_seed: int = 42,
    delta_fraction: float = 0.10,
    threshold_key: str = "p_collapse",
    threshold_target: float = 0.50,
) -> dict:
    """
    Run baseline sweep and one-at-a-time resource perturbations.

    Returns discrete marginal sensitivity table and metadata.
    """
    baseline_sweep = monte_carlo_sweep(
        total_resources=base_resources,
        resource_names=resource_names,
        severity_dist=severity_dist,
        demand_profiles=demand_profiles,
        max_patients=max_patients,
        trials_per_n=trials_per_n,
        base_seed=base_seed,
    )
    n50_baseline = threshold_at_probability(
        baseline_sweep["probability_curve"], threshold_key, threshold_target
    )

    rows: list[dict] = []
    for k, name in enumerate(resource_names):
        delta_k = default_delta(base_resources[k], delta_fraction)
        perturbed = perturb_resource(base_resources, k, delta_k)
        perturbed_sweep = monte_carlo_sweep(
            total_resources=perturbed,
            resource_names=resource_names,
            severity_dist=severity_dist,
            demand_profiles=demand_profiles,
            max_patients=max_patients,
            trials_per_n=trials_per_n,
            base_seed=base_seed + (k + 1) * 100_000,
        )
        n50_perturbed = threshold_at_probability(
            perturbed_sweep["probability_curve"], threshold_key, threshold_target
        )

        if n50_baseline is not None and n50_perturbed is not None:
            delta_n50, elasticity = compute_elasticity(n50_baseline, n50_perturbed, delta_k)
        else:
            delta_n50 = None
            elasticity = None

        rows.append({
            "resource": name,
            "baseline_capacity": base_resources[k],
            "added_capacity": delta_k,
            "new_capacity": perturbed[k],
            "n50_baseline": n50_baseline,
            "n50_perturbed": n50_perturbed,
            "delta_n50": delta_n50,
            "elasticity": elasticity,
        })

    return {
        "analysis_type": "isolated_resource_sensitivity",
        "baseline_resources": dict(zip(resource_names, base_resources)),
        "n50_baseline": n50_baseline,
        "threshold_key": threshold_key,
        "threshold_target": threshold_target,
        "delta_fraction": delta_fraction,
        "trials_per_n": trials_per_n,
        "max_patients": max_patients,
        "elasticity_formula": "epsilon_k = (n_50(C + delta_k * e_k) - n_50(C)) / delta_k",
        "sensitivity_label": "Discrete Marginal Patient-Capacity Sensitivity",
        "elasticity_interpretation": (
            "Discrete marginal patient-capacity sensitivity (ε_k): additional tested "
            "patient-count threshold change per extra unit of resource k near this baseline. "
            "This is a local finite-difference sensitivity, not standard dimensionless "
            "elasticity or an absolute bottleneck ranking. Because n50 comes from finite "
            "Monte Carlo, ε_k inherits sampling variability."
        ),
        "n50_definition": "min { n tested : p_hat(n) >= 0.50 }; no interpolation.",
        "rows": rows,
    }


# Backward-compatible alias for CLI callers
def run_sensitivity_analysis(
    base_resources: list[int],
    resource_names: list[str],
    severity_dist: dict[str, float],
    demand_profiles: dict,
    max_patients: int = 40,
    trials_per_n: int = 30,
    base_seed: int = 42,
    **kwargs,
) -> dict:
    return run_isolated_sensitivity(
        base_resources=base_resources,
        resource_names=resource_names,
        severity_dist=severity_dist,
        demand_profiles=demand_profiles,
        max_patients=max_patients,
        trials_per_n=trials_per_n,
        base_seed=base_seed,
        **kwargs,
    )
