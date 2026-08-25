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
    min_regime_count: int = 5


def _targets(rows):
    return np.asarray([int(r["target_up"]) for r in rows], dtype=int)


def _times(rows):
    return [parse_utc(r.get("feature_time", r.get("timestamp"))) for r in rows]


def _regime(row: Mapping[str, Any]):
    value = row.get("regime")
    if isinstance(value, Mapping):
        value = value.get("regime")
    return value if value is not None else row.get("regime_name", row.get("regime_code"))


def _regime_probability(train: Sequence[Mapping[str, Any]], current_regime: Any, spec: BaselineSpec) -> float:
    y = _targets(train)
    global_p = float(y.mean())
    if current_regime is None:
        return global_p
    mask = np.asarray([_regime(r) == current_regime for r in train], dtype=bool)
    n = int(mask.sum())
    if n < max(1, int(spec.min_regime_count)):
        return global_p
    regime_p = float(y[mask].mean())
    if spec.name == "regime":
        return regime_p
    if spec.name == "shrunk_regime":
        lam = n / (n + max(0.0, float(spec.prior_strength)))
        return float(lam * regime_p + (1.0 - lam) * global_p)
    raise ValueError(spec.name)


def predict_baseline(train: Sequence[Mapping[str, Any]], test: Sequence[Mapping[str, Any]], spec: BaselineSpec) -> np.ndarray:
    if not train:
        raise ValueError("baseline requires training observations")
    y = _targets(train)
    times = _times(train)
    p = float(y.mean())
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
    if spec.name in {"regime", "shrunk_regime"}:
        values = [_regime_probability(train, _regime(r), spec) for r in test]
        return np.clip(np.asarray(values, dtype=float), 1e-6, 1 - 1e-6)
    raise ValueError(f"unsupported baseline: {spec.name}")


def default_specs():
    return (
        [BaselineSpec("expanding")]
        + [BaselineSpec("rolling", window_days=d) for d in (90, 180, 365)]
        + [BaselineSpec("ewma", half_life_days=d) for d in (30, 60, 90, 180)]
        + [BaselineSpec("regime"), BaselineSpec("shrunk_regime")]
    )


def _spec_key(spec: BaselineSpec) -> str:
    if spec.window_days:
        return f"{spec.name}-{spec.window_days}d"
    if spec.half_life_days:
        return f"{spec.name}-{int(spec.half_life_days)}d"
    return spec.name


def evaluate_baselines(folds, specs=None, *, horizon_bars: int, bootstrap_reps: int = 500) -> dict:
    specs = specs or default_specs()
    store = {_spec_key(s): {"p": [], "y": [], "fold_brier": []} for s in specs}
    for fold in folds:
        train, test = fold["train"], fold["test"]
        y = _targets(test)
        for spec in specs:
            key = _spec_key(spec)
            p = predict_baseline(train, test, spec)
            store[key]["p"].extend(p.tolist())
            store[key]["y"].extend(y.tolist())
            store[key]["fold_brier"].append(brier(y, p))
    if not any(v["y"] for v in store.values()):
        return {"available": False, "reason": "NO_VALID_FOLDS"}
    metrics = {}
    base_y = np.asarray(store["expanding"]["y"])
    base_p = np.asarray(store["expanding"]["p"])
    for key, value in store.items():
        y = np.asarray(value["y"])
        p = np.asarray(value["p"])
        ci = moving_block_delta_brier_ci(y, p, base_p, horizon_bars, reps=bootstrap_reps) if len(y) == len(base_y) else None
        metrics[key] = {
            "brier": brier(y, p),
            "brier_skill_vs_expanding": brier_skill_score(y, p, base_p),
            "log_loss": log_loss(y, p),
            "calibration_error": calibration_error(y, p),
            "fold_brier": value["fold_brier"],
            "delta_brier_ci_vs_expanding": ci,
            "oos_n": len(y),
        }
    ranking = sorted(metrics, key=lambda k: (metrics[k]["brier"], 0 if k == "expanding" else 1))
    winner = ranking[0]
    return {
        "available": True,
        "winner": winner,
        "ranking": ranking,
        "metrics": metrics,
        "selection_rule": "lowest Brier with uncertainty/stability review; ties prefer simpler baseline",
    }
