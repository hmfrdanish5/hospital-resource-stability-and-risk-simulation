"""
Generate Project_Brief_Report.pdf for sharing with reviewers.
Requires matplotlib (already in requirements.txt).
"""

from __future__ import annotations

import os
import textwrap

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "Project_Brief_Report.pdf")

TITLE = "Hospital Resource Stability Lab"
SUBTITLE = "Brief Project Report — Pandemic Healthcare Stability Analysis"
DATE = "September 2026"

SECTIONS: list[tuple[str, list[str]]] = [
    (
        "What this is",
        [
            "An academic simulation of hospital resource allocation under pandemic-like pressure.",
            "It answers: (1) Is the current allocation state SAFE? (Banker's Algorithm) and",
            "(2) As patient load grows, what is the probability of collapse? (Monte Carlo).",
            "This is not a live hospital system or clinical decision tool. Results are model-based.",
        ],
    ),
    (
        "Core model (Phase 1)",
        [
            "Five abstract resources: ICU beds, oxygen, ventilators, nurses, blood units.",
            "Each patient has Allocation, Max demand, Need = Max - Allocation, and Available capacity.",
            "Banker's Algorithm (Dijkstra, 1965) returns SAFE if a completion ordering exists, else UNSAFE.",
            "Monte Carlo sweeps n = 1..N patients with Wilson 95% CIs on P(collapse).",
            "Collapse = admission failure OR unsafe Banker's state.",
            "Isolated sensitivity: elasticity epsilon_k = (n_50(C') - n_50(C)) / delta_c_k per resource.",
        ],
    ),
    (
        "Time-dependent hospital (Phase 2)",
        [
            "Discrete time (default 1 hour): C(t) for nurse staffing (shift/weekend multipliers).",
            "Length of stay, fatigue (high utilization extends LOS), treatment bundles (all-or-nothing).",
            "Overflow state (ED_OVERFLOW) when bundles cannot be satisfied — not automatic collapse.",
            "Acuity degradation in overflow; severity-based triage for admission order.",
            "Banker's SAFE/UNSAFE remains a separate per-timestep snapshot. Preemption not implemented.",
        ],
    ),
    (
        "Empirical calibration (Phase 3)",
        [
            "Public data pipeline: Fetch -> Validate -> Clean -> Cache -> Calibrate (with fallback).",
            "Sources: OWID COVID-19, UK Coronavirus Dashboard, Rees et al. 2020 LoS review.",
            "Every quantity labeled: REAL OBSERVATION, MODEL ASSUMPTION, DERIVED PARAMETER, or SIMULATED.",
            "Arrivals: Poisson vs negative binomial (overdispersion tested). LOS: Gamma vs Weibull vs Lognormal.",
            "Model A = independent synthetic; B = severity-conditioned joint ICU/vent; C = calibrated.",
            "Copulas not used (no patient-level resource microdata).",
        ],
    ),
    (
        "Dashboard and verification",
        [
            "Web UI: Banker's trace, Monte Carlo curve, sensitivity, time model, Phase 3 A/B/C comparison.",
            "CLI: python pandemic_bankers/main.py. Tests: python tests/run_tests.py (68 tests).",
            "Mathematics reference page documents formulas and assumptions.",
        ],
    ),
    (
        "Limitations (for reviewers)",
        [
            "Five abstract resources; max demand assumed known (Banker's requirement).",
            "National/epidemiological data are not this hospital's live census.",
            "Under surge capacity, P(unsafe) is often near zero; admission failure dominates.",
            "Phase 2 parameters (fatigue, shifts) are sensitivity knobs unless backed by evidence.",
            "Not clinically validated — illustrative for allocation theory and stochastic risk.",
        ],
    ),
    (
        "One-sentence pitch",
        [
            "A reproducible academic lab combining Banker's deadlock avoidance, Monte Carlo collapse",
            "risk, discrete-time hospital dynamics, and optional public-data calibration — with clear",
            "separation between observations, assumptions, and simulation.",
        ],
    ),
    (
        "Questions for feedback",
        [
            "Are the five resources and demand profiles plausible for your setting?",
            "Is overflow vs Banker's UNSAFE the right split for system stress vs deadlock?",
            "Should Phase 3 prioritize local hospital CSV upload over national APIs?",
            "Which capacity scenario (baseline vs surge) best matches your narrative?",
            "Is the A/B/C experiment the right comparison for a paper?",
        ],
    ),
]


def _page(pdf: PdfPages, lines: list[str], title: str | None = None) -> None:
    fig = plt.figure(figsize=(8.5, 11))
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0.08, 0.06, 0.84, 0.88])
    ax.axis("off")
    y = 0.98
    if title:
        ax.text(0, y, title, fontsize=13, fontweight="bold", color="#5c1522", va="top")
        y -= 0.04
    for line in lines:
        if line == "---":
            y -= 0.02
            continue
        wrapped = textwrap.wrap(line, width=92) or [""]
        for w in wrapped:
            ax.text(0, y, w, fontsize=10, va="top", family="sans-serif", color="#1f1f24")
            y -= 0.032
            if y < 0.05:
                pdf.savefig(fig, bbox_inches="tight", facecolor="white")
                plt.close(fig)
                fig = plt.figure(figsize=(8.5, 11))
                fig.patch.set_facecolor("white")
                ax = fig.add_axes([0.08, 0.06, 0.84, 0.88])
                ax.axis("off")
                y = 0.98
    pdf.savefig(fig, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with PdfPages(OUT) as pdf:
        cover = [
            TITLE,
            SUBTITLE,
            "",
            f"Generated: {DATE}",
            "",
            "Repository: Pandemic Healthcare Stability Analysis",
            "Phases: 1 Mathematical core | 2 Time-dependent hospital | 3 Empirical calibration",
        ]
        fig = plt.figure(figsize=(8.5, 11))
        fig.patch.set_facecolor("white")
        ax = fig.add_axes([0.1, 0.35, 0.8, 0.4])
        ax.axis("off")
        ax.text(0.5, 0.85, TITLE, ha="center", fontsize=22, fontweight="bold", color="#5c1522")
        ax.text(0.5, 0.65, SUBTITLE, ha="center", fontsize=12, color="#5a5a66")
        ax.text(0.5, 0.35, f"Generated: {DATE}", ha="center", fontsize=11, color="#5a5a66")
        ax.text(
            0.5, 0.15,
            "Phase 1: Banker's + Monte Carlo  |  Phase 2: C(t), LOS, overflow\n"
            "Phase 3: Public-data calibration (A/B/C models)",
            ha="center", fontsize=10, color="#5a5a66",
        )
        pdf.savefig(fig, bbox_inches="tight", facecolor="white")
        plt.close(fig)

        for heading, bullets in SECTIONS:
            lines = [heading, "---"] + [f"  - {b}" if not b.startswith("  ") else b for b in bullets]
            _page(pdf, lines)

        d = pdf.infodict()
        d["Title"] = TITLE
        d["Author"] = "Hospital Resource Stability Lab"
        d["Subject"] = "Project brief for academic feedback"
        d["Keywords"] = "Banker's Algorithm, Monte Carlo, hospital resources, pandemic"

    print(f"Wrote: {OUT}")


if __name__ == "__main__":
    main()
