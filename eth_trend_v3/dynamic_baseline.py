from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Mapping, Sequence

import numpy as np

from .research_contract import parse_utc
from .research_metrics import brier, brier_skill_score, calibration_error, log_loss, moving_block_delta_brier_ci


@dataclass(frozen=True)
class BaselineSpec:
    name: str
    window_days: int | None = None
    half_life_days: float | None = None
    prior_strength: float = 20.0
    regime_key: str = "regime"


def _targets(rows):
    return np.asarray([int(r["target_up"]) for r in rows], dtype=int)


def _times(rows):
    return [parse_utc(r.get("feature_time", r.get("timestamp"))) for r in rows]


def _global_rate(y: np.ndarray) -> float:
    return float(y.mean()) if len(y) else 0.5


def _regime_probability(train, y, current_regime, spec: BaselineSpec) -> float:
    global_p = _global_rate(y)
    idx = [i for i, row in enumerate(train) if row.get(spec.regime_key) == current_regime and current_regime is not None]
    if not idx:
        return global_p
    regime_p = float(y[np.asarray(idx, dtype=int)].mean())
    if spec.name == "regime":
        return regime_p
    n = len(idx)
    lam = n / (n + max(float(spec.prior_strength), 1e-9))
    return float(lam * regime_p + (1.0 - lam) * global_p)


def predict_baseline(train: Sequence[Mapping[str, Any]], test: Sequence[Mapping[str, Any]], spec: BaselineSpec) -> np.ndarray:
    if not train:
        raise ValueError("baseline requires training observations")
    y = _targets(train)
    times = _times(train)
    p = _global_rate(y)
    if spec.name == "expanding":
        return np.full(len(test), np.clip(p, 1e-6, 1 - 1e-6), dtype=float)
    if spec.name == "rolling":
        if not spec.window_days:
            raise ValueError("rolling baseline requires window_days")
        cutoff = max(times) - timedelta(days=spec.window_days)
        mask = np.asarray([t >= cutoff for t in times])
        if mask.any():
            p = float(y[mask].mean())
        return np.full(len(test), np.clip(p, 1e-6, 1 - 1e-6), dtype=float)
    if spec.name == "ewma":
        if not spec.half_life_days:
            raise ValueError("ewma baseline requires half_life_days")
        age = np.asarray([(max(times) - t).total_seconds() / 86400 for t in times])
        w = np.exp(-np.log(2) * age / spec.half_life_days)
        p = float(np.average(y, weights=w))
        return np.full(len(test), np.clip(p, 1e-6, 1 - 1e-6), dtype=float)
    if spec.name in {"regime", "shrunk-regime"}:
        values = [_regime_probability(train, y, row.get(spec.regime_key), spec) for row in test]
        return np.clip(np.asarray(values, dtype=float), 1e-6, 1 - 1e-6)
    raise ValueError(f"unsupported baseline: {spec.name}")


def default_specs(include_regime: bool = True):
    specs = [BaselineSpec("expanding")]
    specs += [BaselineSpec("rolling", window_days=d) for d in (90, 180, 365)]
    specs += [BaselineSpec("ewma", half_life_days=d) for d in (30, 60, 90, 180)]
    if include_regime:
        specs += [BaselineSpec("regime"), BaselineSpec("shrunk-regime", prior_strength=20.0)]
    return specs


def _spec_key(spec: BaselineSpec) -> str:
    if spec.window_days:
        return f"{spec.name}-{spec.window_days}d"
    if spec.half_life_days:
        return f"{spec.name}-{int(spec.half_life_days)}d"
    if spec.name == "shrunk-regime":
        return f"{spec.name}-prior{spec.prior_strength:g}"
    return spec.name


def evaluate_baselines(folds, specs=None, *, horizon_bars: int, bootstrap_reps: int = 500) -> dict:
    specs = specs or default_specs()
    store = {_spec_key(s): {"p": [], "y": [], "fold_brier": [], "spec": s} for s in specs}
    for fold in folds:
        train, test = fold["train"], fold["test"]
        y = _targets(test)
        for key, item in store.items():
            p = predict_baseline(train, test, item["spec"])
            item["p"].extend(p.tolist())
            item["y"].extend(y.tolist())
            item["fold_brier"].append(brier(y, p))
    if not any(v["y"] for v in store.values()):
        return {"available": False, "reason": "NO_VALID_FOLDS"}

    base = store["expanding"]
    base_y = np.asarray(base["y"])
    base_p = np.asarray(base["p"])
    metrics = {}
    sensitivity_blocks = sorted({max(1, int(round(horizon_bars * m))) for m in (0.5, 1.0, 1.5)})
    for key, item in store.items():
        y = np.asarray(item["y"])
        p = np.asarray(item["p"])
        sensitivity = {
            str(block): moving_block_delta_brier_ci(y, p, base_p, block, reps=bootstrap_reps)
            for block in sensitivity_blocks
        }
        main_ci = sensitivity[str(max(1, int(horizon_bars)))]
        metrics[key] = {
            "brier": brier(y, p),
            "brier_skill_vs_expanding": brier_skill_score(y, p, base_p),
            "log_loss": log_loss(y, p),
            "calibration_error": calibration_error(y, p),
            "fold_brier": item["fold_brier"],
            "delta_brier_ci_vs_expanding": main_ci,
            "block_sensitivity": sensitivity,
            "oos_n": len(y),
        }
        lows = [v["low"] for v in sensitivity.values() if v]
        metrics[key]["stable_positive_vs_expanding"] = bool(key != "expanding" and lows and min(lows) > 0)

    # Conservative champion rule: a more complex baseline only displaces expanding
    # if improvement survives all pre-registered block-length sensitivity checks.
    eligible = [k for k, m in metrics.items() if m.get("stable_positive_vs_expanding")]
    if eligible:
        winner = min(eligible, key=lambda k: metrics[k]["brier"])
    else:
        winner = "expanding"
    ranking = sorted(metrics, key=lambda k: (metrics[k]["brier"], 0 if k == "expanding" else 1))
    return {
        "available": True,
        "winner": winner,
        "ranking": ranking,
        "metrics": metrics,
        "selection_rule": "non-expanding candidates must beat expanding with positive CI lower bound across 0.5H/1.0H/1.5H block sensitivity; otherwise expanding remains champion",
    }
