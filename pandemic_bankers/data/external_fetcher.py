"""
External epidemiological data fetcher.

Fetches publicly available COVID-19 case data as an EXTERNAL DEMAND SIGNAL.
This is NOT live hospital ICU occupancy data.

Primary source: Our World in Data COVID-19 dataset (CC-BY 4.0)
https://github.com/owid/covid-19-data

Policy (reproducibility):
  prefer_live=False (default): cached validated snapshot → labeled synthetic fallback.
  prefer_live=True: live HTTP fetch → write cache → on failure cached → fallback.

Never silently substitute unlabeled synthetic data for a failed live fetch.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from data.pipeline import read_cache, write_cache
from data.signal_transform import (
    CLIP_MAX,
    CLIP_MIN,
    REFERENCE_CASES,
    epidemiological_workload_factor,
    transformation_record,
)

logger = logging.getLogger(__name__)

OWID_CSV_URL = (
    "https://raw.githubusercontent.com/owid/covid-19-data/master/"
    "public/data/owid-covid-data.csv"
)
SOURCE_NAME = "Our World in Data COVID-19 Dataset"
SOURCE_LICENSE = "CC-BY 4.0"
SOURCE_URL = "https://github.com/owid/covid-19-data"
SOURCE_ID = "owid_covid_global_signal"
METRIC_FIELD = "new_cases_smoothed"
LOOKBACK_DAYS = 14
CACHE_NAME = "external_signal.json"


def _fetch_global_rows(url: str, timeout: int = 20) -> list[dict[str, str]]:
    """Stream CSV and retain only global (OWID_WRL) rows to limit download size."""
    req = Request(url, headers={"User-Agent": "PandemicStabilityLab/1.0 (academic)"})
    with urlopen(req, timeout=timeout) as resp:
        text_stream = io.TextIOWrapper(resp, encoding="utf-8")
        reader = csv.DictReader(text_stream)
        return [row for row in reader if row.get("iso_code") == "OWID_WRL"]


def _enrich_signal(signal: dict[str, Any]) -> dict[str, Any]:
    """Attach export/reproducibility fields used by API responses and experiment metadata."""
    x = signal.get("avg_new_cases_smoothed_14d")
    transform = signal.get("transformation") or transformation_record()
    if isinstance(transform, dict):
        signal.setdefault("external_signal_value", x)
        signal.setdefault("reference_constant", transform.get("X_ref", REFERENCE_CASES))
        signal.setdefault("clip_lower", transform.get("f_min", CLIP_MIN))
        signal.setdefault("clip_upper", transform.get("f_max", CLIP_MAX))
        signal.setdefault("derived_workload_factor", signal.get("workload_factor"))
        signal.setdefault("signal_timestamp", signal.get("last_data_date"))
        signal.setdefault("source_id", SOURCE_ID)
    return signal


def _parse_global_signal(rows: list[dict[str, str]], data_status: str) -> dict[str, Any]:
    """Extract recent global new-case signal from OWID rows."""
    if not rows:
        raise ValueError("No global (OWID_WRL) rows in dataset.")

    global_rows = sorted(rows, key=lambda r: r.get("date", ""))
    recent = global_rows[-LOOKBACK_DAYS:]

    values: list[float] = []
    for row in recent:
        raw = row.get(METRIC_FIELD, "")
        if raw and raw.strip():
            try:
                values.append(float(raw))
            except ValueError:
                continue

    if not values:
        raise ValueError(f"No usable '{METRIC_FIELD}' values in recent data.")

    avg_cases = sum(values) / len(values)
    latest_date = recent[-1].get("date", "unknown")
    workload_factor = epidemiological_workload_factor(avg_cases)
    retrieved_at = datetime.now(timezone.utc).isoformat()

    signal = {
        "source": SOURCE_NAME,
        "source_url": SOURCE_URL,
        "license": SOURCE_LICENSE,
        "metric": METRIC_FIELD,
        "region": "Global (OWID_WRL)",
        "data_type": "latest_available_public_epidemiological_signal",
        "availability_status": data_status,
        "data_status": data_status,
        "last_data_date": latest_date,
        "fetched_at": retrieved_at,
        "signal_retrieval_timestamp": retrieved_at,
        "avg_new_cases_smoothed_14d": avg_cases,
        "external_signal_value": avg_cases,
        "workload_factor": workload_factor,
        "derived_workload_factor": workload_factor,
        "transformation": transformation_record(),
        "reference_constant": REFERENCE_CASES,
        "clip_lower": CLIP_MIN,
        "clip_upper": CLIP_MAX,
        "signal_timestamp": latest_date,
        "source_id": SOURCE_ID,
        "interpretation": (
            "External epidemiological demand signal from global smoothed new-case counts. "
            "Not real-time hospital occupancy and not this facility's census."
        ),
        "available": True,
    }
    if data_status == "LIVE_EXTERNAL":
        signal["reproducibility"] = "NOT_SEED_ONLY"
        signal["reproducibility_note"] = (
            "Live external data was used. Re-run with the recorded signal value and "
            "transformation parameters to reproduce the workload factor; seed alone is insufficient."
        )
    else:
        signal["reproducibility"] = "REPRODUCIBLE_CACHED"
        signal["reproducibility_note"] = (
            "Cached external signal snapshot. Same configuration reproduces the workload factor."
        )
    return signal


def _fallback_signal(reason: str) -> dict[str, Any]:
    retrieved_at = datetime.now(timezone.utc).isoformat()
    return _enrich_signal({
        "source": "Synthetic baseline (external source unavailable)",
        "source_url": SOURCE_URL,
        "license": "N/A",
        "metric": METRIC_FIELD,
        "region": "N/A",
        "data_type": "synthetic_fallback",
        "availability_status": "SYNTHETIC_FALLBACK",
        "data_status": "SYNTHETIC_FALLBACK",
        "last_data_date": None,
        "fetched_at": retrieved_at,
        "signal_retrieval_timestamp": retrieved_at,
        "avg_new_cases_smoothed_14d": None,
        "external_signal_value": None,
        "workload_factor": 1.0,
        "derived_workload_factor": 1.0,
        "transformation": transformation_record(),
        "interpretation": (
            "Neutral workload multiplier (1.0). External epidemiological "
            "data could not be retrieved; simulation uses configured parameters only."
        ),
        "available": False,
        "fallback_reason": reason,
        "reproducibility": "REPRODUCIBLE_FALLBACK",
        "reproducibility_note": "Labeled synthetic fallback (multiplier 1.0).",
        "source_id": SOURCE_ID,
    })


def _from_cache(cached: dict[str, Any]) -> dict[str, Any]:
    out = dict(cached)
    out["cache_hit"] = True
    out["availability_status"] = "CACHED_EMPIRICAL"
    out["data_status"] = "CACHED_EMPIRICAL"
    out["reproducibility"] = "REPRODUCIBLE_CACHED"
    out["reproducibility_note"] = (
        "Cached external signal snapshot. Same configuration reproduces the workload factor."
    )
    return _enrich_signal(out)


def fetch_external_signal(
    prefer_live: bool = False,
    use_cache_fallback: bool = True,
) -> dict[str, Any]:
    """
    Fetch and normalize an external epidemiological demand signal.

    Default (prefer_live=False): use cached validated snapshot, then labeled fallback.
    prefer_live=True: attempt live fetch, cache on success, then cached, then fallback.
    """
    if prefer_live:
        try:
            rows = _fetch_global_rows(OWID_CSV_URL)
            signal = _parse_global_signal(rows, "LIVE_EXTERNAL")
            write_cache(CACHE_NAME, signal)
            return signal
        except (URLError, TimeoutError, ValueError, OSError) as exc:
            logger.warning("Live external data fetch failed: %s", exc)
            cached = read_cache(CACHE_NAME)
            if cached and cached.get("avg_new_cases_smoothed_14d") is not None:
                out = _from_cache(cached)
                out["live_fetch_failed"] = str(exc)
                return out
            if not use_cache_fallback:
                raise
            return _fallback_signal(str(exc))

    cached = read_cache(CACHE_NAME)
    if cached and cached.get("avg_new_cases_smoothed_14d") is not None:
        return _from_cache(cached)

    if not use_cache_fallback:
        raise ValueError("No cached external signal available.")

    return _fallback_signal("no cache and prefer_live=False")


def apply_workload_factor(
    max_patients: int,
    workload_factor: float,
) -> int:
    """Scale simulation patient ceiling by external workload factor."""
    scaled = int(round(max_patients * workload_factor))
    return max(5, min(200, scaled))
