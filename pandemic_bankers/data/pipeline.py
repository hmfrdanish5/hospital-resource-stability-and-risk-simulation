"""
Data ingestion: Fetch → Validate → Clean → Normalize → Cache → Calibration inputs.

The simulation never calls an external HTTP API directly. This module is the only
network boundary. On failure it uses on-disk cache, then a labeled synthetic fixture.

Future calibration may pass a validated dataset object into ingest_from_validated_dataset
instead of fetching. Arbitrary user CSV upload is not implemented here.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from data.provenance import (
    CACHED_EMPIRICAL,
    CURRENT_EXTERNAL,
    DERIVED_PARAMETER,
    REAL_OBSERVATION,
    SIMULATED_VALUE,
    SYNTHETIC_FALLBACK,
    tagged,
)

logger = logging.getLogger(__name__)

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(DATA_DIR, "cache")
SOURCES_PATH = os.path.join(DATA_DIR, "data_sources.json")

OWID_CSV_URL = "https://covid.ourworldindata.org/data/owid-covid-data.csv"
OWID_FALLBACK_URL = (
    "https://raw.githubusercontent.com/owid/covid-19-data/master/public/data/owid-covid-data.csv"
)
UKHSA_URL = (
    "https://api.coronavirus.data.gov.uk/v1/data?filters=areaType=overview"
    "&structure=%7B%22date%22:%22date%22,%22newAdmissions%22:%22newAdmissions%22,"
    "%22hospitalCases%22:%22hospitalCases%22,%22covidOccupiedMVBeds%22:%22covidOccupiedMVBeds%22%7D"
)

USER_AGENT = "PandemicStabilityLab/1.0 (academic; Phase3 calibration)"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_source_catalog() -> dict:
    with open(SOURCES_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _http_get(url: str, timeout: int = 25) -> bytes:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _ensure_cache() -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)


def write_cache(name: str, payload: dict) -> str:
    _ensure_cache()
    path = os.path.join(CACHE_DIR, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    return path


def read_cache(name: str) -> dict | None:
    path = os.path.join(CACHE_DIR, name)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _parse_float(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        if raw != raw:  # NaN
            return None
        return float(raw)
    text = str(raw).strip()
    if text == "" or text.lower() in {"na", "nan", "null", "none"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _validate_rows(rows: list[dict], required: list[str]) -> list[dict]:
    cleaned = []
    dropped = 0
    for row in rows:
        if not isinstance(row, dict):
            dropped += 1
            continue
        date = str(row.get("date") or "").strip()
        if len(date) < 8:
            dropped += 1
            continue
        item = {"date": date}
        ok = False
        for key in required:
            val = _parse_float(row.get(key))
            if val is not None and val < 0:
                val = None
            item[key] = val
            if val is not None:
                ok = True
        if ok:
            cleaned.append(item)
        else:
            dropped += 1
    cleaned.sort(key=lambda r: r["date"])
    return cleaned


def fetch_ukhsa_overview(timeout: int = 25) -> dict:
    raw = _http_get(UKHSA_URL, timeout=timeout)
    payload = json.loads(raw.decode("utf-8"))
    records = payload.get("data") or []
    rows = _validate_rows(
        records, ["newAdmissions", "hospitalCases", "covidOccupiedMVBeds"]
    )
    if len(rows) < 10:
        raise ValueError("UKHSA payload had too few usable rows.")
    return {
        "source_id": "ukhsa_coronavirus_api",
        "classification": REAL_OBSERVATION,
        "availability_status": CURRENT_EXTERNAL,
        "retrieved_at": _now(),
        "n_rows": len(rows),
        "coverage": {"start": rows[0]["date"], "end": rows[-1]["date"]},
        "current_vs_historical": "historical_national_series",
        "rows": rows,
        "transformations": [
            "JSON records parsed; empty/malformed metrics set to null and dropped if all metrics missing.",
            "Negative values rejected. Rows sorted by date.",
        ],
    }


def fetch_owid_country(iso_code: str = "GBR", timeout: int = 40) -> dict:
    last_error = None
    text = None
    used_url = OWID_CSV_URL
    for url in (OWID_CSV_URL, OWID_FALLBACK_URL):
        try:
            raw = _http_get(url, timeout=timeout)
            text = raw.decode("utf-8", errors="replace")
            used_url = url
            break
        except (URLError, TimeoutError, OSError) as exc:
            last_error = exc
    if text is None:
        raise URLError(str(last_error))

    wanted = [
        "date",
        "weekly_hosp_admissions",
        "hosp_patients",
        "icu_patients",
        "new_cases_smoothed",
    ]
    rows_raw = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        if row.get("iso_code") != iso_code:
            continue
        rows_raw.append({
            "date": row.get("date"),
            "weekly_hosp_admissions": row.get("weekly_hosp_admissions"),
            "hosp_patients": row.get("hosp_patients"),
            "icu_patients": row.get("icu_patients"),
            "new_cases_smoothed": row.get("new_cases_smoothed"),
        })
    rows = _validate_rows(rows_raw, wanted[1:])
    if len(rows) < 10:
        raise ValueError(f"OWID {iso_code} had too few usable hospital rows.")
    return {
        "source_id": "owid_covid",
        "iso_code": iso_code,
        "url": used_url,
        "classification": REAL_OBSERVATION,
        "availability_status": CURRENT_EXTERNAL,
        "retrieved_at": _now(),
        "n_rows": len(rows),
        "coverage": {"start": rows[0]["date"], "end": rows[-1]["date"]},
        "current_vs_historical": "historical_country_series",
        "rows": rows,
        "transformations": [
            f"CSV streamed; kept iso_code={iso_code} only.",
            "weekly_hosp_admissions converted later to daily-rate DERIVED_PARAMETER (divide by 7).",
            "Missing/malformed numeric fields nulled.",
        ],
    }


def synthetic_arrival_fixture(n_days: int = 120, seed: int = 2020) -> dict:
    """
    Offline fixture with known Negative-Binomial parameters.

    Classification: SIMULATED_VALUE. This is NOT UKHSA or OWID data.
    """
    import random
    from data.distributions import nbinom_sample

    rng = random.Random(seed)
    mu, size = 80.0, 4.0
    rows = []
    for i in range(n_days):
        month = 1 + (i // 30) % 12
        day = 1 + (i % 28)
        adm = nbinom_sample(rng, mu, size)
        hosp = max(0, int(round(adm * 5 + rng.gauss(0, 20))))
        mv = max(0, int(round(hosp * 0.17 + rng.gauss(0, 8))))
        rows.append({
            "date": f"2020-{month:02d}-{day:02d}",
            "newAdmissions": float(adm),
            "hospitalCases": float(hosp),
            "covidOccupiedMVBeds": float(mv),
        })
    return {
        "source_id": "synthetic_arrival_fixture",
        "classification": SIMULATED_VALUE,
        "availability_status": SYNTHETIC_FALLBACK,
        "retrieved_at": _now(),
        "n_rows": len(rows),
        "coverage": {"start": rows[0]["date"], "end": rows[-1]["date"]},
        "current_vs_historical": "not_empirical",
        "true_params": {"nbinom_mu": mu, "nbinom_size": size, "seed": seed},
        "rows": rows,
        "transformations": [
            "Generated offline for reproducibility when public APIs are unreachable.",
            "Must not be described as hospital observations.",
        ],
    }


def ingest_hospital_series(prefer_live: bool = True) -> dict:
    """
    Return a normalized hospital-activity table plus provenance.

    Order: UKHSA live → OWID GBR live → cached live snapshot → synthetic fixture.
    """
    errors: list[str] = []
    if prefer_live:
        try:
            payload = fetch_ukhsa_overview()
            write_cache("hospital_series.json", payload)
            return payload
        except Exception as exc:
            errors.append(f"UKHSA: {exc}")
            logger.warning("UKHSA fetch failed: %s", exc)
        try:
            owid = fetch_owid_country("GBR")
            rows = []
            for r in owid["rows"]:
                weekly = r.get("weekly_hosp_admissions")
                daily = (weekly / 7.0) if weekly is not None else None
                rows.append({
                    "date": r["date"],
                    "newAdmissions": daily,
                    "hospitalCases": r.get("hosp_patients"),
                    "covidOccupiedMVBeds": r.get("icu_patients"),
                })
            payload = {
                "source_id": "owid_covid",
                "classification": REAL_OBSERVATION,
                "availability_status": CURRENT_EXTERNAL,
                "derived_fields": {
                    "newAdmissions": tagged(
                        "weekly_hosp_admissions / 7",
                        DERIVED_PARAMETER,
                        "owid_covid",
                        note="Daily-rate proxy from weekly admissions.",
                    )
                },
                "retrieved_at": owid["retrieved_at"],
                "n_rows": len(rows),
                "coverage": owid["coverage"],
                "current_vs_historical": owid["current_vs_historical"],
                "rows": _validate_rows(
                    rows, ["newAdmissions", "hospitalCases", "covidOccupiedMVBeds"]
                ),
                "transformations": owid["transformations"]
                + ["weekly_hosp_admissions/7 → newAdmissions (DERIVED)."],
            }
            payload["n_rows"] = len(payload["rows"])
            write_cache("hospital_series.json", payload)
            return payload
        except Exception as exc:
            errors.append(f"OWID: {exc}")
            logger.warning("OWID fetch failed: %s", exc)

    cached = read_cache("hospital_series.json")
    if cached and cached.get("classification") == REAL_OBSERVATION:
        cached["cache_hit"] = True
        cached["availability_status"] = CACHED_EMPIRICAL
        return cached

    fixture = synthetic_arrival_fixture()
    fixture["fallback_errors"] = errors
    fixture["cache_hit"] = False
    fixture["availability_status"] = SYNTHETIC_FALLBACK
    return fixture


def ingest_from_validated_dataset(payload: dict) -> dict:
    """
    Accept a provenance-tagged dataset object (future calibration input).

    This is not a CSV upload endpoint. Callers must already validate rows.
    """
    if not isinstance(payload, dict):
        raise ValueError("dataset must be an object.")
    for key in ("source_id", "classification", "rows"):
        if key not in payload:
            raise ValueError(f"dataset missing '{key}'.")
    if not isinstance(payload["rows"], list):
        raise ValueError("dataset rows must be a list.")
    return payload


def load_literature_los() -> dict:
    path = os.path.join(DATA_DIR, "literature_los.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
