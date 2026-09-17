"""
Explicit treatment / resource bundles (Phase 2).

A pathway is all-or-nothing: the patient enters only if every required
component is available. Independent per-resource admission is not used.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from simulation.resource_generator import generate_patient_demands


@dataclass(frozen=True)
class TreatmentRequirement:
    name: str
    target_state: str
    required: tuple[int, ...]

    def satisfiable(self, available: Sequence[int]) -> bool:
        if len(available) != len(self.required):
            raise ValueError("Available vector length must match the bundle.")
        return all(available[j] >= self.required[j] for j in range(len(self.required)))

    def unsatisfied(self, available: Sequence[int]) -> list[int]:
        """Indices j where available[j] < required[j]."""
        return [
            j for j in range(len(self.required))
            if available[j] < self.required[j]
        ]


def load_pathways(cfg: dict, n_resources: int) -> dict[str, TreatmentRequirement]:
    pathways_cfg = cfg["treatment_pathways"]
    pathways: dict[str, TreatmentRequirement] = {}
    for name in ("WARD", "ICU"):
        block = pathways_cfg[name]
        required = tuple(int(x) for x in block["required"])
        if len(required) != n_resources:
            raise ValueError(
                f"Pathway '{name}' required length {len(required)} != {n_resources}."
            )
        if any(v < 0 for v in required):
            raise ValueError(f"Pathway '{name}' has a negative requirement.")
        pathways[name] = TreatmentRequirement(
            name=name,
            target_state=str(block["target_state"]),
            required=required,
        )
    return pathways


def pathway_for_severity(severity: str, cfg: dict) -> str:
    mapping = cfg["treatment_pathways"]["severity_pathway"]
    if severity not in mapping:
        raise ValueError(f"No pathway mapped for severity '{severity}'.")
    return mapping[severity]


# Lower rank = higher admission priority (deterministic).
TRIAGE_RANK = {
    "Critical": 0,
    "Severe": 1,
    "Moderate": 2,
    "Mild": 3,
}


def triage_priority(severity: str) -> int:
    """Deterministic severity rank. Critical is admitted before Mild."""
    if severity not in TRIAGE_RANK:
        raise ValueError(f"Unknown severity '{severity}'.")
    return TRIAGE_RANK[severity]


def sample_max_demand(
    severity: str,
    demand_profiles: dict,
    n_resources: int,
    rng,
    allocation: Sequence[int],
) -> list[int]:
    """
    Sample Max from Phase 1 demand profiles, then enforce Max >= Allocation
    so the bundle does not violate Banker's invariants.
    """
    _, sampled_max = generate_patient_demands(
        severity, demand_profiles, n_resources, rng
    )
    return [max(allocation[j], sampled_max[j]) for j in range(n_resources)]
