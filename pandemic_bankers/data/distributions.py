"""
Distribution fitting and sampling used by Phase 3 calibration.

Stdlib only. These helpers are statistical tools, not clinical facts.
"""

from __future__ import annotations

import math
import random
from typing import Sequence


def mean_var(xs: Sequence[float]) -> tuple[float, float]:
    n = len(xs)
    if n == 0:
        raise ValueError("Empty sample.")
    mu = sum(xs) / n
    if n == 1:
        return mu, 0.0
    var = sum((x - mu) ** 2 for x in xs) / (n - 1)
    return mu, var


def dispersion_index(xs: Sequence[float]) -> float:
    mu, var = mean_var(xs)
    if mu == 0:
        return float("inf") if var > 0 else 0.0
    return var / mu


def poisson_pmf(k: int, lam: float) -> float:
    if k < 0 or lam < 0:
        return 0.0
    if lam == 0:
        return 1.0 if k == 0 else 0.0
    # log pmf for stability
    logp = -lam + k * math.log(lam) - math.lgamma(k + 1)
    return math.exp(logp)


def nbinom_pmf(k: int, mu: float, size: float) -> float:
    """
    Negative binomial: mean mu, size k (Gamma-Poisson mixture).
    Var = mu + mu^2/size.
    """
    if k < 0 or mu < 0 or size <= 0:
        return 0.0
    p = size / (size + mu)
    # P(X=k) = C(k+size-1, k) (1-p)^k p^size
    logp = (
        math.lgamma(k + size)
        - math.lgamma(k + 1)
        - math.lgamma(size)
        + size * math.log(p)
        + k * math.log(1.0 - p)
    )
    return math.exp(logp)


def poisson_loglik(xs: Sequence[int], lam: float) -> float:
    return sum(math.log(max(poisson_pmf(int(x), lam), 1e-300)) for x in xs)


def nbinom_loglik(xs: Sequence[int], mu: float, size: float) -> float:
    return sum(math.log(max(nbinom_pmf(int(x), mu, size), 1e-300)) for x in xs)


def aic(loglik: float, n_params: int) -> float:
    return 2 * n_params - 2 * loglik


def fit_poisson(xs: Sequence[int]) -> dict:
    mu, var = mean_var(xs)
    ll = poisson_loglik(xs, mu)
    return {
        "family": "poisson",
        "mean": mu,
        "variance": var,
        "lambda": mu,
        "loglik": ll,
        "aic": aic(ll, 1),
        "n_params": 1,
    }


def fit_nbinom(xs: Sequence[int]) -> dict:
    mu, var = mean_var(xs)
    if var <= mu + 1e-12:
        size = float("inf")
        ll = poisson_loglik(xs, mu)
        return {
            "family": "nbinom",
            "mean": mu,
            "variance": var,
            "mu": mu,
            "size": size,
            "loglik": ll,
            "aic": aic(ll, 2),
            "n_params": 2,
            "note": "Variance <= mean; NB size is infinite (Poisson limit).",
            "overdispersed": False,
            "parameterization": (
                "NB2 / Gamma-Poisson mixture: X|λ ~ Poisson(λ), "
                "λ ~ Gamma(shape=size, scale=μ/size); E[X]=μ, Var[X]=μ + μ²/size."
            ),
        }
    size = mu * mu / (var - mu)
    ll = nbinom_loglik(xs, mu, size)
    return {
        "family": "nbinom",
        "mean": mu,
        "variance": var,
        "mu": mu,
        "size": size,
        "loglik": ll,
        "aic": aic(ll, 2),
        "n_params": 2,
            "overdispersed": True,
            "parameterization": (
                "NB2 / Gamma-Poisson mixture: X|λ ~ Poisson(λ), "
                "λ ~ Gamma(shape=size, scale=μ/size); "
                "E[X]=μ, Var[X]=μ + μ²/size. size is the dispersion parameter, not Bernoulli trials."
            ),
    }


