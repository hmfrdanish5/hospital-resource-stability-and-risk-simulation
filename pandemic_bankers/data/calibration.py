"""
Calibrate arrival, LOS, and aggregate ICU-occupancy parameters.

Raw series stay in ingest payloads. This module writes DERIVED parameters only.
"""

from __future__ import annotations

import json
import os
import random
from datetime import datetime
from typing import Any

from data.distributions import (
    bootstrap_mean_ci,
    compare_count_models,
    fit_los_from_quantiles,
    pearson_corr,
)
from data.pipeline import CACHE_DIR, ingest_hospital_series, load_literature_los, write_cache
from data.provenance import (
    DERIVED_PARAMETER,
    MODEL_ASSUMPTION,
    REAL_OBSERVATION,
    SIMULATED_VALUE,
    SYNTHETIC_FALLBACK,
    tagged,
)


def _series(rows: list[dict], key: str) -> list[float]:
    return [float(r[key]) for r in rows if r.get(key) is not None]


def weekday_relative_rates(rows: list[dict], key: str = "newAdmissions") -> dict:
    """
    Relative weekday intensities r_d = mean_d / grand_mean.

    Monday = 0 … Sunday = 6, matching the Phase 2 calendar (t=0 is Monday 00:00).
    Implemented because dated daily counts exist. Month/outbreak splits are not
    used as λ(t) factors unless a series actually supports them.
    """
    buckets: list[list[float]] = [[] for _ in range(7)]
    for row in rows:
        val = row.get(key)
        if val is None:
            continue
        try:
            day = datetime.strptime(str(row.get("date", ""))[:10], "%Y-%m-%d")
        except ValueError:
            continue
        buckets[day.weekday()].append(float(val))
    means: list[float | None] = []
    for vals in buckets:
        means.append((sum(vals) / len(vals)) if vals else None)
    observed = [m for m in means if m is not None]
    grand = (sum(observed) / len(observed)) if observed else 1.0
    if grand <= 0:
        relatives = [1.0] * 7
    else:
        relatives = [(m / grand if m is not None else 1.0) for m in means]
    names = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    return {
        "weekday_names": list(names),
        "weekday_means": means,
        "relative_rates": relatives,
        "grand_mean": grand,
        "n_by_weekday": [len(b) for b in buckets],
        "weekend_vs_weekday": {
            "weekday_mean": _avg([means[i] for i in range(5) if means[i] is not None]),
            "weekend_mean": _avg([means[i] for i in (5, 6) if means[i] is not None]),
        },
        "note": (
            "r_d = mean(X | weekday=d) / mean(X). Hospital intensity uses "
            "λ(t) = λ_0 · r_{dow(t)} where λ_0 is the configured hospital-scale "
            "hourly mean (MODEL_ASSUMPTION). National daily mean is not λ_0."
        ),
    }


def _avg(xs: list[float]) -> float | None:
    if not xs:
        return None
    return sum(xs) / len(xs)


def _los_summary(fit: dict) -> dict:
    return {
        "method": "quantile-based calibration (distribution reconstruction from published quantiles)",
        "not_mle": True,
        "comparison_metric": fit.get("comparison_metric"),
        "observed_quantiles": fit.get("target_quantiles"),
        "candidates": [
            {
                "family": c["family"],
                "sse": c["sse"],
                "reconstructed_quantiles": c["predicted"],
                "params": c["params"],
            }
            for c in fit.get("candidates", [])
        ],
        "selected_family": fit.get("chosen_family"),
        "reconstructed_quantiles": fit.get("chosen", {}).get("predicted"),
        "reconstruction_error_sse": fit.get("chosen", {}).get("sse"),
        "gamma_uses_wilson_hilferty": True,
    }


