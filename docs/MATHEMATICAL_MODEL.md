# Mathematical model (executable)

This document matches the code in `pandemic_bankers/`. Symbols are defined as used. The Banker's safety procedure is unchanged from Dijkstra's algorithm.

## Resource indices and time

- \(j = 1,\ldots,m\): resource type (ICU beds, oxygen units, ventilators, nurses, blood units).
- \(i\): patient index among those currently in the Banker's tables.
- \(t\): elapsed hours. Calendar convention: \(t=0\) is Monday 00:00.
- \(\Delta t\): time step in hours (default 1).
- \(C_{j,t}\): total capacity of resource \(j\) at time \(t\) (integer).
- \(A_{i,j,t}\): allocation of resource \(j\) to in-care patient \(i\) at \(t\).
- \(W_{j,t}\): work / available units of resource \(j\) at \(t\).
- \(M_{i,j}\): maximum claim of patient \(i\) for resource \(j\).
- \(N_{i,j}\): remaining need.

In the static (Phase 1) snapshot, time is omitted: \(C_j\), \(A_{i,j}\), \(W_j\).

---

## 1. Resource conservation

\[
C_{j,t} = W_{j,t} + \sum_{i} A_{i,j,t}
\]

for every resource \(j\) and time \(t\). Holdings are never silently destroyed. If \(C_{j,t}\) would fall below current allocated totals, lowest-priority in-care patients are overflowed explicitly (allocation released) before the new \(C_{j,t}\) is applied.

---

## 2. Need

\[
N_{i,j} = M_{i,j} - A_{i,j}
\]

Invariants: \(0 \le A_{i,j} \le M_{i,j}\) and \(N_{i,j} \ge 0\).

---

## 3. Banker safety condition

Work is initialized \(W^{(0)} = W\) (current available). A sequence \(\sigma\) of unfinished patients is safe if, for each position \(k\),

\[
N_{\sigma(k)} \le W^{(k-1)}
\]

componentwise (every resource).

---

## 4. Work update

When patient \(\sigma(k)\) is declared able to finish,

\[
W^{(k)} = W^{(k-1)} + A_{\sigma(k)}
\]

(componentwise). The state is **SAFE** if every patient appears in \(\sigma\); **UNSAFE** otherwise.