def chi_square_gof(
    xs: Sequence[int],
    pmf_fn,
    n_params: int,
) -> dict:
    """Pearson chi-square on integer counts; bins with E<5 are merged."""
    n = len(xs)
    if n == 0:
        return {"statistic": 0.0, "df": 0, "bins": 0}
    xmax = max(xs)
    observed = [0] * (xmax + 1)
    for x in xs:
        observed[int(x)] += 1
    expected = [n * pmf_fn(k) for k in range(xmax + 1)]
    tail_p = max(0.0, 1.0 - sum(expected[k] / n for k in range(xmax + 1)))
    expected.append(n * tail_p)
    observed.append(0)

    o_m: list[float] = []
    e_m: list[float] = []
    acc_o = 0.0
    acc_e = 0.0
    for o, e in zip(observed, expected):
        acc_o += o
        acc_e += e
        if acc_e >= 5:
            o_m.append(acc_o)
            e_m.append(acc_e)
            acc_o = 0.0
            acc_e = 0.0
    if acc_e > 0 or acc_o > 0:
        if e_m:
            e_m[-1] += acc_e
            o_m[-1] += acc_o
        else:
            o_m.append(acc_o)
            e_m.append(max(acc_e, 1e-9))

    stat = sum((o - e) ** 2 / e for o, e in zip(o_m, e_m) if e > 0)
    df = max(len(o_m) - 1 - n_params, 1)
    return {"statistic": stat, "df": df, "bins": len(o_m)}


def compare_count_models(xs: Sequence[int]) -> dict:
    mu, var = mean_var(xs)
    disp = dispersion_index(xs)
    pois = fit_poisson(xs)
    nb = fit_nbinom(xs)
    pois["gof"] = chi_square_gof(xs, lambda k: poisson_pmf(k, pois["lambda"]), 1)
    if nb.get("overdispersed"):
        nb["gof"] = chi_square_gof(
            xs, lambda k, _nb=nb: nbinom_pmf(k, _nb["mu"], _nb["size"]), 2
        )
    else:
        nb["gof"] = pois["gof"]

    chosen = "nbinom" if nb.get("overdispersed") and nb["aic"] < pois["aic"] else "poisson"
    return {
        "n": len(xs),
        "mean": mu,
        "variance": var,
        "dispersion": disp,
        "overdispersion": disp > 1.05,
        "poisson": pois,
        "nbinom": nb,
        "chosen_family": chosen,
        "selection_rule": (
            "Choose negative binomial if sample variance exceeds the mean "
            "(dispersion > 1.05) and NB AIC is lower; otherwise Poisson. "
            "Poisson is not assumed a priori. Dispersion D = Var/Mean is a diagnostic, not a proof."
        ),
        "nbinom_parameterization": (
            "NB2: mean μ, size θ; Var = μ + μ²/θ. Sampling uses Gamma-Poisson "
            "(λ ~ Gamma(θ, scale=μ/θ), X|λ ~ Poisson(λ))."
        ),
    }


def poisson_sample(rng: random.Random, lam: float) -> int:
    """
    Exact sample from Poisson(lambda).

    Knuth's method for lambda < 20. For larger lambda, split:
    Poisson(a+b) = Poisson(a) + Poisson(b), which is exact and avoids
    exp(-lambda) underflow. No Normal approximation is used.
    """
    if lam <= 0:
        return 0
    if lam < 20.0:
        L = math.exp(-lam)
        k = 0
        p = 1.0
        while p > L:
            k += 1
            p *= rng.random()
        return k - 1
    half = lam * 0.5
    return poisson_sample(rng, half) + poisson_sample(rng, lam - half)


def nbinom_sample(rng: random.Random, mu: float, size: float) -> int:
    if mu <= 0:
        return 0
    if not math.isfinite(size) or size > 1e8:
        return poisson_sample(rng, mu)
    # Gamma-Poisson mixture: lambda ~ Gamma(size, scale=mu/size)
    lam = rng.gammavariate(size, mu / size)
    return poisson_sample(rng, lam)


