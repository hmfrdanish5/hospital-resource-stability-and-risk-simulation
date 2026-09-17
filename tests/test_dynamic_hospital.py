"""Phase 2: time-dependent hospital, staffing, LOS, fatigue, bundles, overflow."""

import sys
import os
import random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pandemic_bankers"))

from simulation.time_model import (
    capacity_at_time,
    day_of_week,
    hour_of_day,
    is_handover_hour,
    is_weekend,
    merge_dynamic_config,
    nurse_capacity,
    staffing_multiplier,
)
from simulation.treatments import TreatmentRequirement, load_pathways, triage_priority
from simulation.dynamic_hospital import DynamicHospitalSimulator


NAMES = ["ICU_Beds", "Oxygen_Units", "Ventilators", "Nurses", "Blood_Units"]
BASE = [4, 40, 4, 10, 20]
SEV = {"Mild": 1.0, "Moderate": 0.0, "Severe": 0.0, "Critical": 0.0}
DEMAND = {
    "Mild": {"min": [0, 1, 0, 0, 0], "max": [0, 3, 0, 1, 1]},
    "Moderate": {"min": [0, 3, 0, 1, 1], "max": [0, 6, 0, 2, 2]},
    "Severe": {"min": [0, 6, 0, 2, 2], "max": [1, 12, 1, 3, 4]},
    "Critical": {"min": [1, 10, 1, 3, 3], "max": [1, 20, 1, 5, 6]},
}


def _cfg(**overrides):
    cfg = merge_dynamic_config({
        "arrivals_per_step": 0,
        "horizon_hours": 24,
        **overrides,
    })
    return cfg


def _sim(cfg=None, base=None, sev=None, seed=1):
    return DynamicHospitalSimulator(
        base_capacity=list(base or BASE),
        resource_names=NAMES,
        dynamic_cfg=cfg or _cfg(),
        severity_dist=sev or SEV,
        demand_profiles=DEMAND,
        rng=random.Random(seed),
    )


def test_staffing_24_hour_cycle():
    cfg = _cfg()["staffing"]
    hours = [hour_of_day(t) for t in range(24)]
    assert hours == list(range(24))
    assert hour_of_day(24) == 0
    assert day_of_week(0) == 0
    assert day_of_week(24 * 5) == 5


def test_shift_handover_multiplier():
    cfg = _cfg()["staffing"]
    assert is_handover_hour(7, cfg["handover_hours"])
    assert is_handover_hour(19, cfg["handover_hours"])
    assert not is_handover_hour(8, cfg["handover_hours"])
    assert staffing_multiplier(7, cfg) == cfg["handover_multiplier"]
    assert nurse_capacity(10, 7, cfg) == 8
    assert nurse_capacity(10, 8, cfg) == 10


def test_weekend_multiplier():
    cfg = _cfg()["staffing"]
    saturday = 5 * 24
    assert is_weekend(saturday, cfg["weekend_days"])
    assert abs(staffing_multiplier(saturday, cfg) - 0.90) < 1e-12
    # Weekend handover compounds: 0.80 * 0.90
    sat_handover = saturday + 7
    assert abs(staffing_multiplier(sat_handover, cfg) - 0.72) < 1e-12


def test_dynamic_capacity_reproducible():
    cfg = _cfg()["staffing"]
    c0 = capacity_at_time(BASE, NAMES, 0, cfg)
    c7 = capacity_at_time(BASE, NAMES, 7, cfg)
    assert c0[3] == 10
    assert c7[3] == 8
    assert c0[0] == c7[0] == BASE[0]
    assert capacity_at_time(BASE, NAMES, 7, cfg) == c7


def test_resource_conservation_every_timestep():
    sim = _sim(_cfg(arrivals_per_step=1, horizon_hours=16), seed=3)
    sim.run(16)
    for snap in sim.history:
        for j in range(5):
            assert snap["C"][j] == snap["W"][j] + snap["A_total"][j]
            assert snap["W"][j] >= 0
        sim.engine.validate_invariants()


def test_los_updates_and_completion():
    sim = _sim(_cfg())
    p = sim.create_arrival(severity="Mild", los=3)
    sim._try_admissions()
    assert p.current_state == "WARD"
    assert p.remaining_time == 3
    sim.step()
    sim.step()
    sim.step()
    assert p.current_state == "COMPLETED"
    assert p.patient_id not in sim.engine.patient_ids


def test_treatment_bundle_all_or_nothing():
    req = TreatmentRequirement("ICU", "ICU", (1, 4, 1, 2, 0))
    assert req.satisfiable([1, 4, 1, 2, 0]) is True
    assert req.satisfiable([1, 3, 1, 2, 0]) is False
    assert req.unsatisfied([1, 3, 1, 2, 0]) == [1]


def test_icu_bundle_blocked_goes_to_overflow_not_collapse():
    base = [0, 40, 0, 10, 20]
    sim = _sim(_cfg(), base=base)
    p = sim.create_arrival(severity="Critical", los=10)
    sim._try_admissions()
    assert p.current_state == "ED_OVERFLOW"
    safe, _, _ = sim.engine.is_safe()
    assert safe is True
    assert sim.state_counts()["ED_OVERFLOW"] == 1