def _conditional_mean(pairs: list[tuple[float, float]]) -> dict | None:
    if not pairs:
        return None
    hs = [a for a, _ in pairs]
    median_h = sorted(hs)[len(hs) // 2]
    high = [b for a, b in pairs if a >= median_h]
    low = [b for a, b in pairs if a < median_h]
    return {
        "split": "hospital occupancy median",
        "mean_mv_when_hosp_high": sum(high) / len(high) if high else None,
        "mean_mv_when_hosp_low": sum(low) / len(low) if low else None,
    }


def calibrate(prefer_live: bool = True, rng: random.Random | None = None) -> dict[str, Any]:
    rng = rng or random.Random(42)
    series = ingest_hospital_series(prefer_live=prefer_live)
    los_lit = load_literature_los()

    admissions = [int(round(x)) for x in _series(series["rows"], "newAdmissions")]
    pairs = [
        (float(r["hospitalCases"]), float(r["covidOccupiedMVBeds"]))
        for r in series["rows"]
        if r.get("hospitalCases") not in (None, 0) and r.get("covidOccupiedMVBeds") is not None
    ]
    p_icu_vals = [b / a for a, b in pairs]
    p_icu = sum(p_icu_vals) / len(p_icu_vals) if p_icu_vals else None
    corr_h_mv = pearson_corr([a for a, _ in pairs], [b for _, b in pairs]) if pairs else float("nan")

    arrival_fit = compare_count_models(admissions) if admissions else None
    weekday = weekday_relative_rates(series["rows"], "newAdmissions")
    mean_daily, mean_lo, mean_hi = (
        bootstrap_mean_ci(admissions, rng) if admissions else (0.0, 0.0, 0.0)
    )
    lambda_hourly = mean_daily / 24.0

    ward_fit = fit_los_from_quantiles(
        los_lit["hospital_los_days"]["q25"],
        los_lit["hospital_los_days"]["median"],
        los_lit["hospital_los_days"]["q75"],
    )
    icu_fit = fit_los_from_quantiles(
        los_lit["icu_los_days"]["q25"],
        los_lit["icu_los_days"]["median"],
        los_lit["icu_los_days"]["q75"],
    )

    copula_decision = {
        "used": False,
        "reason": (
            "Copula modeling was considered but not implemented because available data "
            "does not support reliable estimation of patient-level joint dependence. "
            "National hospital vs mechanical-ventilation occupancy is an aggregate "
            "time-series relationship, not within-patient (ICU, ventilator, oxygen) triples. "
            "Severity-conditioned sampling and treatment bundles encode the implemented dependence."
        ),
        "aggregate_dependence_observed": bool(pairs) and abs(corr_h_mv) > 0.3,
        "pearson_hospital_vs_mv": corr_h_mv,
    }

    classification_arrivals = (
        DERIVED_PARAMETER if series.get("classification") == REAL_OBSERVATION else SIMULATED_VALUE
    )
    calibration = {
        "calibrated_at": series.get("retrieved_at"),
        "series_provenance": {
            "source_id": series.get("source_id"),
            "classification": series.get("classification"),
            "availability_status": series.get("availability_status", SYNTHETIC_FALLBACK),
            "coverage": series.get("coverage"),
            "current_vs_historical": series.get("current_vs_historical"),
            "n_rows": series.get("n_rows"),
            "cache_hit": series.get("cache_hit", False),
            "fallback_errors": series.get("fallback_errors"),
            "label": (
                "Latest available public epidemiological / hospital-activity signal "
                "when empirical; otherwise a labeled synthetic fixture. "
                "Not real-time occupancy of a named hospital."
            ),
        },
        "los_provenance": {
            "classification": REAL_OBSERVATION,
            "observation_type": "published_summary_statistics",
            "citation": los_lit["citation"],
            "doi": los_lit["doi"],
            "access_date": los_lit["access_date"],
        },
        "parameters": {
            "arrival_rate_daily": tagged(
                mean_daily,
                classification_arrivals,
                series.get("source_id"),
                bootstrap_ci95=[mean_lo, mean_hi],
                uncertainty=(
                    "IID percentile bootstrap of the daily-count mean (observations "
                    "resampled independently). If the series is temporally dependent, "
                    "this interval is not a time-series-valid CI. Parameter uncertainty, "
                    "not real-world forecast error."
                ),
                bootstrap_method="iid_percentile",
            ),
            "arrival_rate_hourly": tagged(
                lambda_hourly,
                DERIVED_PARAMETER,
                series.get("source_id"),
                transformation="daily_mean / 24",
                note="Maps a daily national (or fixture) count onto dt=1 hour. Not this hospital's arrival process.",
            ),
            "arrival_model": tagged(
                arrival_fit["chosen_family"] if arrival_fit else "poisson",
                DERIVED_PARAMETER,
                "count_model_comparison",
                fit=arrival_fit,
            ),
            "weekday_relative_rates": tagged(
                weekday,
                DERIVED_PARAMETER if series.get("classification") == REAL_OBSERVATION else SIMULATED_VALUE,
                series.get("source_id"),
                transformation="r_d = mean(X|dow=d) / mean(X)",
            ),
            "p_icu_given_hospital_occupancy": tagged(
                p_icu,
                DERIVED_PARAMETER if p_icu is not None else MODEL_ASSUMPTION,
                series.get("source_id"),
                note=(
                    "Mean of (MV or ICU occupancy / hospital occupancy) on days with hospitalCases>0. "
                    "This is an occupancy ratio, not an identified individual-level P(ICU | admitted)."
                ),
            ),
            "los_ward_days": tagged(
                ward_fit["chosen"]["params"],
                DERIVED_PARAMETER,
                "rees_2020_los",
                family=ward_fit["chosen_family"],
                fit=ward_fit,
            ),
            "los_icu_days": tagged(
                icu_fit["chosen"]["params"],
                DERIVED_PARAMETER,
                "rees_2020_los",
                family=icu_fit["chosen_family"],
                fit=icu_fit,
            ),
        },
        "dependence": {
            "n_paired_days": len(pairs),
            "pearson_hospital_vs_mv": tagged(
                corr_h_mv,
                REAL_OBSERVATION if series.get("classification") == REAL_OBSERVATION else SIMULATED_VALUE,
                series.get("source_id"),
                note="Aggregate time-series correlation, not within-patient resource correlation.",
            ),
            "conditional_mean_mv_given_high_hosp": tagged(
                _conditional_mean(pairs),
                DERIVED_PARAMETER,
                series.get("source_id"),
            ),
            "copula": copula_decision,
        },
        "uncertainty_labels": {
            "simulation_uncertainty": (
                "Monte Carlo Wilson intervals describe binomial sampling error under a fixed model."
            ),
            "parameter_uncertainty": (
                "Bootstrap CI on arrival mean and +/- percent sensitivity ranges describe parameter uncertainty."
            ),
            "not_real_world_ci": (
                "Neither interval is a confidence interval for a named hospital's future collapse risk."
            ),
            "bootstrap": (
                "Arrival-mean interval is an IID percentile bootstrap. It does not "
                "preserve time-series dependence; block bootstrap is not used."
            ),
        },
        "calibration_summary": {
            "availability_status": series.get("availability_status", SYNTHETIC_FALLBACK),
            "data_source": series.get("source_id"),
            "metric": "daily newAdmissions (or weekly_hosp_admissions/7 proxy)",
            "geographic_scope": (
                "UK national overview or OWID GBR aggregates when empirical; "
                "not this model's five-resource hospital."
            ),
            "timestamp_access": series.get("retrieved_at"),
            "coverage": series.get("coverage"),
            "cached_or_historical": series.get("current_vs_historical"),
            "arrival_model": arrival_fit["chosen_family"] if arrival_fit else None,
            "arrival_mean": arrival_fit["mean"] if arrival_fit else None,
            "arrival_variance": arrival_fit["variance"] if arrival_fit else None,
            "dispersion": arrival_fit["dispersion"] if arrival_fit else None,
            "dispersion_interpretation": (
                "D≈1 Poisson-like; D>1 overdispersion; D<1 underdispersion. Diagnostic only."
            ),
            "nbinom_parameterization": (
                arrival_fit.get("nbinom_parameterization") if arrival_fit else None
            ),
            "selection_reason": arrival_fit.get("selection_rule") if arrival_fit else None,
            "los_method": "quantile-based calibration from published Q25/Q50/Q75 (not MLE)",
            "los_ward": _los_summary(ward_fit),
            "los_icu": _los_summary(icu_fit),
            "hospital_lambda_0": {
                "classification": MODEL_ASSUMPTION,
                "note": (
                    "Dynamic Model C uses configured arrivals_per_step as λ_0, "
                    "scaled by weekday relative rates. National daily_mean/24 is "
                    "exposed but is not this hospital's arrival intensity."
                ),
            },
            "weekday_relative_rates": weekday["relative_rates"],
        },
    }
    write_cache("calibration.json", calibration)
    return calibration


def load_or_calibrate(prefer_live: bool = True) -> dict:
    path = os.path.join(CACHE_DIR, "calibration.json")
    if os.path.isfile(path) and not prefer_live:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return calibrate(prefer_live=prefer_live)
