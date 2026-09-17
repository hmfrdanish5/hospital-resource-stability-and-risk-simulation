"""Labels that must travel with every empirical or calibrated quantity."""

from __future__ import annotations

from typing import Any

REAL_OBSERVATION = "REAL_OBSERVATION"
MODEL_ASSUMPTION = "MODEL_ASSUMPTION"
DERIVED_PARAMETER = "DERIVED_PARAMETER"
SIMULATED_VALUE = "SIMULATED_VALUE"

CURRENT_EXTERNAL = "CURRENT_EXTERNAL"
CACHED_EMPIRICAL = "CACHED_EMPIRICAL"
SYNTHETIC_FALLBACK = "SYNTHETIC_FALLBACK"

VALID = {REAL_OBSERVATION, MODEL_ASSUMPTION, DERIVED_PARAMETER, SIMULATED_VALUE}
AVAILABILITY = {CURRENT_EXTERNAL, CACHED_EMPIRICAL, SYNTHETIC_FALLBACK}


def tagged(value: Any, classification: str, source: str, **meta: Any) -> dict[str, Any]:
    if classification not in VALID:
        raise ValueError(f"Unknown classification: {classification}")
    out = {
        "value": value,
        "classification": classification,
        "source": source,
    }
    out.update(meta)
    return out
