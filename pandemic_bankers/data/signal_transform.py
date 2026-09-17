"""
Epidemiological signal → simulation workload.

X = latest-available public smoothed case count (not hospital occupancy).
f(X) = clip(X / X_ref, f_min, f_max)

X_ref, f_min, f_max are MODEL ASSUMPTIONS (normalization and bounds),
not empirically identified hospital parameters. f is non-decreasing in X
before clipping; clipping saturates at the bounds.
"""

from __future__ import annotations

# MODEL ASSUMPTION: reference level for dimensionless scaling.
REFERENCE_CASES = 50_000.0
CLIP_MIN = 0.5
CLIP_MAX = 3.0


def epidemiological_workload_factor(
    x: float,
    reference: float = REFERENCE_CASES,
    clip_min: float = CLIP_MIN,
    clip_max: float = CLIP_MAX,
) -> float:
    if reference <= 0:
        raise ValueError("reference must be positive.")
    raw = float(x) / float(reference)
    return max(clip_min, min(clip_max, raw))


def transformation_record() -> dict:
    return {
        "formula": "f(X) = clip(X / X_ref, f_min, f_max)",
        "X": "14-day mean of global new_cases_smoothed (OWID), when available",
        "X_ref": REFERENCE_CASES,
        "f_min": CLIP_MIN,
        "f_max": CLIP_MAX,
        "classification": "MODEL_ASSUMPTION",
        "note": (
            "X_ref and clip bounds are normalization choices, not hospital truth. "
            "N' = clip(round(N * f(X)), 5, 200) scales the Monte Carlo patient ceiling only."
        ),
    }
