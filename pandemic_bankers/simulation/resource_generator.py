"""
Resource demand generation for pandemic patient admission.

Generates (allocation, max_demand) vectors that satisfy Banker's invariants:
  0 <= allocation[j] <= max_demand[j]

Resource semantics (index order must match config resource names).
These are MODEL units, not measured clinical doses:

  ICU_Beds      — discrete 0 or 1 per patient (binary resource)
  Oxygen_Units  — non-negative integer model units
  Ventilators   — discrete 0 or 1 per patient (binary resource)
  Nurses        — non-negative integer staffing units (one unit = one
                  allocatable nurse-slot in this model; not a measured FTE hour)
  Blood_Units   — non-negative integer model units

Generation uses randint, so all quantities are integers. A patient never
receives more than one ICU bed or ventilator from this generator.
"""

from __future__ import annotations

import random
from typing import Sequence


# Resource indices for the five-resource hospital model.
BINARY_RESOURCES: frozenset[int] = frozenset({0, 2})  # ICU_Beds, Ventilators


def generate_patient_demands(
    tier: str,
    demand_profiles: dict[str, dict[str, list[int]]],
    n_resources: int,
    rng: random.Random,
) -> tuple[list[int], list[int]]:
    """
    Sample (allocation, max_demand) for one patient at a given severity tier.

    Max demand is drawn uniformly from [min, max] per resource.
    Allocation is drawn uniformly from [min, max_demand] per resource, with
    binary resources (ICU, ventilator) restricted to {0, 1}.
    """
    if tier not in demand_profiles:
        raise ValueError(f"Unknown severity tier: '{tier}'")

    lo = demand_profiles[tier]["min"]
    hi = demand_profiles[tier]["max"]

    if len(lo) != n_resources or len(hi) != n_resources:
        raise ValueError(
            f"Demand profile for '{tier}' has length {len(lo)}/{len(hi)}, "
            f"expected {n_resources}."
        )

    max_demand: list[int] = []
    for j in range(n_resources):
        if lo[j] > hi[j]:
            raise ValueError(
                f"demand_profiles['{tier}']: min[{j}]={lo[j]} > max[{j}]={hi[j]}"
            )
        if hi[j] == 0:
            # Tier does not use this resource at peak demand.
            max_demand.append(0)
        elif j in BINARY_RESOURCES:
            # Binary resource: peak demand is 0 or 1, respecting configured minimum.
            max_demand.append(rng.randint(lo[j], hi[j]))
        else:
            max_demand.append(rng.randint(lo[j], hi[j]))

    allocation: list[int] = []
    for j in range(n_resources):
        # Initial allocation lies in [min, max_demand] — never below the tier floor.
        if max_demand[j] == 0:
            allocation.append(0)
        elif j in BINARY_RESOURCES:
            allocation.append(rng.randint(lo[j], max_demand[j]))
        else:
            allocation.append(rng.randint(lo[j], max_demand[j]))

    validate_patient_vectors(allocation, max_demand, n_resources)
    return allocation, max_demand


def compute_need(
    allocation: Sequence[int],
    max_demand: Sequence[int],
) -> list[int]:
    """Need[j] = Max[j] - Allocation[j]; must be non-negative."""
    return [max_demand[j] - allocation[j] for j in range(len(allocation))]


def validate_patient_vectors(
    allocation: Sequence[int],
    max_demand: Sequence[int],
    n_resources: int,
) -> None:
    """Raise ValueError if patient vectors violate Banker's constraints."""
    if len(allocation) != n_resources or len(max_demand) != n_resources:
        raise ValueError("Vector length mismatch.")
    for j in range(n_resources):
        if allocation[j] < 0 or max_demand[j] < 0:
            raise ValueError(f"Negative value at resource index {j}.")
        if allocation[j] > max_demand[j]:
            raise ValueError(
                f"allocation[{j}]={allocation[j]} > max_demand[{j}]={max_demand[j]}"
            )