def _norm_ppf(p: float) -> float:
    """Acklam inverse-normal approximation for p in (0,1)."""
    if p <= 0.0:
        return -8.0
    if p >= 1.0:
        return 8.0
    a = [
        -3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
        1.383577509590705e02, -3.066479806614716e01, 2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
        6.680131188771972e01, -1.328068155288826e01,
    ]
    c = [
        -7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
        -2.821206333459723e00, 3.543889200727778e00, 4.374664141464858e00,
    ]
    d = [
        7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
        3.754408661907416e00,
    ]
    plow = 0.02425
    phigh = 1 - plow
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    q = p - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q
    ) / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def lognormal_quantiles(mu: float, sigma: float) -> dict:
    def q(p: float) -> float:
        return math.exp(mu + sigma * _norm_ppf(p))

    return {"q25": q(0.25), "median": q(0.5), "q75": q(0.75)}


def weibull_quantiles(shape: float, scale: float) -> dict:
    def q(p: float) -> float:
        return scale * ((-math.log(1.0 - p)) ** (1.0 / shape))

    return {"q25": q(0.25), "median": q(0.5), "q75": q(0.75)}


def gamma_quantiles(shape: float, scale: float) -> dict:
    """Wilson–Hilferty approximation to Gamma quantiles."""
    def q(p: float) -> float:
        z = _norm_ppf(p)
        a = shape
        inner = 1.0 - 1.0 / (9.0 * a) + z * math.sqrt(1.0 / (9.0 * a))
        return max(1e-9, scale * a * (inner ** 3))

    return {"q25": q(0.25), "median": q(0.5), "q75": q(0.75)}


def quantile_sse(pred: dict, target: dict) -> float:
    """Quantile reconstruction SSE = Σ (Q_model - Q_observed)^2 for Q25, Q50, Q75."""
    return sum((pred[k] - target[k]) ** 2 for k in ("q25", "median", "q75"))


def fit_los_from_quantiles(q25: float, median: float, q75: float) -> dict:
    """
    Quantile-based distribution reconstruction from published Q25, Q50, Q75.

    This is NOT patient-level maximum-likelihood fitting and NOT a formal
    goodness-of-fit test. Candidate families are scored by quantile
    reconstruction SSE on those three points only.

    Parameter sources (closed-form reconstruction, no patient-level MLE):
      Lognormal: mu = log(Q50); sigma = (log(Q75)-log(Q25)) / (2 * z_0.75)
                 with z_0.75 = Φ^{-1}(0.75) ≈ 0.67448975. Q50 is matched by
                 construction; Q25/Q75 are not guaranteed to equal the published
                 quartiles unless the data are truly lognormal.
      Weibull: shape from Q75/Q25 ratio; scale from the median. This is a
               quantile-based reconstruction; predicted Q25/Q75 need not match
               the published quartiles unless the data follow Weibull.
      Gamma: shape/scale from Tukey mean (Q25+2*Q50+Q75)/4 and IQR/1.349
             variance proxy. Predicted quantiles use the Wilson–Hilferty
             approximation, so Gamma SSE is not on identical footing with the
             closed-form Lognormal/Weibull quantile maps.
    """
    target = {"q25": q25, "median": median, "q75": q75}
    candidates = []

    # Lognormal
    mu = math.log(median)
    sigma = (math.log(q75) - math.log(q25)) / (2 * 0.67448975)
    ln_pred = lognormal_quantiles(mu, max(sigma, 1e-6))
    candidates.append({
        "family": "lognormal",
        "params": {"mu": mu, "sigma": sigma},
        "predicted": ln_pred,
        "sse": quantile_sse(ln_pred, target),
    })

    # Weibull from q25/q75 ratio
    ratio = q75 / q25
    inner = math.log(-math.log(0.25)) - math.log(-math.log(0.75))
    shape = inner / math.log(ratio) if ratio > 1 else 1.0
    scale = median / ((math.log(2.0)) ** (1.0 / shape))
    wb_pred = weibull_quantiles(shape, scale)
    candidates.append({
        "family": "weibull",
        "params": {"shape": shape, "scale": scale},
        "predicted": wb_pred,
        "sse": quantile_sse(wb_pred, target),
    })

    # Gamma via Tukey mean and IQR-as-sigma approximation
    tukey_mean = (q25 + 2 * median + q75) / 4.0
    sigma_hat = (q75 - q25) / 1.349
    var_hat = max(sigma_hat ** 2, 1e-6)
    g_shape = (tukey_mean ** 2) / var_hat
    g_scale = var_hat / tukey_mean
    ga_pred = gamma_quantiles(g_shape, g_scale)
    candidates.append({
        "family": "gamma",
        "params": {"shape": g_shape, "scale": g_scale},
        "predicted": ga_pred,
        "sse": quantile_sse(ga_pred, target),
        "moment_note": "shape/scale from Tukey mean and IQR/1.349 variance proxy",
    })

    chosen = min(candidates, key=lambda c: c["sse"])
    return {
        "target_quantiles": target,
        "candidates": candidates,
        "chosen_family": chosen["family"],
        "chosen": chosen,
        "comparison_metric": "quantile_reconstruction_sse",
        "comparison_formula": "SSE = (Q25_m-Q25_o)^2 + (Q50_m-Q50_o)^2 + (Q75_m-Q75_o)^2",
        "not_a_gof_test": True,
        "selection_rule": (
            "Minimum quantile reconstruction SSE on published 0.25/0.50/0.75. "
            "Not a Kolmogorov–Smirnov, chi-square, or likelihood-ratio GOF test."
        ),
    }


