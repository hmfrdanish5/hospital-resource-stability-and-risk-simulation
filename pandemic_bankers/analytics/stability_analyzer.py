"""
Stability Analyzer
==================
Monte Carlo sweep of patient load with Banker's Algorithm safety checks.
Produces collapse_probability_curve.png and structured analysis dict.
"""

from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from simulation.monte_carlo import monte_carlo_from_config
from utils.config_loader import ConfigLoader


class StabilityAnalyzer:
    """Runs Monte Carlo collapse-probability analysis from hospital config."""

    def __init__(self, config: ConfigLoader, output_dir: str = ".") -> None:
        self._config = config
        self._output_dir = output_dir
        self._result: dict = {}

    def run(self, trials_per_n: int = 100) -> dict:
        """Execute Monte Carlo sweep and generate probability curve plot."""
        cfg = self._config
        print(f"\n  Monte Carlo sweep 1 - {cfg.max_patients}  "
              f"({trials_per_n} trials per n)  ...")

        result = monte_carlo_from_config(cfg, trials_per_n=trials_per_n)

        # Map to CLI/report field names for backward compatibility
        probability_curve = []
        for entry in result["probability_curve"]:
            probability_curve.append({
                "n": entry["n"],
                "collapse_probability": entry["p_collapse"],
                "ci_lower": entry["ci_lo"],
                "ci_upper": entry["ci_hi"],
                "admission_failure_probability": entry.get("p_admission_failure", 0.0),
                "unsafe_probability": entry.get("p_unsafe", 0.0),
            })
            if entry["n"] % 10 == 0 or entry["n"] == cfg.max_patients:
                print(f"    n={entry['n']:3d}  collapse_prob={entry['p_collapse']:.3f}")

        risk = result["risk_summary"]
        risk_summary = {
            "collapse_probability_50_percent_at": risk["threshold_50pct"],
            "high_risk_region_begins_at": risk["threshold_70pct"],
            "instability_onset_at": risk["threshold_10pct"],
        }

        self._result = {
            "analysis_type": "Monte Carlo Collapse Probability",
            "trials_per_n": trials_per_n,
            "max_patients_tested": cfg.max_patients,
            "probability_curve": probability_curve,
            "risk_summary": risk_summary,
        }

        self._plot_probability_curve(probability_curve)
        return self._result

    @property
    def result(self) -> dict:
        return self._result

    def _plot_probability_curve(self, curve: list[dict]) -> None:
        fig, ax = plt.subplots(figsize=(10, 5))
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")

        ns = [c["n"] for c in curve]
        probs = [c["collapse_probability"] for c in curve]
        lower = [c["ci_lower"] for c in curve]
        upper = [c["ci_upper"] for c in curve]

        ax.plot(ns, probs, color="#2563eb", linewidth=2, label="P(Collapse)")
        ax.fill_between(ns, lower, upper, color="#2563eb", alpha=0.12, label="95% Wilson CI")
        ax.axhline(0.5, linestyle="--", linewidth=1, color="#dc2626", label="50% threshold")
        ax.axhline(0.1, linestyle=":", linewidth=1, color="#16a34a", label="10% onset")

        ax.set_xlabel("Number of Admitted Patients")
        ax.set_ylabel("Probability of Unsafe / Infeasible State")
        ax.set_ylim(0, 1)
        ax.set_title("Monte Carlo Collapse Probability - Banker's Algorithm")
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)

        plt.tight_layout()
        path = f"{self._output_dir}/collapse_probability_curve.png"
        plt.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        print(f"\n  Saved: {path}")
