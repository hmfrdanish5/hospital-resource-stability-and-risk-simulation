"""Request parsing for the interactive Monte Carlo experiment (no new estimators)."""

from __future__ import annotations

from data.sampling import demand_fn_for_mode

MODEL_LABELS = {
    "A": "A — Independent synthetic demand",
    "B": "B — Severity-conditioned demand",
    "C": "C — Same static demand as B (not a calibrated collapse model)",
}

MIN_N, MAX_N = 1, 200
MIN_TRIALS, MAX_TRIALS = 1, 200
MAX_PLANNED_TRIALS = 24_000


def validate_experiment_params(
    min_patients: int,
    max_patients: int,
    trials_per_n: int,
    model: str,
    seed: int,
) -> None:
    if model not in MODEL_LABELS:
        raise ValueError("model must be A, B, or C.")
    if min_patients < MIN_N or max_patients > MAX_N:
        raise ValueError(f"Patient load must be between {MIN_N} and {MAX_N}.")
    if max_patients < min_patients:
        raise ValueError("Maximum patient load must be >= minimum.")
    if trials_per_n < MIN_TRIALS or trials_per_n > MAX_TRIALS:
        raise ValueError(f"Trials per patient count must be between {MIN_TRIALS} and {MAX_TRIALS}.")
    planned = (max_patients - min_patients + 1) * trials_per_n
    if planned > MAX_PLANNED_TRIALS:
        raise ValueError(
            f"Experiment is too large ({planned} trials). "
            f"Reduce range or trials (limit {MAX_PLANNED_TRIALS})."
        )
    if not isinstance(seed, int):
        raise ValueError("seed must be an integer.")


def demand_fn_for_experiment(model: str, demand_profiles: dict, p_icu_severe: float):
    return demand_fn_for_mode(model, demand_profiles, p_icu_severe)


def progress_batch_size(trials_per_n: int) -> int:
    """How often to emit a progress event. Does not change trial seeds."""
    if trials_per_n <= 5:
        return 1
    return min(10, max(5, trials_per_n // 10))
