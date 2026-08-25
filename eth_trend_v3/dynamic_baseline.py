from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Mapping, Sequence

import numpy as np

from .research_contract import parse_utc
from .research_metrics import (
    brier,
    brier_skill_score,
    calibration_error,
    log_loss,
    moving_block_delta_brier_ci,
)


@dataclass(frozen=True)
class BaselineSpec:
    name: str
    window_days: int | None = None
    half_life_days: float | None = None
    regime_key: str = "regime"
    prior_strength: float = 20.0
    min_regime_count: int = 20

    @property
    def key(self) -> str:
        if self.name == "rolling":
            return f"rolling-{self.window_days}d"
        if self.name == "ewma":
            return f"ewma-{int(self.half_life_days or 0)}d"
        if self.name == "hard_regime":
            return f"hard-regime-min{self.min_regime_count}"
        if self.name == "shrunk_regime":
            return f"shrunk-regime-prior{self.prior_strength:g}"
        return self.name


def _targets(rows):
    return np.asarray([int(r["target_up"]) for r in rows], dtype=int)


def _times(rows):
    return [parse_utc(r.get("feature_time", r.get("timestamp"))) for r in rows]


def _global_probability(y: np.ndarray) -> float:
    return float(np.clip(float(y.mean()), 1e-6, 1 - 1e-6))


def _regime_probabilities(
    train: Sequence[Mapping[str, Any]],
    test: Sequence[Mapping[str, Any]],
    spec: BaselineSpec,
) -> np.ndarray:
    y = _targets(train)
    global_p = _global_probability(y)
    train_regimes = [r.get(spec.regime_key) for r in train]
    out = []
    for row in test:
        current = row.get(spec.regime_key)
        idx = [i for i, regime in enumerate(train_regimes) if current is not None and regime == current]
        n = len(idx)
        if not n:
            out.append(global_p)
            continue
        regime_p = float(np.mean(y[idx]))
        if spec.name == "hard_regime":
            p = regime_p if n >= spec.min_regime_count else global_p
        else:
            lam = n / (n + max(float(spec.prior_strength), 1e-9))
            p = lam * regime_p + (1 - lam) * global_p
        out.append(float(np.clip(p, 1e-6, 1 - 1e-6)))
    return np.asarray(out, dtype=float)


def predict_baseline(
    train: Sequence[Mapping[str, Any]],
    test: Sequence[Mapping[str, Any]],
    spec: BaselineSpec,
) -> np.ndarray:
    if not train:
        raise ValueError("baseline requires training observations")
    y = _targets(train)
    times = _times(train)
    p = _global_probability(y)

    if spec.name == "expanding":
        pass
    elif spec.name == "rolling":
        if not spec.window_days:
            raise ValueError("rolling baseline requires window_days")
        cutoff = max(times) - timedelta(days=spec.window_days)
        mask = np.asarray([t >= cutoff for t in times])
        if mask.any():
            p = _global_probability(y[mask])
    elif spec.name == "ewma":
        if not spec.half_life_days:
            raise ValueError("ewma baseline requires half_life_days")
        age = np.asarray([(max(times) - t).total_seconds() / 86400 for t in times])
        weights = np.exp(-np.log(2) * age / spec.half_life_days)
        p = float(np.clip(np.average(y, weights=weights), 1e-6, 1 - 1e-6))
    elif spec.name in {"hard_regime", "shrunk_regime"}:
        return _regime_probabilities(train, test, spec)
    else:
        raise ValueError(f"unsupported baseline: {spec.name}")

    return np.full(len(test), p, dtype=float)


def default_specs(include_regime: bool = True):
    specs = [BaselineSpec("expanding")]
    specs += [BaselineSpec("rolling", window_days=d) for d in (90, 180, 365)]
    specs += [BaselineSpec("ewma", half_life_days=d) for d in (30, 60, 90, 180)]
    if include_regime:
        specs += [BaselineSpec("hard_regime"), BaselineSpec("shrunk_regime")]
    return specs


def evaluate_baselines(folds, specs=None, *, horizon_bars: int, bootstrap_reps: int = 500) -> dict:
    specs = specs or default_specs()
    store = {s.key: {"p": [], "y": [], "fold_brier": [], "spec": s} for s in specs}

    for fold in folds:
        train, test = fold["train"], fold["test"]
        y = _targets(test)
        for spec in specs:
            p = predict_baseline(train, test, spec)
            bucket = store[spec.key]
            bucket["p"].extend(p.tolist())
            bucket["y"].extend(y.tolist())
            bucket["fold_brier"].append(brier(y, p))

    if not any(v["y"] for v in store.values()):
        return {"available": False, "reason": "NO_VALID_FOLDS"}

    base_y = np.asarray(store["expanding"]["y"])
    base_p = np.asarray(store["expanding"]["p"])
    metrics = {}
    for key, bucket in store.items():
        y = np.asarray(bucket["y"])
        p = np.asarray(bucket["p"])
        ci = (
            moving_block_delta_brier_ci(y, p, base_p, horizon_bars, reps=bootstrap_reps)
            if len(y) == len(base_y)
            else None
        )
        metrics[key] = {
            "brier": brier(y, p),
            "brier_skill_vs_expanding": brier_skill_score(y, p, base_p),
            "log_loss": log_loss(y, p),
            "calibration_error": calibration_error(y, p),
            "fold_brier": bucket["fold_brier"],
            "delta_brier_ci_vs_expanding": ci,
            "oos_n": len(y),
        }

    ranking = sorted(metrics, key=lambda k: (metrics[k]["brier"], 0 if k == "expanding" else 1))
    raw_winner = ranking[0]
    raw_metrics = metrics[raw_winner]
    ci = raw_metrics.get("delta_brier_ci_vs_expanding")
    statistically_clear = raw_winner == "expanding" or bool(ci and ci.get("low", 0) > 0)
    winner = raw_winner if statistically_clear else "expanding"

    return {
        "available": True,
        "winner": winner,
        "raw_point_estimate_winner": raw_winner,
        "ranking": ranking,
        "metrics": metrics,
        "selection_rule": (
            "Use lowest Brier only when its moving-block CI supports improvement over expanding; "
            "otherwise prefer expanding as the simpler baseline."
        ),
    }
