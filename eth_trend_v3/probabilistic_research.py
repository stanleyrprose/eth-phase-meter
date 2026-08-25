from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Any, Mapping, Sequence

import numpy as np

from .dynamic_baseline import BaselineSpec, predict_baseline
from .research_metrics import brier, brier_skill_score, calibration_error, log_loss, moving_block_delta_brier_ci


@dataclass
class ModelArtifact:
    features: list[str]
    mean: list[float]
    scale: list[float]
    coef: list[float]
    intercept: float
    interactions: list[tuple[str, str]]
    model_type: str = "logistic"

    def to_dict(self):
        return {
            "features": self.features,
            "mean": self.mean,
            "scale": self.scale,
            "coef": self.coef,
            "intercept": self.intercept,
            "interactions": [list(x) for x in self.interactions],
            "model_type": self.model_type,
        }


def _design(rows: Sequence[Mapping[str, Any]], features: list[str], interactions: list[tuple[str, str]]):
    cols = []
    kept = []
    for row in rows:
        vals = [row.get(f) for f in features]
        if any(v is None or not np.isfinite(v) for v in vals):
            continue
        base = dict(zip(features, map(float, vals)))
        x = list(map(float, vals))
        x.extend(base[a] * base[b] for a, b in interactions)
        cols.append(x)
        kept.append(row)
    return kept, np.asarray(cols, dtype=float)


def fit_logistic_artifact(rows, features: list[str], interactions: list[tuple[str, str]] | None = None, C: float = 1.0):
    from sklearn.linear_model import LogisticRegression

    interactions = interactions or []
    kept, X = _design(rows, features, interactions)
    y = np.asarray([r["target_up"] for r in kept], dtype=int)
    if len(y) < 20 or len(np.unique(y)) < 2:
        return None
    mean = X.mean(axis=0)
    scale = X.std(axis=0)
    scale = np.where(scale < 1e-12, 1.0, scale)
    z = (X - mean) / scale
    model = LogisticRegression(C=C, max_iter=1000, random_state=0).fit(z, y)
    names = features + [f"{a}*{b}" for a, b in interactions]
    return ModelArtifact(names, mean.tolist(), scale.tolist(), model.coef_[0].tolist(), float(model.intercept_[0]), interactions)


def predict_artifact(artifact: ModelArtifact | Mapping[str, Any], rows, base_features: list[str] | None = None):
    a = artifact if isinstance(artifact, ModelArtifact) else ModelArtifact(
        features=list(artifact["features"]),
        mean=list(artifact["mean"]),
        scale=list(artifact["scale"]),
        coef=list(artifact["coef"]),
        intercept=float(artifact["intercept"]),
        interactions=[tuple(x) for x in artifact.get("interactions", [])],
        model_type=artifact.get("model_type", "logistic"),
    )
    interactions = a.interactions
    base_features = base_features or [x for x in a.features if "*" not in x]
    kept, X = _design(rows, base_features, interactions)
    z = (X - np.asarray(a.mean)) / np.asarray(a.scale)
    logits = z @ np.asarray(a.coef) + a.intercept
    p = 1 / (1 + np.exp(-np.clip(logits, -30, 30)))
    return kept, p


def _row_key(row: Mapping[str, Any], fallback: str) -> str:
    return str(row.get("feature_time") or row.get("timestamp") or fallback)


def evaluate_logistic(
    folds,
    features: list[str],
    *,
    horizon_bars: int,
    baseline_spec: BaselineSpec | None = None,
    interactions: list[tuple[str, str]] | None = None,
    C: float = 1.0,
    bootstrap_reps: int = 500,
):
    baseline_spec = baseline_spec or BaselineSpec("expanding")
    interactions = interactions or []
    if len(interactions) > 20:
        raise ValueError("controlled interaction budget exceeded")
    ys = []
    ps = []
    bs = []
    fold_metrics = []
    oos_predictions = []
    for fold_no, fold in enumerate(folds, start=1):
        artifact = fit_logistic_artifact(fold["train"], features, interactions, C=C)
        if artifact is None:
            continue
        kept, p = predict_artifact(artifact, fold["test"], features)
        if not kept:
            continue
        y = np.asarray([r["target_up"] for r in kept], dtype=int)
        bp = predict_baseline(fold["train"], kept, baseline_spec)
        ys.extend(y.tolist())
        ps.extend(p.tolist())
        bs.extend(bp.tolist())
        fold_metrics.append({"brier": brier(y, p), "baseline_brier": brier(y, bp), "n": len(y)})
        for i, row in enumerate(kept):
            oos_predictions.append(
                {
                    "key": _row_key(row, f"fold{fold_no}-{i}"),
                    "fold": fold_no,
                    "target_up": int(y[i]),
                    "probability": float(p[i]),
                    "baseline_probability": float(bp[i]),
                }
            )
    if not ys:
        return {"available": False, "reason": "NO_VALID_FOLDS"}
    y = np.asarray(ys)
    p = np.asarray(ps)
    bp = np.asarray(bs)
    ci = moving_block_delta_brier_ci(y, p, bp, horizon_bars, reps=bootstrap_reps)
    return {
        "available": True,
        "features": features,
        "interactions": [list(x) for x in interactions],
        "metrics": {
            "brier": brier(y, p),
            "baseline_brier": brier(y, bp),
            "brier_skill": brier_skill_score(y, p, bp),
            "log_loss": log_loss(y, p),
            "calibration_error": calibration_error(y, p),
            "delta_brier_ci": ci,
            "oos_n": len(y),
            "folds": fold_metrics,
        },
        "oos_predictions": oos_predictions,
        "passes_incremental_gate": bool(brier(y, p) < brier(y, bp) and ci and ci["low"] > 0),
    }


def controlled_interactions(
    features: list[str],
    allowed_pairs: list[tuple[str, str]] | None = None,
    max_interactions: int = 20,
):
    pairs = allowed_pairs if allowed_pairs is not None else list(combinations(features, 2))
    pairs = [p for p in pairs if p[0] in features and p[1] in features]
    if len(pairs) > max_interactions:
        pairs = pairs[:max_interactions]
    return pairs
