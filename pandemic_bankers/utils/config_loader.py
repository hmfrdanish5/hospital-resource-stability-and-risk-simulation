"""Configuration loader with validation for hospital pandemic simulator."""

import json
import os
from typing import Any


class ConfigError(Exception):
    """Raised when hospital_config.json fails schema validation."""
    pass


REQUIRED_KEYS = {
    "hospital": ["name", "total_beds", "random_seed", "max_patients"],
    "resources": ["names", "baseline", "surge"],
    "severity_distributions": ["normal", "surge"],
    "demand_profiles": None,
    "simulation": ["mode", "severity_mode"],
}

SEVERITY_TIERS = ["Mild", "Moderate", "Severe", "Critical"]


class ConfigLoader:
    """Loads and validates hospital_config.json, exposes typed accessors."""

    def __init__(self, path: str = "hospital_config.json") -> None:
        if not os.path.exists(path):
            raise ConfigError(f"Config file not found: {path}")
        with open(path, "r") as fh:
            try:
                self._data: dict = json.load(fh)
            except json.JSONDecodeError as exc:
                raise ConfigError(f"Invalid JSON: {exc}") from exc
        self._validate()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate(self) -> None:
        for section, keys in REQUIRED_KEYS.items():
            if section not in self._data:
                raise ConfigError(f"Missing top-level section: '{section}'")
            if keys:
                for key in keys:
                    if key not in self._data[section]:
                        raise ConfigError(f"Missing key '{key}' in section '{section}'")

        # Validate resource lists have same length
        res = self._data["resources"]
        n = len(res["names"])
        if len(res["baseline"]) != n or len(res["surge"]) != n:
            raise ConfigError("Resource lists (names/baseline/surge) must be same length")

        # Validate demand profile bounds: min <= max, non-negative
        dp = self._data["demand_profiles"]
        for tier in SEVERITY_TIERS:
            if tier not in dp:
                raise ConfigError(f"demand_profiles missing tier '{tier}'")
            for bound in ("min", "max"):
                if bound not in dp[tier]:
                    raise ConfigError(f"demand_profiles['{tier}'] missing '{bound}'")
            lo, hi = dp[tier]["min"], dp[tier]["max"]
            if len(lo) != n or len(hi) != n:
                raise ConfigError(
                    f"demand_profiles['{tier}'] vectors must have length {n}"
                )
            for j in range(n):
                if lo[j] < 0 or hi[j] < 0:
                    raise ConfigError(
                        f"demand_profiles['{tier}']: negative bound at index {j}"
                    )
                if lo[j] > hi[j]:
                    raise ConfigError(
                        f"demand_profiles['{tier}']: min[{j}]={lo[j]} > max[{j}]={hi[j]}"
                    )
            for j, name in enumerate(res["names"]):
                if name in ("ICU_Beds", "Ventilators") and hi[j] > 1:
                    raise ConfigError(
                        f"demand_profiles['{tier}']['{name}']: max must be 0 or 1 "
                        f"(binary resource), got {hi[j]}"
                    )

        # Validate severity distributions sum to ~1
        for mode_name in ("normal", "surge"):
            dist = self._data["severity_distributions"][mode_name]
            total = sum(dist.values())
            if not (0.99 <= total <= 1.01):
                raise ConfigError(
                    f"severity_distributions['{mode_name}'] probabilities sum to {total:.3f}, expected 1.0"
                )

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def hospital_name(self) -> str:
        return self._data["hospital"]["name"]

    @property
    def total_beds(self) -> int:
        return int(self._data["hospital"]["total_beds"])

    @property
    def random_seed(self) -> int:
        return int(self._data["hospital"]["random_seed"])

    @property
    def max_patients(self) -> int:
        return int(self._data["hospital"]["max_patients"])

    @property
    def resource_names(self) -> list[str]:
        return list(self._data["resources"]["names"])

    def resource_totals(self, mode: str = "baseline") -> list[int]:
        key = mode.lower()
        if key not in ("baseline", "surge"):
            raise ConfigError(f"Unknown resource mode: '{mode}'")
        return list(self._data["resources"][key])

    def severity_distribution(self, mode: str = "normal") -> dict[str, float]:
        key = mode.lower()
        if key not in self._data["severity_distributions"]:
            raise ConfigError(f"Unknown severity mode: '{mode}'")
        return dict(self._data["severity_distributions"][key])

    def demand_profile(self, tier: str) -> tuple[list[int], list[int]]:
        if tier not in self._data["demand_profiles"]:
            raise ConfigError(f"Unknown severity tier: '{tier}'")
        dp = self._data["demand_profiles"][tier]
        return list(dp["min"]), list(dp["max"])

    @property
    def simulation_mode(self) -> str:
        return self._data["simulation"]["mode"]

    @property
    def severity_mode(self) -> str:
        return self._data["simulation"]["severity_mode"]

    def raw(self) -> dict:
        return self._data

    def dynamic_model(self) -> dict:
        """Phase 2 time-dependent parameters (optional section; defaults apply)."""
        return dict(self._data.get("dynamic_model") or {})
