# Hospital Resource Stability Lab

Interactive academic tool for **Banker's Algorithm** safety analysis and **Monte Carlo** collapse-probability estimation under pandemic-like hospital workload conditions.

(live demo: https://pandemic-healthcare-stability-lab.onrender.com/)

## Problem Statement

During surge conditions, hospitals must allocate scarce resources (ICU beds, oxygen, ventilators, staff, blood products) across patients with varying severity. This project models each patient as a process in a multi-resource allocation system and asks:

1. Is the current allocation state **SAFE** (exists a completion ordering without deadlock)?
2. As patient load increases, what is the **estimated probability of collapse** (admission failure or unsafe state)?

## Overview

The Hospital Resource Stability Lab is an interactive simulation framework
for studying hospital resource stability under increasing workload.

It combines:

- Banker's Algorithm for multi-resource safety analysis
- Monte Carlo simulation for collapse-probability estimation
- Dynamic staffing and resource-capacity modeling
- Empirically informed arrival and length-of-stay models
- Wilson confidence intervals and sensitivity analysis
- Interactive Flask dashboard with streamed Monte Carlo results

The system is designed as an academic research and demonstration tool,
not as a clinical decision-support system.

## Mathematical Model

| Symbol | Meaning |
|--------|---------|
| `Allocation[i,j]` | Resource units currently held by patient *i* |
| `Max[i,j]` | Maximum units patient *i* may require |
| `Need[i,j]` | `Max[i,j] − Allocation[i,j]` |
| `Available[j]` | Free units of resource *j* |

**Invariants:** `0 ≤ Allocation ≤ Max`, `Need ≥ 0`, `Total[j] = Available[j] + Σ Allocation[i,j]`

## Banker's Algorithm

Standard safety procedure (Dijkstra, 1965): initialize `Work = Available`, find unfinished patients with `Need ≤ Work`, release their allocation into `Work`, repeat. **SAFE** if all finish; **UNSAFE** otherwise.

## Monte Carlo Methodology

For each patient count *n* = 1…*N*, run *T* independent trials:
1. Generate *n* patients with stochastic severity and demand vectors
2. Attempt sequential admission
3. Run Banker's safety check
4. Record collapse (admission failure **or** unsafe state)

Estimated: `P̂(collapse | n) = K_n / T` with **Wilson 95% score intervals** (z = 1.96). Seed policy: trial `t` at load `n` uses `Random(base_seed + n*1000 + t)`.

**n₅₀** is discrete: `n50 = min { n tested : p̂(n) ≥ 0.50 }`. No interpolation. If no tested n reaches 0.50, n₅₀ is undefined (null).

Collapse, admission failure, Banker's UNSAFE, overflow, and fatigue are **distinct** events. They are not synonyms.

## External Data

Optional Monte Carlo load scaling uses the [Our World in Data COVID-19 dataset](https://github.com/owid/covid-19-data) (CC-BY 4.0) as a **latest-available public epidemiological signal**: `f(X) = clip(X / X_ref, 0.5, 3.0)` where X is 14-day mean global smoothed new cases. `X_ref = 50_000` and clip bounds are **MODEL_ASSUMPTION** normalization choices, not hospital occupancy or capacity. This is **not** real-time facility census.

**Reproducibility policy (default offline):**
- `prefer_live=False` (default): **CACHED_EMPIRICAL** snapshot → **SYNTHETIC_FALLBACK** (labeled, multiplier 1.0)
- `prefer_live=True` or `?live=1` / `live_external: true`: **LIVE_EXTERNAL** fetch; records signal value, retrieval time, and transformation parameters. **Not reproducible from seed alone.**

Calibration provenance is labeled `REAL_OBSERVATION` / `DERIVED_PARAMETER` / `MODEL_ASSUMPTION` / `SIMULATED_VALUE`. Offline runs use a **labeled synthetic arrival fixture**, not empirical hospital data. Catalog: `pandemic_bankers/data/data_sources.json`.

## Time-dependent model (Phase 2)

Discrete-time simulation (`Δt` configurable, default 1 hour) with:

- Nurse capacity `C_nurse(t) = round(C_base × m_shift(t) × m_weekend(t))` (integer; multipliers are configurable **model assumptions**)
- If `C(t)` would fall below current allocation, lowest-priority in-care patients are overflowed **explicitly** (holdings are never silently destroyed)
- Length of stay, fatigue delay `effective_LOS = base_LOS × (1 + α)` (α configurable, not a clinical fact)
- Treatment bundles (all-or-nothing WARD/ICU)
- ED overflow and acuity degradation (overflow ≠ Banker's UNSAFE)
- Severity triage for admission order

Acuity-based preemption is **not** implemented (would make Banker's Max/Need ambiguous).

Resource units in generation are **integers**. ICU beds and ventilators are 0 or 1 per patient. Nurse/oxygen/blood units are model slots, not measured liters or FTE hours.

## Empirical calibration (Phase 3)

The project is **empirically informed**, not a fully calibrated model of a named hospital.

LOS uses **quantile-based distribution reconstruction** from Rees et al. (2020) published Q25/Q50/Q75, scored by quantile reconstruction SSE, **not** patient-level MLE and **not** a formal GOF test. For lognormal reconstruction, Q50 is matched by construction; Q25/Q75 are not guaranteed to match published quartiles unless the data are truly lognormal. Gamma predicted quantiles use Wilson–Hilferty (documented approximation). Arrival counts: Poisson vs negative binomial using mean, variance, and dispersion \(D=\mathrm{Var}/\mathrm{Mean}\) (diagnostic). Negative binomial uses NB2 / Gamma–Poisson (`size` \(\theta\): \(\mathrm{Var}=\mu+\mu^2/\theta\)). Arrival-mean interval is an **IID percentile bootstrap** (does not preserve time-series dependence; block bootstrap is not used). Copulas are **not** used: available data do not support patient-level joint dependence.

**Fallback hierarchy (never silent):** live/current source if requested and reachable → cached `REAL_OBSERVATION` (`CACHED_EMPIRICAL`) → labeled synthetic fixture (`SYNTHETIC_FALLBACK`). Live network access is not required to run the app (`prefer_live=False` on the Phase 3 dashboard route).

### Experiment families (do not collapse these)

1. **Static Banker collapse analysis** : Phase 1 n-sweep: \(\hat p_n\), Wilson CI, discrete \(n_{50}\). Isolated discrete marginal sensitivity is a separate Phase 1 experiment.
2. **Dynamic empirically informed simulation**: Phase 2 time model: overflow rate/duration, fatigue exposure, utilization. Model C uses calibrated arrival family, weekday \(\lambda(t)=\lambda_0 r_{\mathrm{dow}(t)}\), and quantile-reconstructed LOS. Hospital \(\lambda_0\) remains a **MODEL_ASSUMPTION** (`arrivals_per_step`).

### Model A / B / C (what the code actually does)

| Model | Static Banker's collapse (n-sweep) | Dynamic overflow | External data |
|-------|-------------------------------------|------------------|---------------|
| A Independent synthetic demand | Independent draws given severity | Configured arrivals; uniform LOS; bundles | None in the generators |
| B Severity-conditioned demand | Joint ICU/vent given severity | Same dynamic inputs as A | Occupancy mapping may inform p(ICU\|Severe) for **static** B and C; not complete empirical census |
| C Empirically informed dynamic | **Same demand as B** (not a separately calibrated static collapse) | Calibrated family + weekday \(\lambda(t)\) + quantile LOS | Rees LOS quantiles; arrival family/weekday from ingested series or synthetic fixture |

Calibrated arrivals and LOS **do not** change n₅₀ / P(collapse). They affect the **dynamic** overflow experiment only.

Empirical assumption sensitivity (0.9×–1.2× on \(\lambda_0\), LOS, fatigue \(\alpha\)) reports overflow metrics. It does **not** replace isolated discrete marginal sensitivity.

See `docs/MATHEMATICAL_MODEL.md` for numbered formulas.

## Sensitivity Analysis

Isolated one-resource perturbations: `ε_k = (n50(C + Δc_k e_k) − n50(C)) / Δc_k`. Display label: **Discrete Marginal Patient-Capacity Sensitivity**. This is a **local discrete finite-difference sensitivity** near the tested baseline, not standard dimensionless elasticity or an absolute bottleneck. Parameter ±5/10/20% sweeps and 0.9–1.2× empirical-assumption scales are separate experiments. Observed simulation differences are not reported as “statistically significant” unless a test is actually performed (none is).

## Installation

```bash
pip install -r requirements.txt
```

## for Running

Debug is **OFF** by default. For local debugging only:
```bash
set FLASK_DEBUG=1
python app.py
```

**Public / portfolio hosting:** plz do **not** use `python app.py` or `FLASK_DEBUG=1`. Use a WSGI server, for example:

```bash
cd pandemic_dashboard
pip install waitress
waitress-serve --listen=127.0.0.1:5000 app:app
```

On Linux you may use gunicorn instead: `gunicorn -w 1 -b 0.0.0.0:$PORT app:app` (from `pandemic_dashboard/`).

**CLI analysis:**
```bash
cd pandemic_bankers
python main.py
```

**Tests:**
```bash
python tests/run_tests.py
```

**Monte Carlo experiment (dashboard):** configure patient range, trials, model A/B/C, and seed, then **Run Experiment**. Progress and Wilson intervals are streamed from Flask (SSE). Download CSV/JSON from the result card. Same seed and configuration reproduce the same `p_hat` values when using cached/offline data paths.

## Project Structure

```
pandemic_bankers/
  core/bankers_engine.py       Banker's safety algorithm
  simulation/
    resource_generator.py      Patient demand vectors
    domain.py                  Hospital admission logic
    monte_carlo.py             Stochastic collapse estimation
    time_model.py              Discrete time and staffing C(t)
    treatments.py              Pathway bundles and triage ranks
    dynamic_hospital.py        Phase 2 time-stepping simulator
  data/
    data_sources.json          Provenance catalog
    literature_los.json        Published LoS summaries
    pipeline.py                Fetch / validate / cache / fallback
    calibration.py             Derived parameters, weekday λ(t), summary
    signal_transform.py        f(X)=clip(X/X_ref, f_min, f_max) MODEL_ASSUMPTION
    external_fetcher.py        Cached/live epidemiological signal
    provenance.py              Observation vs assumption labels
  analytics/
    phase3_experiment.py       Model A/B/C + empirical-assumption sensitivity
    sensitivity.py             Discrete marginal capacity sensitivity
    stability_analyzer.py      CLI plotting
  utils/config_loader.py       JSON validation
  hospital_config.json         Model parameters

pandemic_dashboard/
  app.py                       Flask API
  comments_store.py            SQLite comments + feedback
  rate_limit_store.py          SQLite comment rate limits
  templates/                   HTML pages
  static/                      CSS + JS

tests/                         Mathematical core tests
```

## Quantitative Experiments

The project was evaluated through three controlled experiments designed to separate load sensitivity, resource capacity sensitivity, and dynamic staffing effects.

The experiments are simulation studies of the implemented model. They are intended to characterize model behavior under controlled assumptions, rather than make clinical predictions or estimate real-world hospital failure probabilities.

### Experiment 1: Monte Carlo Load Sweep

**Objective**

Determine how the estimated probability of system collapse changes as the number of simultaneously modeled patients increases.

**Configuration**

The baseline surge configuration was:

$$ C=(14,90,14,35,120) $$

for:

$$ (\text{ICU},\text{Oxygen},\text{Ventilators},\text{Nurses},\text{Blood}) $$

with severity distribution:

$$ P(S)= (0.60,0.15,0.15,0.10) $$

for mild, moderate, severe, and critical patients.

The experiment evaluated:

$$ n=1,\ldots,40 $$

with:

$$ 200\text{ Monte Carlo trials per }n $$

giving:

$$ 40\times200=\boxed{8000\text{ trials}} $$

using random seed 42 and with the external workload signal disabled.

**Collapse definition**

A trial was classified as a collapse when either:

- admission failed, or
- the resulting state was Banker-unsafe.

The estimated collapse probability was:

$$ \hat p(n)=\frac{K_n}{T} $$

where \(K_n\) is the number of collapse trials and \(T=200\).

A Wilson 95% confidence interval was reported for each estimated probability.

**Result**

The smallest tested patient count with estimated collapse probability at least 0.50 was:

$$ \boxed{n_{50}=24} $$

At:

$$ n=23 $$

the estimated collapse probability was:

$$ \hat p=0.440 $$

with Wilson 95% CI:

$$ [0.373,\;0.509] $$

At:

$$ n=24 $$

the estimate became:

$$ \hat p=0.515 $$

with Wilson 95% CI:

$$ [0.446,\;0.583] $$

Thus:

$$ \boxed{n_{50}=24} $$

because 24 is the smallest tested load for which \(\hat p\ge0.50\).

No interpolation between 23 and 24 was performed.

**Analytical sanity check**

For the synthetic demand generator:

$$ M\sim U\{L,\ldots,H\} $$

and allocation is sampled conditionally on the generated maximum.

For a resource with severity-specific bounds \(L,H\):

$$ E[M]=\frac{L+H}{2} $$

and:

$$ E[A]=\frac{3L+H}{4} $$

Under the chosen severity mixture, expected oxygen allocation per patient was:

$$ E[A_{\text{O}_2}]=3.8375 $$

Therefore:

$$ 23(3.8375)=88.2625 $$

while:

$$ 24(3.8375)=92.10 $$

against an oxygen capacity of 90.

This does not analytically establish that collapse probability should equal 50% at 24 patients. It only provides an analytical workload sanity check consistent with the transition occurring near that region.

**Interpretation**

The experiment establishes a model-specific stochastic transition region rather than a universal hospital capacity threshold.

### Experiment 2: Isolated Resource Sensitivity

**Objective**

Measure how the estimated \(n_{50}\) changes when one resource capacity is perturbed while all other baseline resource capacities remain fixed.

The local finite-difference measure used was:

$$ \epsilon_k= \frac{ n_{50}(C+\Delta c_ke_k)-n_{50}(C) }{ \Delta c_k } $$

where:

\(C\) is the baseline resource vector,
\(e_k\) selects resource \(k\),
\(\Delta c_k\) is the perturbation,
\(n_{50}\) is recomputed after the isolated perturbation.

This is a discrete marginal sensitivity, not a dimensionless elasticity and not an absolute bottleneck ranking.

**Baseline**

$$ C=(14,90,14,35,120) $$

with:

$$ n_{50}=24 $$

**Perturbations and observed results**

| Resource | Baseline | Perturbation | New capacity | \(n_{50}\) | \(\Delta n_{50}\) | \(\epsilon_k\) |
|----------|----------|--------------|--------------|------------|-------------------|----------------|
| ICU beds | 14 | +1 | 15 | 23 | −1 | −1.000 |
| Oxygen | 90 | +9 | 99 | 26 | +2 | +0.222 |
| Ventilators | 14 | +1 | 15 | 23 | −1 | −1.000 |
| Nurses | 35 | +4 | 39 | 24 | 0 | 0.000 |
| Blood | 120 | +12 | 132 | 24 | 0 | 0.000 |

**Interpretation**

The oxygen perturbation increased the tested \(n_{50}\) by two patients, corresponding to:

$$ \epsilon_{\text{oxygen}} = \frac{2}{9} \approx0.222 $$

in this realization.

The nurse and blood perturbations produced no observed change in \(n_{50}\).

The negative ICU and ventilator sensitivities should not be interpreted as extra ICU capacity causing worse system behavior. Since \(n_{50}\) is itself estimated from finite Monte Carlo samples, the finite-difference result inherits sampling variability. The experiment therefore demonstrates the local behavior of the implemented estimator, rather than establishing a general monotonic ranking of resources.


### Experiment 3: Dynamic Staffing Sensitivity

**Objective**

Investigate how changes in staffing scale affect system behavior when resource capacity evolves over time rather than remaining fixed.

**Dynamic model**

The simulation uses:

$$ \Delta t=1\text{ hour} $$

over:

$$ H=168\text{ hours}=7\text{ days} $$

with:

$$ 2\text{ arrivals/hour} $$

so the configured arrival process generates:

$$ 168\times2=\boxed{336\text{ arrivals}} $$

The experiment varies only staffing scale.

**Staffing scenarios**

| Scenario | Normal | Handover | Weekend |
|----------|--------|----------|---------|
| Low staffing | 0.80× | 0.64× | 0.72× |
| Baseline | 1.00× | 0.80× | 0.90× |
| High staffing | 1.20× | 0.96× | 1.08× |

All other simulation parameters remain fixed.

**Analytical workload expectation**

Using the configured severity probabilities:

$$ E[N_{\text{mild}}]=336(0.60)=201.6 $$

$$ E[N_{\text{moderate}}]=336(0.15)=50.4 $$

$$ E[N_{\text{severe}}]=336(0.15)=50.4 $$

$$ E[N_{\text{critical}}]=336(0.10)=33.6 $$

Using the midpoint of each configured LOS interval:

$$ E[LOS] = 0.6(8)+0.15(16)+0.15(36)+0.1(72) $$

$$ =\boxed{19.8\text{ h}} $$

Hence the expected base workload is approximately:

$$ 336(19.8)=\boxed{6652.8\text{ patient-hours}} $$

before dynamic fatigue and related state-dependent effects.

Again, this is an analytical expectation, not the realized workload of the simulation.

**Observed simulation results**

**0.8× staffing**

The simulation produced:

- 21 completed patients
- 300 ED-overflow patients
- 13 ICU patients
- 2 ward patients
- overflow event rate = 2.256
- mean overflow = 73.89 h
- maximum overflow = 151 h
- fraction overflowed = 0.955
- Banker-unsafe timesteps = 49

**1.0× staffing**

The simulation produced:

- 44 completed patients
- 271 ED-overflow patients
- 14 ICU patients
- 7 ward patients
- overflow event rate = 2.286
- mean overflow = 65.42 h
- maximum overflow = 149 h
- fraction overflowed = 0.917
- Banker-unsafe timesteps = 4

**1.2× staffing**

The simulation produced:

- 216 completed patients
- 92 ED-overflow patients
- 14 ICU patients
- 14 ward patients
- overflow event rate = 1.565
- mean overflow = 31.40 h
- maximum overflow = 134 h
- fraction overflowed = 0.765
- Banker-unsafe timesteps = 0

**Comparative analysis**

Across the three tested staffing levels:

$$ \text{Completed} = 21\rightarrow44\rightarrow216 $$

while mean overflow duration changed:

$$ 73.89\rightarrow65.42\rightarrow31.40\text{ h} $$

From 0.8× to 1.2×, this corresponds to a relative reduction in mean overflow duration of approximately:

$$ \frac{73.89-31.40}{73.89}\times100 \approx\boxed{57.5\%} $$

The fraction of patients experiencing overflow changed:

$$ 0.955\rightarrow0.917\rightarrow0.765 $$

corresponding to an approximately:

$$ \boxed{19.9\%} $$

relative reduction from 0.8× to 1.2×.

Maximum overflow duration changed:

$$ 151\rightarrow149\rightarrow134\text{ h} $$

or approximately:

$$ \boxed{11.3\%} $$

lower from 0.8× to 1.2×.

Observed Banker-unsafe timesteps changed:

$$ 49\rightarrow4\rightarrow0 $$

The high-staffing scenario therefore experienced zero unsafe timesteps in this particular realization.

**Important observation**

The overflow event rate itself is not monotonic:

$$ 2.256\rightarrow2.286\rightarrow1.565 $$

Therefore, not every metric changes monotonically with staffing.

This is expected to some extent in a stochastic, path-dependent simulation and is precisely why the experiment should be interpreted through the complete set of system metrics rather than through a single output.


The three experiments progressively move from a relatively static stochastic question toward a dynamic systems question:

$$ \boxed{ \text{Load Sweep} \rightarrow \text{Capacity Sensitivity} \rightarrow \text{Dynamic Staffing} } $$


Observed results show substantially different trajectories across the 0.8×, 1.0×, and 1.2× scenarios, with the 1.2× realization producing 216 completed patients versus 21 at 0.8×, alongside lower overflow duration and zero observed Banker-unsafe timesteps.


## Limitations

- Banker's Algorithm assumes maximum demands are known in advance
- Five abstract resource types; ICU/ventilator are binary per patient; other units are integer model slots
- Phase 2 staffing, LOS, fatigue, and degradation parameters are model assumptions, not empirical clinical facts
- Acuity-based preemption is deferred
- National/epidemiological series are not this hospital's census; offline calibration uses a synthetic fixture when needed (labeled `SYNTHETIC_FALLBACK` / `SIMULATED_VALUE`)
- LOS calibration matches three published quantiles via quantile reconstruction (not MLE); Q25/Q75 are not guaranteed exact fits
- IID bootstrap of daily counts ignores serial correlation
- Staffing, nurse FTE, per-patient oxygen liters, and named-hospital ICU census are **MODEL_ASSUMPTION** or unused; they are not fake-calibrated
- n50 and discrete marginal sensitivity inherit Monte Carlo sampling error
- Stochastic results depend on sample size and configured demand profiles
- Simulation outputs are illustrative, not clinical predictions
- In-memory/SQLite rate limiting is suitable for low-traffic demo hosting only; multi-worker deployments across hosts may need centralized rate limiting

## License

Educational / research use. External data subject to [OWID license terms](https://github.com/owid/covid-19-data).