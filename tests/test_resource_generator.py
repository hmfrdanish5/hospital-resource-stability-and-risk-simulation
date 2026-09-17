"""Tests for patient demand vector generation."""

import sys
import os
import random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pandemic_bankers"))

from simulation.resource_generator import generate_patient_demands, validate_patient_vectors, compute_need

DEMAND = {
    "Critical": {"min": [1, 10, 1, 3, 3], "max": [1, 20, 1, 5, 6]},
    "Mild": {"min": [0, 1, 0, 0, 0], "max": [0, 3, 0, 1, 1]},
}


def test_need_never_negative():
    rng = random.Random(42)
    for _ in range(100):
        alloc, max_d = generate_patient_demands("Critical", DEMAND, 5, rng)
        need = compute_need(alloc, max_d)
        assert all(n >= 0 for n in need)


def test_allocation_le_max():
    rng = random.Random(7)
    for _ in range(100):
        alloc, max_d = generate_patient_demands("Mild", DEMAND, 5, rng)
        for j in range(5):
            assert alloc[j] <= max_d[j]


def test_binary_icu_at_most_one():
    rng = random.Random(13)
    for _ in range(50):
        alloc, max_d = generate_patient_demands("Critical", DEMAND, 5, rng)
        assert max_d[0] <= 1
        assert alloc[0] <= 1


def test_validate_rejects_invalid():
    try:
        validate_patient_vectors([5], [3], 1)
        assert False
    except ValueError:
        pass
