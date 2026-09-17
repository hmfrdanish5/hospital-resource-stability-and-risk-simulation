"""
Hospital Resource Stability Simulator
========================================
Entry point — orchestrates config loading, simulation, analysis,
and reporting.

Run:
    python main.py
"""

from __future__ import annotations

import json
import os
import sys
import random
import datetime
import textwrap

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(__file__))

from utils.config_loader import ConfigLoader, ConfigError
from core.bankers_engine import BankersEngine
from simulation.domain import HospitalSystem
from analytics.stability_analyzer import StabilityAnalyzer

# ─────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "hospital_config.json")
OUTPUT_DIR = os.path.dirname(__file__)     # write outputs next to main.py

DIVIDER = "-" * 72
BOLD = "\033[1m"
RESET = "\033[0m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def header(text: str) -> None:
    print(f"\n{BOLD}{CYAN}{DIVIDER}{RESET}")
    print(f"{BOLD}{CYAN}  {text}{RESET}")
    print(f"{BOLD}{CYAN}{DIVIDER}{RESET}")


def print_hospital_summary(cfg: ConfigLoader) -> None:
    header("HOSPITAL CONFIGURATION SUMMARY")
    print(f"  {'Model':<28}: {cfg.hospital_name}")
    print(f"  {'Total Beds':<28}: {cfg.total_beds}")
    print(f"  {'Resource Mode':<28}: {cfg.simulation_mode.upper()}")
    print(f"  {'Severity Distribution Mode':<28}: {cfg.severity_mode.upper()}")
    print(f"  {'Random Seed':<28}: {cfg.random_seed}")
    print(f"  {'Max Patients Sweep':<28}: {cfg.max_patients}")
    print()
    totals = cfg.resource_totals(cfg.simulation_mode)
    print(f"  {'Resource':<22} {'Total Units':>12}")
    print(f"  {'-'*22} {'-'*12}")
    for name, total in zip(cfg.resource_names, totals):
        print(f"  {name:<22} {total:>12}")
    print()
    dist = cfg.severity_distribution(cfg.severity_mode)
    print(f"  Severity distribution ({cfg.severity_mode.upper()}):")
    for tier, prob in dist.items():
        bar = "#" * int(prob * 30)
        print(f"    {tier:<12} {prob*100:5.1f}%  {bar}")


