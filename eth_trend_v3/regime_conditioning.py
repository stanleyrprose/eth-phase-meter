from __future__ import annotations

import itertools
import numpy as np

from .dynamic_baseline import BaselineSpec, evaluate_baselines
from .hmm_production import causal_filter
from .probabilistic_research import evaluate_logistic


def align_states(reference_profiles: list[dict], new_profiles: list[dict], keys=("mean_return", "volatility")) -> dict[int, int]:
    if len(reference_profiles) != len(new_profiles):
        raise ValueError("state counts differ")
    k = len(reference_profiles)
    best = None
    best_cost = float("inf")
    for perm in itertools.permutations(range(k)):
        cost = 0.0
        for i, j in enumerate(perm):
            for key in keys:
                a = float(reference_profiles[i].get(key, 0.0))
                b = float(new_profiles[j].get(key, 0.0))
                cost += (a - b) ** 2
        if cost < best_cost:
            best_cost = cost
            best = perm
    return {j: i for i, j in enumerate(best)}


def assert_causal_filter(params: dict, x: np.ndarray, extension: np.ndarray, atol: float = 1e-10) -> bool:
    base = causal_filter(x, params)
    ext = causal_filter(np.vstack([x, extension]), params)
    if not np.allclose(base, ext[:len(base)], atol=atol, rtol=0):
        raise AssertionError("HMM posterior is not causal")
    return True


def shrunk_regime_probability(y, regimes, current_regime, prior_strength: float = 20.0) -> float:
    y = np.asarray(y, dtype=float)
    r = np.asarray(regimes)
    global_p = float(y.mean()) if len(y) else .5
    mask = r == current_regime
    n = int(mask.sum())
    if n == 0:
        return global_p
    regime_p = float(y[mask].mean())
    lam = n / (n + prior_strength)
    return float(lam * regime_p + (1 - lam) * global_p)


def regime_latency(regimes: list[str], stable_flags: list[bool]) -> dict:
    delays = []
    last = regimes[0] if regimes else None
    pending = None
    for i, (r, stable) in enumerate(zip(regimes, stable_flags)):
        if r != last and pending is None:
            pending = i
        if pending is not None and stable and r != last:
            delays.append(i - pending)
            last = r
            pending = None
    return {"switches_measured": len(delays), "mean_delay_bars": float(np.mean(delays)) if delays else None, "delays": delays}


def compare_regime_conditioning(folds, *, horizon_bars: int, posterior_features: list[str] | None = None, bootstrap_reps: int = 300) -> dict:
    baseline_specs = [BaselineSpec("expanding"), BaselineSpec("regime"), BaselineSpec("shrunk-regime", prior_strength=20.0)]
    baseline_result = evaluate_baselines(folds, baseline_specs, horizon_bars=horizon_bars, bootstrap_reps=bootstrap_reps)
    soft = None
    if posterior_features:
        soft = evaluate_logistic(folds, posterior_features, horizon_bars=horizon_bars, bootstrap_reps=bootstrap_reps)
    return {
        "baseline_comparison": baseline_result,
        "soft_posterior": soft,
        "decision": "HMM_PREDICTIVE_CANDIDATE" if ((baseline_result.get("winner") or "") != "expanding" or (soft or {}).get("passes_incremental_gate")) else "HMM_DESCRIPTIVE_ONLY",
        "note": "Regime inputs must be causal and state-aligned before this comparison is considered valid.",
    }
