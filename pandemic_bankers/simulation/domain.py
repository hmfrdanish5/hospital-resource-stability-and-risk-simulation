"""
Hospital System Domain
======================
Generates synthetic pandemic patient populations and registers them
with the BankersEngine for safety analysis.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from core.bankers_engine import BankersEngine
from simulation.resource_generator import generate_patient_demands
from utils.config_loader import ConfigLoader


@dataclass
class Patient:
    """Represents a single pandemic patient."""
    patient_id: str
    severity: str
    allocation: list[int]
    max_demand: list[int]

    def need(self) -> list[int]:
        """Remaining resource need (max_demand − allocation)."""
        return [self.max_demand[i] - self.allocation[i] for i in range(len(self.allocation))]

    def to_dict(self) -> dict:
        return {
            "patient_id": self.patient_id,
            "severity": self.severity,
            "allocation": self.allocation,
            "max_demand": self.max_demand,
            "need": self.need(),
        }


class HospitalSystem:
    """
    Orchestrates patient generation and BankersEngine registration.

    Parameters
    ----------
    config : ConfigLoader
        Validated hospital configuration.
    engine : BankersEngine
        Banker's algorithm engine (already configured with resource totals).
    rng : random.Random
        Seeded random number generator for reproducible trials.
    """

    SEVERITY_TIERS: list[str] = ["Mild", "Moderate", "Severe", "Critical"]

    def __init__(
        self,
        config: ConfigLoader,
        engine: BankersEngine,
        rng: random.Random,
        severity_dist: dict[str, float] | None = None,
    ) -> None:
        self._config = config
        self._engine = engine
        self._rng = rng
        self._patients: list[Patient] = []
        self._severity_mode = config.severity_mode
        self._severity_override = severity_dist
        self._n_resources = engine.num_resources
        self._demand_profiles = config.raw()["demand_profiles"]

    def _pick_severity(self) -> str:
        """Sample a severity tier from the configured distribution."""
        if self._severity_override is not None:
            dist = self._severity_override
        else:
            dist = self._config.severity_distribution(self._severity_mode)
        tiers = list(dist.keys())
        weights = list(dist.values())
        return self._rng.choices(tiers, weights=weights, k=1)[0]

    def _generate_demand_vector(self, tier: str) -> tuple[list[int], list[int]]:
        """Generate (allocation, max_demand) vectors for a patient."""
        return generate_patient_demands(
            tier, self._demand_profiles, self._n_resources, self._rng
        )

    def admit_patient(self) -> Patient | None:
        """
        Attempt to admit one new patient.

        Returns the Patient if admission succeeded, or None if the engine
        cannot accommodate the initial allocation (physical capacity limit).
        """
        patient_id = f"P{len(self._patients) + 1:04d}"
        severity = self._pick_severity()
        allocation, max_demand = self._generate_demand_vector(severity)

        try:
            self._engine.add_patient(patient_id, allocation, max_demand)
        except ValueError:
            return None

        patient = Patient(patient_id, severity, allocation, max_demand)
        self._patients.append(patient)
        return patient

    def admit_n_patients(self, n: int) -> list[Patient]:
        """
        Attempt to admit n patients sequentially.

        Stops early if a patient's initial allocation exceeds available resources.
        Returns the list of successfully admitted patients.
        """
        admitted: list[Patient] = []
        for _ in range(n):
            patient = self.admit_patient()
            if patient is None:
                break
            admitted.append(patient)
        return admitted

    @property
    def patients(self) -> list[Patient]:
        return list(self._patients)

    @property
    def patient_count(self) -> int:
        return len(self._patients)

    def severity_breakdown(self) -> dict[str, int]:
        counts: dict[str, int] = {t: 0 for t in self.SEVERITY_TIERS}
        for p in self._patients:
            if p.severity in counts:
                counts[p.severity] += 1
        return counts

    def snapshot_dict(self) -> dict:
        """Return a JSON-serialisable snapshot of the hospital system."""
        return {
            "patient_count": self.patient_count,
            "severity_breakdown": self.severity_breakdown(),
            "engine_snapshot": self._engine.snapshot(),
            "patients": [p.to_dict() for p in self._patients],
        }