def sample_lognormal(rng: random.Random, mu: float, sigma: float) -> float:
    return math.exp(rng.gauss(mu, sigma))


def sample_weibull(rng: random.Random, shape: float, scale: float) -> float:
    """Python weibullvariate(alpha=shape, beta=scale): CDF = 1 - exp(-(x/scale)^shape)."""
    return rng.weibullvariate(shape, scale)


def sample_gamma(rng: random.Random, shape: float, scale: float) -> float:
    return rng.gammavariate(shape, scale)


def sample_fitted_los(rng: random.Random, fit: dict) -> float:
    fam = fit["chosen_family"]
    p = fit["chosen"]["params"]
    if fam == "lognormal":
        return sample_lognormal(rng, p["mu"], p["sigma"])
    if fam == "weibull":
        return sample_weibull(rng, p["shape"], p["scale"])
    return sample_gamma(rng, p["shape"], p["scale"])


def pearson_corr(xs: Sequence[float], ys: Sequence[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 3:
        return float("nan")
    mx, vx = mean_var(xs)
    my, vy = mean_var(ys)
    if vx <= 0 or vy <= 0:
        return float("nan")
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(len(xs))) / (len(xs) - 1)
    return cov / math.sqrt(vx * vy)


def bootstrap_mean_ci(
    xs: Sequence[float],
    rng: random.Random,
    n_boot: int = 400,
    alpha: float = 0.05,
) -> tuple[float, float, float]:
    """
    IID percentile bootstrap of the sample mean.

    Each replicate draws n observations independently with replacement.
    This does NOT preserve serial correlation. If xs is a daily time series,
    the interval is an IID-bootstrap estimate of uncertainty in the mean,
    not a time-series-valid confidence interval.
    """
    n = len(xs)
    if n == 0:
        return 0.0, 0.0, 0.0
    means = []
    for _ in range(n_boot):
        sample = [xs[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int(alpha / 2 * n_boot)]
    hi = means[min(n_boot - 1, int((1 - alpha / 2) * n_boot))]
    return sum(xs) / n, lo, hi