Admission failure (a new patient's initial allocation exceeds available) is recorded separately from UNSAFE. **Collapse** in the Monte Carlo experiment is admission failure **or** UNSAFE.

---

## 5. Monte Carlo estimator

For a fixed patient count \(n\) and \(T\) independent trials, let \(K_n\) be the number of collapsing trials.

\[
\hat p_n = \frac{K_n}{T}
\]

This is a Monte Carlo estimate under a fixed generative model, not a hospital forecast.

---

## 6. Wilson score interval

With \(z = 1.96\) (nominal 95%) and \(n=T\) trials,

\[
\hat p = \frac{K}{T},\qquad
z^2 = z\cdot z
\]

\[
\text{centre} = \frac{\hat p + z^2/(2T)}{1 + z^2/T}
\]

\[
\text{half} = \frac{z}{1 + z^2/T}
\sqrt{\frac{\hat p(1-\hat p)}{T} + \frac{z^2}{4T^2}}
\]

\[
\mathrm{CI} = \bigl[\max(0,\ \text{centre}-\text{half}),\ \min(1,\ \text{centre}+\text{half})\bigr]
\]

The interval describes binomial sampling error of \(\hat p\) under a fixed model.

---

## 7. \(n_{50}\)

\[
n_{50} = \min\{\, n \text{ tested} : \hat p_n \ge 0.50 \,\}
\]

Discrete; no interpolation. If no tested \(n\) reaches 0.50, \(n_{50}\) is undefined (`null`).

---

## 8. Discrete marginal patient-capacity sensitivity

For resource \(k\), unit vector \(e_k\), and integer perturbation \(\Delta c_k \ne 0\),

\[
\varepsilon_k =
\frac{
n_{50}(C + \Delta c_k\, e_k) - n_{50}(C)
}{
\Delta c_k
}
\]

\(\varepsilon_k\) is a **local discrete finite-difference sensitivity** (additional tested patients per additional resource unit near the baseline). It is not standard dimensionless elasticity. \(\Delta c_k = 0\) is undefined.

---

## 9. Dynamic capacity

At each time \(t\), after overflow adjustments,

\[
W_{j,t} = C_{j,t} - \sum_{i} A_{i,j,t}
\]

Nurse capacity (model assumption) is

\[
C_{\text{nurse}}(t) = \mathrm{round}\bigl(C_{\text{base}} \cdot m_{\text{shift}}(t) \cdot m_{\text{weekend}}(t)\bigr)
\]

with \(m_{\text{shift}}, m_{\text{weekend}}\) from configuration.

Fatigue (model assumption): if fatigued, \(\mathrm{LOS}_{\text{eff}} = \mathrm{LOS}_{\text{base}}(1+\alpha)\).

---

## 10. Arrival model

Let \(X_d\) be the ingested daily count series (UK national admissions, OWID GBR weekly admissions / 7, or a labeled synthetic fixture). Dispersion diagnostic:

\[
D = \frac{\mathrm{Var}(X)}{\mathrm{Mean}(X)}
\]

\(D \approx 1\): Poisson-like; \(D>1\): overdispersion; \(D<1\): underdispersion. This is a diagnostic, not a proof.

Poisson(\(\lambda\)): \(\mathrm{E}[X]=\mathrm{Var}[X]=\lambda\). Sampling uses Knuth's method with exact recursive split for large \(\lambda\) (no Normal approximation).

Negative binomial **NB2 / Gamma–Poisson** (not Bernoulli-trials \(n,p\)):

\[
\lambda \sim \mathrm{Gamma}(\theta,\ \text{scale}=\mu/\theta),\qquad
X\mid\lambda \sim \mathrm{Poisson}(\lambda)
\]

\[
\mathrm{E}[X]=\mu,\qquad \mathrm{Var}[X]=\mu + \mu^2/\theta
\]

Family selection: negative binomial if \(D>1.05\) **and** NB AIC is lower; otherwise Poisson.

**Hospital-scale intensity** \(\lambda_0\) is the configured `arrivals_per_step` (**MODEL_ASSUMPTION**). The national daily mean / 24 is **not** this hospital's \(\lambda_0\).

**Time dependence (Model C dynamic only):**

\[
r_d = \frac{\mathrm{mean}(X \mid \mathrm{weekday}=d)}{\mathrm{mean}(X)},\qquad d=0,\ldots,6
\]

\[
\lambda(t) = \lambda_0 \cdot r_{\mathrm{dow}(t)},\qquad \mathrm{dow}(t)=(t\ \mathrm{div}\ 24)\bmod 7
\]

Month/outbreak factors are not multiplied into \(\lambda(t)\) unless a supporting series is actually used.

Models A and B dynamic runs use configured constant (or Poisson) arrivals, not \(\lambda(t)\).

---

## 11. LOS calibration method

Published quartiles \(Q_{25}, Q_{50}, Q_{75}\) (Rees et al. 2020, outside China) are **REAL_OBSERVATION** summaries, not patient-level records.

Candidate families (Lognormal, Weibull, Gamma) are scored by **quantile reconstruction SSE**:

\[
\mathrm{SSE} = \sum (Q^{\mathrm{model}} - Q^{\mathrm{observed}})^2
\]

over \(\{0.25, 0.50, 0.75\}\). This is **not** maximum-likelihood fitting and **not** a formal GOF test.

Gamma predicted quantiles use the **Wilson–Hilferty** approximation, so Gamma's SSE is not on identical exact-quantile footing as Lognormal/Weibull.

Selected family is sampled in the **dynamic Model C** run (days \(\times 24\) hours). Static Banker's \(n\)-sweep does not use LOS.

---

## 12. External-signal transformation

Let \(X\) be the 14-day mean of OWID global `new_cases_smoothed` when a live fetch succeeds.

\[
f(X) = \mathrm{clip}\bigl(X / X_{\mathrm{ref}},\ f_{\min},\ f_{\max}\bigr)
\]

with \(X_{\mathrm{ref}}=50000\), \(f_{\min}=0.5\), \(f_{\max}=3.0\) (**MODEL_ASSUMPTION**: normalization and bounds, not hospital truth). \(f\) is non-decreasing in \(X\) before clipping; clipping saturates.

Monte Carlo patient ceiling:

\[
N' = \mathrm{clip}\bigl(\mathrm{round}(N \cdot f(X)),\ 5,\ 200\bigr)
\]

This is **not** empirically learned. Fallback when fetch fails: \(f=1\) and status `SYNTHETIC_FALLBACK`.

Public case counts are **not** ICU occupancy, hospital census, ventilator occupancy, or nurse staffing of this model hospital.

---

## Experiment families

| Family | What runs | Metrics |
|--------|-----------|---------|
| **Static Banker collapse** | Phase 1 n-sweep. Model A independent demand; B and C identical severity-conditioned demand | \(\hat p_n\), Wilson CI, \(n_{50}\) |
| **Dynamic empirically informed simulation** | Phase 2 time model. Model C uses calibrated family + \(\lambda(t)\) + quantile LOS | overflow rate/duration, fatigue exposure, utilization |

Do not label the static n-sweep as a fully calibrated collapse model.

---

## Data availability statuses

- `CURRENT_EXTERNAL` — live fetch succeeded this run.
- `CACHED_EMPIRICAL` — on-disk `REAL_OBSERVATION` snapshot.
- `SYNTHETIC_FALLBACK` — labeled fixture; not hospital observations.

Quantity classifications: `REAL_OBSERVATION`, `DERIVED_PARAMETER`, `MODEL_ASSUMPTION`, `SIMULATED_VALUE`.

---

## Dependence (no copula)

Copula modeling was considered but not implemented because available data does not support reliable estimation of patient-level joint dependence.

---

## Bootstrap limitation

The arrival-mean interval is an **IID percentile bootstrap**. It does not preserve time-series dependence. Block bootstrap is not used.
