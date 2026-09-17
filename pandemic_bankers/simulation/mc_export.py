"""Format Monte Carlo experiment results for download. No extra mathematics."""

from __future__ import annotations

import csv
import io
import json
from typing import Any


EXPORT_ROW_FIELDS = (
    "patient_count",
    "trials",
    "collapse_trials",
    "safe_trials",
    "unsafe_trials",
    "admission_fail_trials",
    "collapse_probability",
    "wilson_lower",
    "wilson_upper",
    "seed",
    "model",
    "data_source",
)

ALLOWED_EXPERIMENT_KEYS = {
    "model",
    "model_label",
    "seed",
    "trials_per_load",
    "patient_range",
    "resource_capacities",
    "resource_names",
    "severity_distribution",
    "p_icu_severe",
    "seed_policy",
    "probability_estimator",
    "ci_method",
    "ci_z",
    "ci_level",
}

ALLOWED_PROVENANCE_KEYS = {
    "data_source",
    "availability_status",
    "classification",
    "calibrated_at",
    "note",
    "data_status",
    "reproducibility",
    "reproducibility_note",
    "external_signal_value",
    "signal_timestamp",
    "signal_retrieval_timestamp",
    "source_id",
    "reference_constant",
    "clip_lower",
    "clip_upper",
    "derived_workload_factor",
}

ALLOWED_RESULT_KEYS = {
    "patient_count",
    "trials",
    "collapse_trials",
    "safe_trials",
    "unsafe_trials",
    "admission_fail_trials",
    "collapse_probability",
    "wilson_lower",
    "wilson_upper",
    "p_unsafe",
    "p_admission_failure",
}


def _pick(src: dict, allowed: set[str]) -> dict:
    return {k: src[k] for k in allowed if k in src}


def build_export_payload(
    experiment: dict[str, Any],
    provenance: dict[str, Any] | None,
    curve: list[dict],
    n50: int | None,
    seed: int,
    model: str,
    data_source: str,
) -> dict[str, Any]:
    rows = []
    for entry in curve:
        rows.append({
            "patient_count": entry["n"],
            "trials": entry.get("trials"),
            "collapse_trials": entry.get("collapse_trials"),
            "safe_trials": entry.get("safe_trials"),
            "unsafe_trials": entry.get("unsafe_trials"),
            "admission_fail_trials": entry.get("admission_fail_trials"),
            "collapse_probability": entry["p_collapse"],
            "wilson_lower": entry["ci_lo"],
            "wilson_upper": entry["ci_hi"],
            "p_unsafe": entry.get("p_unsafe"),
            "p_admission_failure": entry.get("p_admission_failure"),
            "seed": seed,
            "model": model,
            "data_source": data_source,
        })
    payload = {
        "experiment": _pick(experiment, ALLOWED_EXPERIMENT_KEYS),
        "provenance": _pick(provenance or {}, ALLOWED_PROVENANCE_KEYS),
        "n50": n50,
        "n50_definition": "min { n tested : p_hat(n) >= 0.50 }; no interpolation.",
        "results": [_pick(r, set(ALLOWED_RESULT_KEYS) | {"seed", "model", "data_source"}) for r in rows],
    }
    return payload


def export_json_text(payload: dict) -> str:
    return json.dumps(payload, indent=2)


def export_csv_text(payload: dict) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(EXPORT_ROW_FIELDS), extrasaction="ignore")
    writer.writeheader()
    model = (payload.get("experiment") or {}).get("model")
    seed = (payload.get("experiment") or {}).get("seed")
    source = (payload.get("provenance") or {}).get("data_source", "")
    for row in payload.get("results") or []:
        out = {k: row.get(k) for k in EXPORT_ROW_FIELDS}
        out["seed"] = row.get("seed", seed)
        out["model"] = row.get("model", model)
        out["data_source"] = row.get("data_source", source)
        writer.writerow(out)
    return buf.getvalue()


def parse_export_request(body: dict) -> dict:
    """Validate a client-echoed experiment payload. Formatting only; no secrets."""
    if not isinstance(body, dict):
        raise ValueError("Export body must be a JSON object.")
    experiment = body.get("experiment")
    results = body.get("results")
    if not isinstance(experiment, dict):
        raise ValueError("Missing experiment configuration.")
    if not isinstance(results, list) or not results:
        raise ValueError("Missing results array.")
    for row in results:
        if not isinstance(row, dict):
            raise ValueError("Each result must be an object.")
        if "patient_count" not in row or "collapse_probability" not in row:
            raise ValueError("Each result needs patient_count and collapse_probability.")
    forbidden = ("ADMIN_TOKEN", "admin_token", "api_key", "password", "secret", "env")
    blob = json.dumps(body)
    for word in forbidden:
        if word in blob:
            raise ValueError("Export body contains disallowed keys.")
    return body
