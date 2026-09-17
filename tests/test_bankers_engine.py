"""Tests for Banker's Algorithm engine (Phase 1)."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pandemic_bankers"))

from core.bankers_engine import BankersEngine, compute_deficit, need_le_work


# ── A. Known SAFE state ─────────────────────────────────────────────

def test_known_safe_state():
    engine = BankersEngine([10, 5, 7], ["A", "B", "C"])
    engine.add_patient("P0", [0, 1, 0], [7, 5, 3])
    engine.add_patient("P1", [2, 0, 0], [3, 2, 2])
    engine.add_patient("P2", [3, 0, 2], [9, 0, 2])
    safe, seq, blocking = engine.is_safe()
    assert safe is True
    assert blocking is None
    assert len(seq) == 3
    assert set(seq) == {"P0", "P1", "P2"}


# ── B. Known UNSAFE state ───────────────────────────────────────────

def test_known_unsafe_state():
    # Classic textbook unsafe state (Silberschatz); Available = [3, 3, 2].
    engine = BankersEngine([8, 4, 4], ["A", "B", "C"])
    engine.add_patient("P0", [0, 1, 0], [7, 5, 3])
    engine.add_patient("P1", [2, 0, 0], [3, 2, 2])
    engine.add_patient("P2", [3, 0, 2], [9, 0, 2])
    safe, seq, blocking = engine.is_safe()
    assert safe is False
    assert seq == []
    assert blocking is not None


# ── C. Allocation == max demand (Need = 0) ──────────────────────────

def test_allocation_equals_max():
    engine = BankersEngine([5, 5], ["X", "Y"])
    engine.add_patient("P1", [2, 3], [2, 3])
    need = engine.need_matrix()
    assert need["P1"] == [0, 0]
    safe, seq, _ = engine.is_safe()
    assert safe is True
    assert seq == ["P1"]


# ── D. Zero allocation ──────────────────────────────────────────────

def test_zero_allocation():
    engine = BankersEngine([4, 4], ["A", "B"])
    engine.add_patient("P1", [0, 0], [2, 2])
    engine.add_patient("P2", [0, 0], [1, 3])
    need = engine.need_matrix()
    assert need["P1"] == [2, 2]
    assert need["P2"] == [1, 3]
    engine.validate_invariants()


# ── E. Zero available resources ─────────────────────────────────────

def test_zero_available_resources():
    # All units allocated, but Need = 0 so processes can still complete.
    engine = BankersEngine([4, 4], ["A", "B"])
    engine.add_patient("P1", [2, 2], [2, 2])
    engine.add_patient("P2", [2, 2], [2, 2])
    assert engine.snapshot()["available"] == [0, 0]
    safe, seq, _ = engine.is_safe()
    assert safe is True
    assert len(seq) == 2


# ── F. Multiple resource types ──────────────────────────────────────

def test_multiple_resource_types():
    engine = BankersEngine([10, 8, 6, 4], ["R0", "R1", "R2", "R3"])
    engine.add_patient("P1", [1, 2, 1, 0], [3, 4, 2, 1])
    engine.add_patient("P2", [2, 1, 0, 1], [4, 3, 1, 2])
    engine.validate_invariants()
    safe, seq, _ = engine.is_safe()
    assert safe is True
    assert len(seq) == 2


# ── G. Invalid Allocation > Max ─────────────────────────────────────

def test_rejects_allocation_exceeds_max():
    engine = BankersEngine([10], ["A"])
    try:
        engine.add_patient("P1", [5], [3])
        assert False, "Should have raised"
    except ValueError:
        pass


# ── H. Invalid negative Allocation ────────────────────────────────

def test_rejects_negative_allocation():
    engine = BankersEngine([10], ["A"])
    try:
        engine.add_patient("P1", [-1], [3])
        assert False, "Should have raised"
    except ValueError:
        pass


# ── I. Invalid negative Available (over-allocation) ───────────────

def test_rejects_allocation_exceeds_available():
    engine = BankersEngine([2, 2], ["A", "B"])
    engine.add_patient("P1", [1, 1], [2, 2])
    try:
        engine.add_patient("P2", [2, 0], [2, 1])
        assert False, "Should have raised"
    except ValueError:
        pass


# ── J. Resource conservation ────────────────────────────────────────

def test_resource_conservation():
    engine = BankersEngine([10, 8, 6], ["A", "B", "C"])
    engine.add_patient("P1", [2, 1, 1], [4, 3, 3])
    engine.add_patient("P2", [3, 2, 0], [5, 4, 2])
    engine.validate_invariants()
    snap = engine.snapshot()
    for j, name in enumerate(snap["resource_names"]):
        allocated = sum(snap["allocation"][p][j] for p in snap["allocation"])
        assert snap["available"][j] + allocated == snap["total"][j]
        assert snap["available"][j] >= 0


def test_need_non_negative():
    engine = BankersEngine([5, 5], ["X", "Y"])
    engine.add_patient("P1", [1, 2], [3, 4])
    need = engine.need_matrix()
    for pid, row in need.items():
        for val in row:
            assert val >= 0


def test_need_le_work_helper():
    assert need_le_work([1, 2], [2, 2]) is True
    assert need_le_work([3, 1], [2, 2]) is False


def test_compute_deficit():
    assert compute_deficit([3, 1], [2, 2]) == [1, 0]
    assert compute_deficit([1, 1], [5, 5]) == [0, 0]


def test_safe_sequence_and_work_updates():
    engine = BankersEngine([5, 10], ["A", "B"])
    engine.add_patient("P1", [1, 2], [2, 4])
    engine.add_patient("P2", [1, 3], [2, 5])
    safe, seq, _, steps, post_mortem = engine.is_safe_with_trace()
    assert safe is True
    assert post_mortem is None
    assert len(seq) == 2
    complete_checks = [s for s in steps if s["action"] == "check" and s["need_le_work"]]
    for step in complete_checks:
        wb = step["work_before"]
        wa = step["work_after"]
        alloc = step["allocation"]
        assert wa == [wb[j] + alloc[j] for j in range(len(wb))]


def test_trace_fields():
    engine = BankersEngine([5, 5], ["A", "B"])
    engine.add_patient("P1", [1, 1], [2, 2])
    _, _, _, steps, _ = engine.is_safe_with_trace()
    check_steps = [s for s in steps if s["action"] == "check"]
    assert check_steps
    s0 = check_steps[0]
    assert "work_before" in s0
    assert "work_after" in s0
    assert "allocation" in s0
    assert "need_le_work" in s0


def test_unsafe_post_mortem():
    engine = BankersEngine([8, 4, 4], ["A", "B", "C"])
    engine.add_patient("P0", [0, 1, 0], [7, 5, 3])
    engine.add_patient("P1", [2, 0, 0], [3, 2, 2])
    engine.add_patient("P2", [3, 0, 2], [9, 0, 2])
    safe, seq, blocking, steps, post_mortem = engine.is_safe_with_trace()
    assert safe is False
    assert seq == []
    assert post_mortem is not None
    assert "remaining_processes" in post_mortem
    assert "final_work" in post_mortem
    assert "deficits_by_process" in post_mortem
    assert "most_constraining_resource" in post_mortem
    assert len(post_mortem["remaining_processes"]) > 0
    unsafe_steps = [s for s in steps if s["action"] == "unsafe"]
    assert unsafe_steps
    assert blocking == post_mortem["most_constraining_resource"]


def test_conservation_violation_is_detected():
    engine = BankersEngine([10, 10], ["A", "B"])
    engine.add_patient("P1", [2, 3], [5, 5])
    engine.available[0] += 1
    try:
        engine.validate_invariants()
        assert False, "Should have raised"
    except ValueError as exc:
        assert "total" in str(exc).lower() or "allocated" in str(exc).lower()


def test_tampered_need_is_detected():
    engine = BankersEngine([10, 10], ["A", "B"])
    engine.add_patient("P1", [2, 3], [5, 5])
    engine._max_demand["P1"][0] = 1
    try:
        engine.validate_invariants()
        assert False, "Should have raised"
    except ValueError:
        pass


def test_set_total_resources_preserves_allocation():
    engine = BankersEngine([10, 10], ["A", "B"])
    engine.add_patient("P1", [2, 3], [5, 5])
    engine.set_total_resources([12, 10])
    assert engine.total == [12, 10]
    assert engine.available == [10, 7]
    assert engine.allocated_totals() == [2, 3]
    engine.validate_invariants()


def test_set_total_rejects_below_allocated():
    engine = BankersEngine([10, 10], ["A", "B"])
    engine.add_patient("P1", [4, 1], [5, 5])
    try:
        engine.set_total_resources([3, 10])
        assert False, "Should have raised"
    except ValueError:
        pass
    assert engine.snapshot()["allocation"]["P1"] == [4, 1]