def print_research_summary(result: dict, cfg: ConfigLoader) -> None:
    header("RESEARCH SUMMARY - BANKER'S ALGORITHM ANALYSIS")

    print(f"  {'Analysis Timestamp':<32}: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # --------------------------------------------------
    # MONTE CARLO MODE
    # --------------------------------------------------
    if result.get("analysis_type") == "Monte Carlo Collapse Probability":

        max_n = result["max_patients_tested"]
        trials = result["trials_per_n"]
        risk = result["risk_summary"]

        print(f"  {'Analysis Type':<32}: Monte Carlo Collapse Probability")
        print(f"  {'Trials per Patient Count':<32}: {trials}")
        print(f"  {'Patients Swept':<32}: 1 - {max_n}")
        print()

        print(f"  Risk Thresholds:")
        print(f"    10% Instability Begins At : {risk['instability_onset_at']}")
        print(f"    50% Collapse Probability  : {risk['collapse_probability_50_percent_at']}")
        print(f"    70% High Risk Region At   : {risk['high_risk_region_begins_at']}")
        print()

        print(f"  Output Files:")
        print(f"    - collapse_probability_curve.png")
        print()

        return

    # --------------------------------------------------
    # DETERMINISTIC MODE
    # --------------------------------------------------

    collapse = result["collapse_detected"]
    collapse_n = result["collapse_at_patient"]
    safe_cap = result["safe_capacity"]
    max_n = result["max_patients_tested"]

    print(f"  {'Resource Mode':<32}: {result['resource_mode'].upper()}")
    print(f"  {'Severity Mode':<32}: {result['severity_mode'].upper()}")
    print(f"  {'Patients Swept':<32}: 1 – {max_n}")
    print()

    if collapse:
        status_str = f"{RED}COLLAPSE DETECTED{RESET}"
        print(f"  System Status        : {status_str}")
        print(f"  Collapse Threshold   : {YELLOW}Patient #{collapse_n}{RESET}")
        print(f"  Safe Capacity        : {GREEN}{safe_cap} patients{RESET}")
        pct = safe_cap / cfg.total_beds * 100
        print(f"  Safe Capacity / Beds : {pct:.1f}%")
        print()
        print(f"  Resource Utilization at Collapse Point:")
        print(f"  {'Resource':<22} {'Utilization':>12}")
        print(f"  {'-'*22} {'-'*12}")
        for name, val in result["utilization_at_collapse"].items():
            pct_util = val * 100
            flag = f"{RED}  <- CRITICAL{RESET}" if pct_util >= 90 else \
                   f"{YELLOW}  <- WARNING{RESET}" if pct_util >= 70 else ""
            print(f"  {name:<22} {pct_util:>10.1f}%{flag}")
    else:
        print(f"  System Status        : {GREEN}STABLE - no collapse detected within {max_n} patients{RESET}")
        print(f"  Safe Capacity        : {GREEN}>= {max_n} patients{RESET}")

    print()
    print(f"  Output Files:")
    print(f"    - stability_curve.png")
    print(f"    - resource_utilization_at_collapse.png")
    print(f"    - stability_report.json")
    print()
# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"\n{BOLD}{'='*72}{RESET}")
    print(f"{BOLD}   HOSPITAL RESOURCE STABILITY SIMULATOR{RESET}")
    print(f"{BOLD}   Banker's Algorithm - Resource Safety Analysis{RESET}")
    print(f"{BOLD}{'='*72}{RESET}")

    # 1. Load config
    try:
        cfg = ConfigLoader(CONFIG_PATH)
    except ConfigError as exc:
        print(f"\n{RED}[CONFIG ERROR] {exc}{RESET}")
        sys.exit(1)

    # 2. Hospital summary
    print_hospital_summary(cfg)

    # 3. Quick demo — admit patients and check safety at full sweep start
    header("BANKER'S ENGINE DEMO - SINGLE SCENARIO")
    engine = BankersEngine(
        total_resources=cfg.resource_totals(cfg.simulation_mode),
        resource_names=cfg.resource_names,
    )
    rng = random.Random(cfg.random_seed)
    hospital = HospitalSystem(cfg, engine, rng)

    demo_n = min(10, cfg.max_patients)
    admitted = hospital.admit_n_patients(demo_n)
    safe, seq, blocking = engine.is_safe()

    print(f"  Admitted {len(admitted)} demo patients.")
    print(f"  Severity breakdown: {hospital.severity_breakdown()}")
    print(f"  System Safe: {GREEN + 'YES' + RESET if safe else RED + 'NO' + RESET}")
    if seq:
        seq_preview = " -> ".join(seq[:6]) + (" -> ..." if len(seq) > 6 else "")
        print(f"  Safe Sequence (preview): {seq_preview}")
    util_demo = engine.utilization()
    print(f"  Current Utilization:")
    for name, val in util_demo.items():
        print(f"    {name:<22} {val*100:6.1f}%")

    # 4. Full stability sweep
    header("RUNNING STABILITY SWEEP")
    analyzer = StabilityAnalyzer(cfg, output_dir=OUTPUT_DIR)
    result = analyzer.run()

    # 5. Research summary
    print_research_summary(result, cfg)

    # 6. Save JSON report
    report_path = os.path.join(OUTPUT_DIR, "stability_report.json")

    if result.get("analysis_type") == "Monte Carlo Collapse Probability":

        report = {
            "metadata": {
                "title": "Hospital Resource Stability Report",
                "hospital": cfg.hospital_name,
                "generated_at": datetime.datetime.now().isoformat(),
                "algorithm": "Banker's Safety Algorithm (Monte Carlo Variant)",
            },
            "analysis_type": "Monte Carlo Collapse Probability",
            "trials_per_n": result["trials_per_n"],
            "max_patients_tested": result["max_patients_tested"],
            "risk_summary": result["risk_summary"],
            "probability_curve": result["probability_curve"],
        }

    else:
        report = {
            "metadata": {
                "title": "Hospital Resource Stability Report",
                "hospital": cfg.hospital_name,
                "generated_at": datetime.datetime.now().isoformat(),
                "algorithm": "Banker's Safety Algorithm (Deterministic)",
                "resource_mode": result["resource_mode"],
                "severity_mode": result["severity_mode"],
            },
            "analysis": {
                "collapse_detected": result["collapse_detected"],
                "collapse_at_patient": result["collapse_at_patient"],
                "safe_capacity": result["safe_capacity"],
                "max_patients_tested": result["max_patients_tested"],
            },
            "utilization_at_collapse": result["utilization_at_collapse"],
            "stability_curve": result["stability_curve"],
            "utilization_history": result["utilization_history"],
        }

    with open(report_path, "w") as fh:
        json.dump(report, fh, indent=2)

    print(f"  Saved: {report_path}")

if __name__ == "__main__":
    main()
