"""
Demand, arrival, and LOS samplers for Model A / B / C.

Executable scope (do not over-read comments):

Static Banker's collapse sweep (_sweep_demand) uses only demand_fn:
  A: independent per-resource draws given severity (Phase 1 generator)
  B and C: same severity-conditioned joint ICU/ventilator generator
           (p_icu_severe from occupancy mapping when available)
  Arrival family and LOS do NOT enter n50 / P(collapse).

Dynamic overflow (_overflow_stats) uses arrival_sampler and los_sampler:
  A and B: configured integer arrivals (or Poisson if non-integer mu) and
           uniform LOS bounds from config
  C: calibrated count family (Poisson/NB size) and quantile-reconstructed LOS
  The time model still admits via treatment bundles + Phase 1 max sampling,
  not the Model B joint demand generator.
"""

from __future__ import annotations

import random
from typing import Any, Callable

from data.distributions import nbinom_sample, poisson_sample, sample_fitted_los
from data.provenance import DERIVED_PARAMETER, MODEL_ASSUMPTION
from simulation.resource_generator import generate_patient_demands, validate_patient_vectors


def generate_demands_independent(tier, demand_profiles, n_resources, rng):
    return generate_patient_demands(tier, demand_profiles, n_resources, rng)


def generate_demands_severity_conditioned(
    tier: str,
    demand_profiles: dict,
    n_resources: int,
    rng: random.Random,
    p_icu_severe: float = 0.35,
) -> tuple[list[int], list[int]]:
    """
    P(resource | severity), with ICU and ventilator drawn jointly.

    Critical: ICU=1 and Vent=1 (pathway bundle).
    Severe: with probability p_icu_severe both ICU and Vent are 1, else both 0.
    Mild/Moderate: ICU=0 and Vent=0.
    Other resources remain severity-profile draws.
    """
    alloc, mx = generate_patient_demands(tier, demand_profiles, n_resources, rng)
    p_icu_severe = min(1.0, max(0.0, float(p_icu_severe)))
    if n_resources < 3:
        return alloc, mx

    if tier == "Critical":
        icu = 1
    elif tier == "Severe":
        icu = 1 if rng.random() < p_icu_severe else 0
    else:
        icu = 0

    mx[0] = icu
    mx[2] = icu
    alloc[0] = icu
    alloc[2] = icu
    if icu == 1 and n_resources > 1:
        # Oxygen at least the profile floor, and not independent of ventilation.
        lo = demand_profiles[tier]["min"][1]
        hi = demand_profiles[tier]["max"][1]
        mx[1] = max(mx[1], lo, 4)
        mx[1] = min(mx[1], hi) if hi >= mx[1] else hi
        alloc[1] = min(max(alloc[1], lo), mx[1])
        if n_resources > 3:
            alloc[3] = max(alloc[3], 2)
            mx[3] = max(mx[3], alloc[3])
    validate_patient_vectors(alloc, mx, n_resources)
    return alloc, mx


def p_icu_severe_from_occupancy(
    p_icu_occupancy: float | None,
    severity_dist: dict[str, float],
) -> dict:
    """
    Map aggregate occupancy ratio onto P(ICU | Severe) given:
      P(ICU|Mild)=P(ICU|Moderate)=0, P(ICU|Critical)=1 (MODEL ASSUMPTION).
      P(ICU) = P(Critical) + P(ICU|Severe) P(Severe)
    """
    if p_icu_occupancy is None:
        return {
            "p_icu_severe": 0.35,
            "classification": MODEL_ASSUMPTION,
            "note": "No occupancy ratio available; default P(ICU|Severe)=0.35.",
        }
    p_c = float(severity_dist.get("Critical", 0.0))
    p_s = float(severity_dist.get("Severe", 0.0))
    if p_s <= 1e-9:
        return {
            "p_icu_severe": 0.0,
            "classification": DERIVED_PARAMETER,
            "note": "No Severe mass; Critical absorbs ICU under the mapping assumptions.",
        }
    raw = (p_icu_occupancy - p_c) / p_s
    return {
        "p_icu_severe": min(1.0, max(0.0, raw)),
        "classification": DERIVED_PARAMETER,
        "formula": "(p_icu_occupancy - P(Critical)) / P(Severe), clipped to [0,1]",
        "inputs": {"p_icu_occupancy": p_icu_occupancy, "P_critical": p_c, "P_severe": p_s},
        "note": "Occupancy ratio is not an identified individual probability; this mapping is a model assumption.",
    }