def test_overflow_does_not_equal_system_collapse():
    sim = _sim(_cfg())
    for _ in range(20):
        sim.create_arrival(severity="Mild", los=40)
    sim._try_admissions()
    overflowed = sim.state_counts()["ED_OVERFLOW"]
    ward = sim.state_counts()["WARD"]
    assert overflowed > 0
    assert ward > 0
    safe, _, _ = sim.engine.is_safe()
    assert safe is True


def test_degradation_on_overflow():
    sim = _sim(_cfg(degradation={"rate_per_hour": 0.10}), base=[0, 40, 0, 10, 20])
    p = sim.create_arrival(severity="Critical", los=10)
    sim._try_admissions()
    assert p.current_state == "ED_OVERFLOW"
    start = p.acuity
    sim.step()
    sim.step()
    assert p.overflow_duration == 2
    assert abs(p.acuity - (start + 0.20)) < 1e-9


def test_fatigue_trigger():
    sim = _sim(_cfg(fatigue={
        "utilization_threshold": 0.50,
        "consecutive_hours": 3,
        "recovery_hours": 2,
        "delay_factor_alpha": 0.15,
    }))
    for _ in range(8):
        sim.create_arrival(severity="Mild", los=40)
    sim._try_admissions()
    util = sim.history[-1]["nurse_utilization"] if sim.history else (
        sim.engine.allocated_totals()[3] / sim.engine.total[3]
    )
    assert util > 0.50
    remaining_before = [p.remaining_time for p in sim._in_care()]
    for _ in range(3):
        sim.step()
    assert sim.fatigue.state == "fatigued"
    assert sim.fatigue.fatigue_events == 1
    assert sim.fatigue.fatigue_start_time is not None


def test_fatigue_extends_los():
    sim = _sim(_cfg(fatigue={
        "utilization_threshold": 0.50,
        "consecutive_hours": 2,
        "recovery_hours": 2,
        "delay_factor_alpha": 0.15,
    }))
    for _ in range(8):
        sim.create_arrival(severity="Mild", los=40)
    sim._try_admissions()
    remaining_before = min(p.remaining_time for p in sim._in_care())
    sim.step()
    sim.step()
    assert sim.fatigue.state == "fatigued"
    in_care = sim._in_care()
    assert in_care
    assert any(p.fatigue_los_applied for p in in_care)
    assert any(p.remaining_time > remaining_before * 0.9 for p in in_care)


def test_fatigue_recovery():
    sim = _sim(_cfg(fatigue={
        "utilization_threshold": 0.50,
        "consecutive_hours": 2,
        "recovery_hours": 2,
        "delay_factor_alpha": 0.15,
    }))
    patients = [sim.create_arrival(severity="Mild", los=80) for _ in range(8)]
    sim._try_admissions()
    sim.step()
    sim.step()
    assert sim.fatigue.state == "fatigued"
    for p in list(sim._in_care()):
        sim._complete_patient(p)
    sim.step()
    sim.step()
    assert sim.fatigue.state == "normal"


def test_triage_priority_order():
    assert triage_priority("Critical") < triage_priority("Mild")
    sim = _sim(_cfg())
    mild = sim.create_arrival(severity="Mild", los=10)
    crit = sim.create_arrival(severity="Critical", los=10)
    waiting = sim._waiting()
    assert waiting[0].patient_id == crit.patient_id
    assert waiting[1].patient_id == mild.patient_id


def test_triage_affects_admission():
    # One ICU slot: later Critical should take it before an earlier Severe if we
    # admit after both have arrived. Both need ICU bundle.
    sim = _sim(_cfg(), base=[1, 40, 1, 10, 20])
    severe = sim.create_arrival(severity="Severe", los=20)
    crit = sim.create_arrival(severity="Critical", los=20)
    sim._try_admissions()
    assert crit.current_state == "ICU"
    assert severe.current_state == "ED_OVERFLOW"


def test_capacity_drop_overflows_lowest_priority():
    sim = _sim(_cfg())
    for _ in range(8):
        sim.create_arrival(severity="Mild", los=40)
    sim._try_admissions()
    allocated_nurses = sim.engine.allocated_totals()[3]
    assert allocated_nurses >= 8
    # Force a staffing drop by jumping to handover with patients holding 8 nurses
    # while handover capacity is 8 if base is 10... use smaller drop via config.
    sim.cfg["staffing"]["handover_multiplier"] = 0.5
    sim.t = 6
    sim.step()  # t=7 handover, nurses -> round(10*0.5)=5
    assert sim.engine.total[3] == 5
    assert sim.engine.allocated_totals()[3] <= 5
    assert sim.state_counts()["ED_OVERFLOW"] > 0
    sim.engine.validate_invariants()


def test_banker_semantics_remain_distinct():
    sim = _sim(_cfg(arrivals_per_step=1), seed=9)
    result = sim.run(12)
    assert "banker_unsafe_timesteps" in result["secondary_metrics"]
    last = result["last_snapshot"]
    assert "banker_safe" in last
    assert last["banker_safe"] in (True, False)


def test_pathways_load_from_config():
    pathways = load_pathways(_cfg(), 5)
    assert pathways["ICU"].required[0] == 1
    assert pathways["WARD"].required[0] == 0
    assert pathways["WARD"].target_state == "WARD"
