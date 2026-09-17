"""
Discrete-time hospital capacity model (Phase 2).

All staffing multipliers and LOS bounds are MODEL ASSUMPTIONS / sensitivity
parameters unless an empirical source is attached. They are not medical facts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


PARAMETER_STATUS = (
    "MODEL ASSUMPTIONS: staffing multipliers, LOS ranges, fatigue thresholds, "
    "and degradation rates are configurable sensitivity parameters, not measured "
    "clinical facts."
)

# t = 0 is Monday 00:00 under this calendar convention (model assumption).
WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


DEFAULT_DYNAMIC_MODEL: dict[str, Any] = {
    "parameter_status": PARAMETER_STATUS,
    "dt_hours": 1,
    "horizon_hours": 48,
    "arrivals_per_step": 2,
    "staffing": {
        "resource_name": "Nurses",
        "normal_multiplier": 1.0,
        "handover_multiplier": 0.80,
        "weekend_multiplier": 0.90,
        "handover_hours": [7, 19],
        "weekend_days": [5, 6],
    },
    "los_hours": {
        "Mild": {"min": 4, "max": 12},
        "Moderate": {"min": 8, "max": 24},
        "Severe": {"min": 24, "max": 48},
        "Critical": {"min": 48, "max": 96},
    },
    "fatigue": {
        "utilization_threshold": 0.80,
        "consecutive_hours": 4,
        "recovery_hours": 2,
        "delay_factor_alpha": 0.15,
    },
    "degradation": {
        "rate_per_hour": 0.05,
    },
    "treatment_pathways": {
        "severity_pathway": {
            "Mild": "WARD",
            "Moderate": "WARD",
            "Severe": "ICU",
            "Critical": "ICU",
        },
        "WARD": {"target_state": "WARD", "required": [0, 1, 0, 1, 0]},
        "ICU": {"target_state": "ICU", "required": [1, 4, 1, 2, 0]},
    },
}


def merge_dynamic_config(raw: dict | None) -> dict[str, Any]:
    """Shallow-merge user config onto defaults (nested dicts overwritten by key)."""
    cfg = _deep_merge(DEFAULT_DYNAMIC_MODEL, raw or {})
    if int(cfg["dt_hours"]) <= 0:
        raise ValueError("dt_hours must be a positive integer.")
    if int(cfg["horizon_hours"]) < 1:
        raise ValueError("horizon_hours must be >= 1.")
    return cfg


def _deep_merge(base: dict, overlay: dict) -> dict:
    out = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def hour_of_day(t: int, dt_hours: int = 1) -> int:
    """Hour in 0..23 from elapsed hours t (t measured in hours)."""
    return int(t) % 24


def day_of_week(t: int) -> int:
    """0=Monday ... 6=Sunday from elapsed hours t. Model calendar convention."""
    return (int(t) // 24) % 7


def is_handover_hour(t: int, handover_hours: list[int]) -> bool:
    return hour_of_day(t) in set(int(h) for h in handover_hours)


def is_weekend(t: int, weekend_days: list[int]) -> bool:
    return day_of_week(t) in set(int(d) for d in weekend_days)


STAFFING_OVERRIDE_KEYS = {
    "normal_staffing_multiplier": "normal_multiplier",
    "handover_staffing_multiplier": "handover_multiplier",
    "weekend_staffing_multiplier": "weekend_multiplier",
}
STAFFING_MULT_MIN = 0.0
STAFFING_MULT_MAX = 3.0


def apply_staffing_overrides(staffing_cfg: dict, overrides: dict | None) -> dict:
    """
    Copy staffing_cfg and apply optional per-run UI overrides.

    Request keys use the *_staffing_multiplier names; internal config uses
    normal_multiplier / handover_multiplier / weekend_multiplier.
    """
    out = dict(staffing_cfg)
    if not overrides:
        return out
    for req_key, cfg_key in STAFFING_OVERRIDE_KEYS.items():
        if req_key not in overrides:
            continue
        raw = overrides[req_key]
        try:
            val = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{req_key} must be a number.")
        if val < STAFFING_MULT_MIN or val > STAFFING_MULT_MAX:
            raise ValueError(
                f"{req_key} must be between {STAFFING_MULT_MIN} and {STAFFING_MULT_MAX}."
            )
        out[cfg_key] = val
    return out


def staffing_multiplier(t: int, staffing_cfg: dict) -> float:
    """
    m(t) = m_normal * m_shift(t) * m_weekend(t)

    m_normal = normal_multiplier (baseline scale; default 1.0).
    m_shift = handover_multiplier during configured handover hours, else 1.
    m_weekend = weekend_multiplier on configured weekend days, else 1.

    Composition is a model assumption so weekend handovers compound.
    """
    m_normal = float(staffing_cfg.get("normal_multiplier", 1.0))
    m_shift = float(staffing_cfg["handover_multiplier"]) if is_handover_hour(
        t, staffing_cfg["handover_hours"]
    ) else 1.0
    m_weekend = float(staffing_cfg["weekend_multiplier"]) if is_weekend(
        t, staffing_cfg["weekend_days"]
    ) else 1.0
    return m_normal * m_shift * m_weekend


def nurse_capacity(base_nurses: int, t: int, staffing_cfg: dict) -> int:
    """NurseCapacity(t) = round(Base * m(t)), floored at 0."""
    m = staffing_multiplier(t, staffing_cfg)
    return max(0, int(round(base_nurses * m)))


def capacity_at_time(
    base_capacity: list[int],
    resource_names: list[str],
    t: int,
    staffing_cfg: dict,
) -> list[int]:
    """C(t): only the named staffing resource varies; others stay at base."""
    c = list(base_capacity)
    name = staffing_cfg["resource_name"]
    if name not in resource_names:
        raise ValueError(f"Staffing resource '{name}' is not in resource_names.")
    idx = resource_names.index(name)
    c[idx] = nurse_capacity(base_capacity[idx], t, staffing_cfg)
    return c


@dataclass(frozen=True)
class ClockLabel:
    t: int
    hour: int
    day: int
    day_name: str
    handover: bool
    weekend: bool
    staffing_multiplier: float


def describe_time(t: int, staffing_cfg: dict) -> ClockLabel:
    return ClockLabel(
        t=t,
        hour=hour_of_day(t),
        day=day_of_week(t),
        day_name=WEEKDAY_NAMES[day_of_week(t)],
        handover=is_handover_hour(t, staffing_cfg["handover_hours"]),
        weekend=is_weekend(t, staffing_cfg["weekend_days"]),
        staffing_multiplier=staffing_multiplier(t, staffing_cfg),
    )
