"""
Time-dependent hospital simulation (Phase 2).

Wraps the Phase 1 Banker's engine. The safety algorithm is unchanged: each
time step records SAFE/UNSAFE as a snapshot of currently allocated in-care
patients. Overflow, fatigue, and degradation are separate risk indicators.

Preemption of in-care patients by a higher-acuity arrival is not implemented.
Releasing holdings without a well-defined remaining-claim update would make
Banker's Max/Need interpretation ambiguous. Capacity shortfall uses explicit
priority overflow instead (see apply_capacity).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Optional

from core.bankers_engine import BankersEngine
from simulation.time_model import (
    PARAMETER_STATUS,
    capacity_at_time,
    describe_time,
    merge_dynamic_config,
)
from simulation.treatments import (
    load_pathways,
    pathway_for_severity,
    sample_max_demand,
    triage_priority,
)

PATIENT_STATES = ("ED", "WARD", "ICU", "ED_OVERFLOW", "COMPLETED")
FATIGUE_NORMAL = "normal"
FATIGUE_FATIGUED = "fatigued"


@dataclass
class TemporalPatient:
    patient_id: str
    severity: str
    triage_priority: int
    pathway_name: str
    bundle: tuple[int, ...]
    allocation: list[int]
    max_demand: list[int]
    arrival_time: int
    expected_los: float
    elapsed_time: float = 0.0
    remaining_time: float = 0.0
    current_state: str = "ED"
    acuity: float = 0.0
    overflow_duration: float = 0.0
    overflow_events: int = 0
    fatigue_los_applied: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "patient_id": self.patient_id,
            "severity": self.severity,
            "triage_priority": self.triage_priority,
            "pathway": self.pathway_name,
            "state": self.current_state,
            "arrival_time": self.arrival_time,
            "expected_los": self.expected_los,
            "elapsed_time": self.elapsed_time,
            "remaining_time": self.remaining_time,
            "acuity": self.acuity,
            "overflow_duration": self.overflow_duration,
            "allocation": list(self.allocation),
            "max_demand": list(self.max_demand),
        }


@dataclass
class FatigueTracker:
    state: str = FATIGUE_NORMAL
    high_util_streak: int = 0
    low_util_streak: int = 0
    fatigue_start_time: Optional[int] = None
    fatigue_duration: float = 0.0
    fatigue_events: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "fatigue_start_time": self.fatigue_start_time,
            "fatigue_duration": self.fatigue_duration,
            "fatigue_events": self.fatigue_events,
        }


class DynamicHospitalSimulator:
    """Discrete-time hospital with C(t), LOS, fatigue, bundles, overflow, triage."""

    def __init__(
        self,
        base_capacity: list[int],
        resource_names: list[str],
        dynamic_cfg: dict | None,
        severity_dist: dict[str, float],
        demand_profiles: dict,
        rng: random.Random,
        arrival_sampler=None,
        los_sampler=None,
    ) -> None:
        self.base_capacity = list(base_capacity)
        self.resource_names = list(resource_names)
        self.cfg = merge_dynamic_config(dynamic_cfg)
        self.severity_dist = dict(severity_dist)
        self.demand_profiles = demand_profiles
        self.rng = rng
        self.arrival_sampler = arrival_sampler
        self.los_sampler = los_sampler
        self.dt = int(self.cfg["dt_hours"])
        self.n_res = len(resource_names)
        self.pathways = load_pathways(self.cfg, self.n_res)
        self.staffing_name = self.cfg["staffing"]["resource_name"]
        if self.staffing_name not in resource_names:
            raise ValueError(f"Unknown staffing resource '{self.staffing_name}'.")
        self.staffing_index = resource_names.index(self.staffing_name)

        self.t = 0
        self.engine = BankersEngine(list(base_capacity), list(resource_names))
        self.patients: dict[str, TemporalPatient] = {}
        self._next_id = 1
        self.fatigue = FatigueTracker()
        self.events: list[dict[str, Any]] = []
        self.history: list[dict[str, Any]] = []
        self._apply_capacity(self.t, reason="initialize")

    def _pid(self) -> str:
        pid = f"T{self._next_id:04d}"
        self._next_id += 1
        return pid

    def _sample_severity(self) -> str:
        tiers = list(self.severity_dist.keys())
        weights = list(self.severity_dist.values())
        return self.rng.choices(tiers, weights=weights, k=1)[0]

    def _sample_los(self, severity: str) -> int:
        if self.los_sampler is not None:
            return max(1, int(round(self.los_sampler(severity, self.rng))))
        bounds = self.cfg["los_hours"][severity]
        lo, hi = int(bounds["min"]), int(bounds["max"])
        if lo > hi:
            raise ValueError(f"LOS bounds invalid for {severity}: min={lo} > max={hi}")
        return self.rng.randint(lo, hi)

    def _n_arrivals(self) -> int:
        if self.arrival_sampler is not None:
            try:
                n = self.arrival_sampler(self.rng, self.t)
            except TypeError:
                n = self.arrival_sampler(self.rng)
            return max(0, int(n))
        return int(self.cfg["arrivals_per_step"])

    def _effective_los(self, base_los: float) -> float:
        if self.fatigue.state == FATIGUE_FATIGUED:
            alpha = float(self.cfg["fatigue"]["delay_factor_alpha"])
            return base_los * (1.0 + alpha)
        return base_los

    def _in_care(self) -> list[TemporalPatient]:
        return [
            p for p in self.patients.values()
            if p.current_state in ("WARD", "ICU")
        ]

    def _waiting(self) -> list[TemporalPatient]:
        waiting = [
            p for p in self.patients.values()
            if p.current_state in ("ED", "ED_OVERFLOW")
        ]
        waiting.sort(key=lambda p: (p.triage_priority, p.arrival_time, p.patient_id))
        return waiting

    def _record(self, kind: str, **payload: Any) -> None:
        event = {"t": self.t, "kind": kind, **payload}
        self.events.append(event)

    def _apply_capacity(self, t: int, reason: str) -> None:
        """
        Set C(t). If C_j(t) < A_total,j, overflow lowest-priority in-care
        patients until A_total <= C. Allocations are never silently destroyed.
        """
        c_t = capacity_at_time(
            self.base_capacity, self.resource_names, t, self.cfg["staffing"]
        )
        allocated = self.engine.allocated_totals()
        while any(c_t[j] < allocated[j] for j in range(self.n_res)):
            short_idx = next(j for j in range(self.n_res) if c_t[j] < allocated[j])
            holders = [
                p for p in self._in_care()
                if p.allocation[short_idx] > 0
            ]
            if not holders:
                raise RuntimeError(
                    f"Capacity shortfall on {self.resource_names[short_idx]} "
                    "with no in-care holders to overflow."
                )
            holders.sort(key=lambda p: (-p.triage_priority, -p.arrival_time, p.patient_id))
            victim = holders[0]
            self._overflow_patient(victim, cause=f"capacity_shortfall:{self.resource_names[short_idx]}")
            allocated = self.engine.allocated_totals()
        self.engine.set_total_resources(c_t)
        self._record(
            "capacity",
            reason=reason,
            C=list(c_t),
            W=list(self.engine.available),
            A_total=self.engine.allocated_totals(),
            staffing_multiplier=describe_time(t, self.cfg["staffing"]).staffing_multiplier,
        )

    def _overflow_patient(self, patient: TemporalPatient, cause: str) -> None:
        if patient.current_state in ("WARD", "ICU"):
            self.engine.remove_patient(patient.patient_id)
        patient.current_state = "ED_OVERFLOW"
        patient.overflow_events += 1
        patient.allocation = [0] * self.n_res
        self._record(
            "overflow",
            patient=patient.patient_id,
            cause=cause,
            severity=patient.severity,
            pathway=patient.pathway_name,
        )

    def _complete_patient(self, patient: TemporalPatient) -> None:
        if patient.current_state in ("WARD", "ICU"):
            self.engine.remove_patient(patient.patient_id)
        patient.current_state = "COMPLETED"
        patient.remaining_time = 0.0
        patient.allocation = [0] * self.n_res
        self._record("complete", patient=patient.patient_id)

    def _admit_patient(self, patient: TemporalPatient) -> bool:
        pathway = self.pathways[patient.pathway_name]
        if not pathway.satisfiable(self.engine.available):
            if patient.current_state != "ED_OVERFLOW":
                patient.current_state = "ED_OVERFLOW"
                patient.overflow_events += 1
                missing = [
                    self.resource_names[j]
                    for j in pathway.unsatisfied(self.engine.available)
                ]
                self._record(
                    "overflow",
                    patient=patient.patient_id,
                    cause="bundle_unsatisfied",
                    missing=missing,
                    severity=patient.severity,
                    pathway=patient.pathway_name,
                )
            return False

        allocation = list(pathway.required)
        max_demand = sample_max_demand(
            patient.severity, self.demand_profiles, self.n_res, self.rng, allocation
        )
        try:
            self.engine.add_patient(patient.patient_id, allocation, max_demand)
        except ValueError:
            return False

        patient.allocation = allocation
        patient.max_demand = max_demand
        patient.current_state = pathway.target_state
        patient.expected_los = self._effective_los(patient.expected_los)
        if self.fatigue.state == FATIGUE_FATIGUED:
            patient.fatigue_los_applied = True
        patient.remaining_time = patient.expected_los
        self._record(
            "admit",
            patient=patient.patient_id,
            state=patient.current_state,
            bundle=list(pathway.required),
        )
        return True

    def create_arrival(self, severity: str | None = None, los: int | None = None) -> TemporalPatient:
        severity = severity or self._sample_severity()
        pathway_name = pathway_for_severity(severity, self.cfg)
        bundle = self.pathways[pathway_name].required
        base_los = float(los if los is not None else self._sample_los(severity))
        patient = TemporalPatient(
            patient_id=self._pid(),
            severity=severity,
            triage_priority=triage_priority(severity),
            pathway_name=pathway_name,
            bundle=bundle,
            allocation=[0] * self.n_res,
            max_demand=[0] * self.n_res,
            arrival_time=self.t,
            expected_los=base_los,
            remaining_time=base_los,
            current_state="ED",
            acuity=float(triage_priority(severity)),
        )
        self.patients[patient.patient_id] = patient
        self._record("arrival", patient=patient.patient_id, severity=severity)
        return patient

    def _tick_los(self) -> None:
        for patient in self._in_care():
            patient.elapsed_time += self.dt
            patient.remaining_time -= self.dt
            if patient.remaining_time <= 0:
                self._complete_patient(patient)

    def _tick_overflow(self) -> None:
        rate = float(self.cfg["degradation"]["rate_per_hour"])
        for patient in self.patients.values():
            if patient.current_state != "ED_OVERFLOW":
                continue
            patient.overflow_duration += self.dt
            patient.elapsed_time += self.dt
            patient.acuity += rate * self.dt

    def _update_fatigue(self) -> None:
        fat_cfg = self.cfg["fatigue"]
        threshold = float(fat_cfg["utilization_threshold"])
        need_high = int(fat_cfg["consecutive_hours"])
        need_low = int(fat_cfg["recovery_hours"])
        c_n = self.engine.total[self.staffing_index]
        a_n = self.engine.allocated_totals()[self.staffing_index]
        util = (a_n / c_n) if c_n > 0 else 1.0

        if util > threshold:
            self.fatigue.high_util_streak += self.dt
            self.fatigue.low_util_streak = 0
        else:
            self.fatigue.low_util_streak += self.dt
            self.fatigue.high_util_streak = 0

        if self.fatigue.state == FATIGUE_NORMAL:
            if self.fatigue.high_util_streak >= need_high:
                self.fatigue.state = FATIGUE_FATIGUED
                self.fatigue.fatigue_start_time = self.t
                self.fatigue.fatigue_events += 1
                alpha = float(fat_cfg["delay_factor_alpha"])
                for patient in self._in_care():
                    if not patient.fatigue_los_applied:
                        patient.remaining_time *= (1.0 + alpha)
                        patient.expected_los *= (1.0 + alpha)
                        patient.fatigue_los_applied = True
                self._record("fatigue_onset", utilization=util, alpha=alpha)
        else:
            self.fatigue.fatigue_duration += self.dt
            if self.fatigue.low_util_streak >= need_low:
                self.fatigue.state = FATIGUE_NORMAL
                self.fatigue.fatigue_start_time = None
                self.fatigue.high_util_streak = 0
                self._record("fatigue_recovery", utilization=util)

    def _try_admissions(self) -> None:
        for patient in self._waiting():
            self._admit_patient(patient)

    def _bottleneck_flags(self) -> dict[str, bool]:
        flags = {}
        for j, name in enumerate(self.resource_names):
            flags[name] = self.engine.available[j] == 0 and self.engine.total[j] > 0
        return flags

    def step(self) -> dict[str, Any]:
        """Advance one Δt. Conservation is checked before returning."""
        self.t += self.dt
        self._tick_los()
        self._apply_capacity(self.t, reason="time_step")
        self._tick_overflow()
        self._update_fatigue()
        for _ in range(self._n_arrivals()):
            self.create_arrival()
        self._try_admissions()
        self.engine.validate_invariants()

        safe, sequence, blocking = self.engine.is_safe()
        clock = describe_time(self.t, self.cfg["staffing"])
        snapshot = {
            "t": self.t,
            "hour": clock.hour,
            "day_name": clock.day_name,
            "handover": clock.handover,
            "weekend": clock.weekend,
            "staffing_multiplier": clock.staffing_multiplier,
            "C": list(self.engine.total),
            "W": list(self.engine.available),
            "A_total": self.engine.allocated_totals(),
            "banker_safe": safe,
            "banker_sequence": sequence,
            "blocking_resource": blocking,
            "fatigue_state": self.fatigue.state,
            "nurse_utilization": (
                self.engine.allocated_totals()[self.staffing_index] / self.engine.total[self.staffing_index]
                if self.engine.total[self.staffing_index] > 0 else 1.0
            ),
            "counts": self.state_counts(),
            "bottleneck": self._bottleneck_flags(),
        }
        self.history.append(snapshot)
        return snapshot

    def run(self, horizon_hours: int | None = None) -> dict[str, Any]:
        horizon = int(horizon_hours if horizon_hours is not None else self.cfg["horizon_hours"])
        steps = horizon // self.dt
        for _ in range(steps):
            self.step()
        return self.results()

    def state_counts(self) -> dict[str, int]:
        counts = {s: 0 for s in PATIENT_STATES}
        for p in self.patients.values():
            counts[p.current_state] = counts.get(p.current_state, 0) + 1
        return counts

    def secondary_metrics(self) -> dict[str, Any]:
        n = max(len(self.history), 1)
        arrivals = list(self.patients.values())
        n_arrivals = len(arrivals) or 1
        overflowed = [p for p in arrivals if p.overflow_events > 0]
        overflow_durations = [p.overflow_duration for p in overflowed]
        unsafe_hours = sum(1 for h in self.history if not h["banker_safe"])
        bottleneck_hours = {name: 0 for name in self.resource_names}
        for h in self.history:
            for name, flag in h["bottleneck"].items():
                if flag:
                    bottleneck_hours[name] += self.dt
        return {
            "overflow_event_rate": sum(p.overflow_events for p in arrivals) / n,
            "mean_overflow_duration": (
                sum(overflow_durations) / len(overflow_durations)
                if overflow_durations else 0.0
            ),
            "maximum_overflow_duration": max(overflow_durations) if overflow_durations else 0.0,
            "fraction_of_patients_experiencing_overflow": len(overflowed) / n_arrivals if arrivals else 0.0,
            "fatigue_duration": self.fatigue.fatigue_duration,
            "fatigue_events": self.fatigue.fatigue_events,
            "resource_bottleneck_exposure_hours": bottleneck_hours,
            "banker_unsafe_timesteps": unsafe_hours,
            "n_arrivals": len(arrivals),
            "n_completed": sum(1 for p in arrivals if p.current_state == "COMPLETED"),
        }

    def example_trace(self, limit: int = 24) -> list[dict[str, Any]]:
        interesting = {"overflow", "fatigue_onset", "fatigue_recovery", "admit", "complete", "capacity"}
        selected: list[dict[str, Any]] = []
        for event in self.events:
            if event["kind"] in interesting:
                selected.append(event)
            if len(selected) >= limit:
                break
        return selected

    def results(self) -> dict[str, Any]:
        last = self.history[-1] if self.history else None
        return {
            "phase": 2,
            "parameter_status": PARAMETER_STATUS,
            "dt_hours": self.dt,
            "horizon_hours": self.t,
            "base_capacity": dict(zip(self.resource_names, self.base_capacity)),
            "preemption": {
                "implemented": False,
                "reason": (
                    "Optional acuity-based preemption is deferred. Removing an in-care "
                    "patient's Allocation without a defined remaining Max/Need would "
                    "make Banker's safety interpretation ambiguous. Capacity drops use "
                    "explicit priority overflow, which updates Allocation, Available, "
                    "and patient state before C(t) is applied."
                ),
            },
            "fatigue": self.fatigue.to_dict(),
            "state_counts": self.state_counts(),
            "last_snapshot": last,
            "secondary_metrics": self.secondary_metrics(),
            "history": self.history,
            "example_trace": self.example_trace(),
            "patients": [p.to_dict() for p in self.patients.values()],
            "equations": {
                "C_nurses_t": "round(BaseNurses * m_shift(t) * m_weekend(t))",
                "W_t": "C_t - A_total_t",
                "effective_LOS": "base_LOS * (1 + alpha) while fatigued (alpha is a sensitivity parameter)",
                "acuity_overflow": "acuity(t+dt) = acuity(t) + degradation_rate * dt",
            },
        }


def run_dynamic_simulation(
    base_capacity: list[int],
    resource_names: list[str],
    dynamic_cfg: dict | None,
    severity_dist: dict[str, float],
    demand_profiles: dict,
    seed: int,
    horizon_hours: int | None = None,
    arrivals_per_step: int | None = None,
) -> dict[str, Any]:
    cfg = merge_dynamic_config(dynamic_cfg)
    if arrivals_per_step is not None:
        cfg["arrivals_per_step"] = int(arrivals_per_step)
    sim = DynamicHospitalSimulator(
        base_capacity=base_capacity,
        resource_names=resource_names,
        dynamic_cfg=cfg,
        severity_dist=severity_dist,
        demand_profiles=demand_profiles,
        rng=random.Random(seed),
    )
    return sim.run(horizon_hours=horizon_hours)