def demand_fn_for_mode(
    mode: str,
    demand_profiles: dict,
    p_icu_severe: float,
) -> Callable:
    mode = mode.upper()

    def _fn(tier, n_resources, rng):
        if mode == "A":
            return generate_demands_independent(tier, demand_profiles, n_resources, rng)
        return generate_demands_severity_conditioned(
            tier, demand_profiles, n_resources, rng, p_icu_severe=p_icu_severe
        )

    return _fn


def make_arrival_sampler(
    calibration: dict | None,
    mu_hourly: float,
    mode: str,
    weekday_relative: list[float] | None = None,
    intensity_scale: float = 1.0,
):
    """
    Hospital-scale mean mu_hourly is a MODEL ASSUMPTION (config).
    Count family and NB size are taken from calibration when mode C.
    Time dependence (mode C): λ(t) = λ_0 · intensity_scale · r_{dow(t)}.
    """
    mu = max(0.0, float(mu_hourly) * float(intensity_scale))
    relatives = list(weekday_relative) if weekday_relative else [1.0] * 7
    if len(relatives) != 7:
        relatives = [1.0] * 7
    use_time = bool(weekday_relative) and mode.upper() == "C"

    def _lambda(t) -> float:
        if not use_time or t is None:
            return mu
        dow = (int(t) // 24) % 7
        return max(0.0, mu * float(relatives[dow]))

    if mode.upper() != "C" or not calibration:
        def _fixed(rng: random.Random, t=None) -> int:
            lam = _lambda(t) if use_time else mu
            return poisson_sample(rng, lam) if lam != int(lam) else int(round(lam))

        if abs(mu - round(mu)) < 1e-9 and not use_time:
            def _const(rng: random.Random, t=None, k=int(round(mu))) -> int:
                return k
            return _const
        return _fixed

    family = calibration["parameters"]["arrival_model"]["value"]
    fit = calibration["parameters"]["arrival_model"].get("fit") or {}
    size = fit.get("nbinom", {}).get("size")

    def _calibrated(rng: random.Random, t=None) -> int:
        lam = _lambda(t)
        if family == "nbinom" and size is not None and size == size and size > 0:
            return nbinom_sample(rng, lam, float(size))
        return poisson_sample(rng, lam)

    return _calibrated


def make_los_sampler(
    calibration: dict | None,
    mode: str,
    fallback_bounds: dict,
    los_scale: float = 1.0,
):
    """LOS in hours. Mode C uses fitted days × 24; otherwise uniform integer hours."""
    scale = max(0.0, float(los_scale))

    def _uniform(severity: str, rng: random.Random) -> int:
        b = fallback_bounds[severity]
        hours = rng.randint(int(b["min"]), int(b["max"]))
        return max(1, int(round(hours * scale))) if scale != 1.0 else hours

    if mode.upper() != "C" or not calibration:
        return _uniform

    ward = calibration["parameters"]["los_ward_days"]["fit"]
    icu = calibration["parameters"]["los_icu_days"]["fit"]

    def _fitted(severity: str, rng: random.Random) -> int:
        fit = icu if severity in ("Severe", "Critical") else ward
        days = max(0.25, sample_fitted_los(rng, fit) * scale)
        return max(1, int(round(days * 24.0)))

    return _fitted
