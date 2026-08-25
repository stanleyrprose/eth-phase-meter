from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

import numpy as np

from .research_metrics import brier, brier_skill_score, effective_sample_diagnostic, log_loss

HORIZON_BARS = {"3d": 18, "7d": 42, "30d": 180}
SHADOW_SETTLED_HEURISTICS = {"3d": 50, "7d": 30, "30d": 15}


@dataclass
class ShadowRecord:
    forecast_id: str
    experiment_id: str
    model_version: str
    artifact_hash: str
    git_sha: str
    forecast_time: str
    horizon: str
    probability: float
    baseline_probability: float
    market_state: dict
    regime: str | None
    data_health: str
    feature_snapshot_id: str | None
    settlement_time: str
    settled: bool = False
    mode: str = "SHADOW"

    def to_dict(self):
        return asdict(self)


def unified_inference(
    predict_fn: Callable[[Mapping[str, Any]], float],
    features: Mapping[str, Any],
    *,
    mode: str,
) -> float:
    if mode not in {"SHADOW", "PRODUCTION"}:
        raise ValueError("invalid inference mode")
    p = float(predict_fn(features))
    if not 0 <= p <= 1:
        raise ValueError("probability outside [0,1]")
    return p


def new_shadow_record(**kwargs) -> dict:
    kwargs.setdefault("forecast_id", f"fc-{uuid4().hex}")
    kwargs.setdefault("forecast_time", datetime.now(timezone.utc).isoformat())
    return ShadowRecord(**kwargs).to_dict()


def path_outcome(entry_price: float, path_prices: Sequence[float]) -> dict:
    p = np.asarray(path_prices, dtype=float)
    if entry_price <= 0 or len(p) == 0:
        raise ValueError("invalid path")
    returns = p / entry_price - 1
    running_max = np.maximum.accumulate(np.r_[entry_price, p])
    draw = np.r_[entry_price, p] / running_max - 1
    min_idx = int(np.argmin(draw))
    recovery = len(draw) - 1 - min_idx if min_idx < len(draw) - 1 else 0
    stable = lambda value: round(float(value), 12)
    return {
        "actual_return": stable(p[-1] / entry_price - 1),
        "actual_direction": int(p[-1] > entry_price),
        "mae": stable(np.min(returns)),
        "mfe": stable(np.max(returns)),
        "path_volatility": stable(np.std(np.diff(np.log(np.r_[entry_price, p])), ddof=0)) if len(p) > 1 else 0.0,
        "max_drawdown": stable(np.min(draw)),
        "drawdown_duration_bars": int(recovery),
    }


def settle_shadow_record(
    record: Mapping[str, Any],
    *,
    entry_price: float,
    path_prices: Sequence[float],
    settled_at: str | None = None,
) -> dict:
    if record.get("mode", "SHADOW") not in {"SHADOW", "PRODUCTION"}:
        raise ValueError("invalid forecast mode")
    settled = dict(record)
    settled.update(path_outcome(entry_price, path_prices))
    settled["settled"] = True
    settled["settled_at"] = settled_at or datetime.now(timezone.utc).isoformat()
    y = np.asarray([settled["actual_direction"]], dtype=float)
    p = np.asarray([float(settled["probability"])], dtype=float)
    bp = np.asarray([float(settled["baseline_probability"])], dtype=float)
    settled["brier_loss"] = brier(y, p)
    settled["baseline_brier_loss"] = brier(y, bp)
    settled["log_loss"] = log_loss(y, p)
    return settled


def shadow_metrics(records: list[dict]) -> dict:
    settled = [r for r in records if r.get("settled") and r.get("data_health") == "NORMAL"]
    if not settled:
        return {"available": False, "reason": "NO_NORMAL_SETTLED_FORECASTS"}
    y = np.asarray([r["actual_direction"] for r in settled])
    p = np.asarray([r["probability"] for r in settled])
    bp = np.asarray([r["baseline_probability"] for r in settled])
    return {
        "available": True,
        "settled_n": len(settled),
        "brier": brier(y, p),
        "brier_skill": brier_skill_score(y, p, bp),
        "log_loss": log_loss(y, p),
        "degraded_excluded": len(
            [r for r in records if r.get("settled") and r.get("data_health") != "NORMAL"]
        ),
    }


def shadow_evidence(
    records: list[dict],
    *,
    horizon: str,
    effective_evidence_confirmed: bool = False,
    min_regimes: int = 2,
) -> dict:
    if horizon not in HORIZON_BARS:
        raise ValueError("unsupported horizon")
    normal = [
        r for r in records
        if r.get("settled") and r.get("data_health") == "NORMAL" and r.get("horizon") == horizon
    ]
    metrics = shadow_metrics(normal) if normal else {"available": False, "reason": "NO_NORMAL_SETTLED_FORECASTS"}
    regimes = sorted({str(r.get("regime")) for r in normal if r.get("regime") not in (None, "")})
    raw_threshold = SHADOW_SETTLED_HEURISTICS[horizon]
    raw_gate = len(normal) >= raw_threshold
    regime_gate = len(regimes) >= min_regimes
    diagnostic = effective_sample_diagnostic(len(normal), HORIZON_BARS[horizon])
    ready = bool(raw_gate and regime_gate and effective_evidence_confirmed and metrics.get("available"))
    return {
        "horizon": horizon,
        "metrics": metrics,
        "settled_n": len(normal),
        "raw_count_threshold": raw_threshold,
        "raw_count_gate": raw_gate,
        "regimes": regimes,
        "regime_gate": regime_gate,
        "effective_sample_diagnostic": diagnostic,
        "effective_evidence_confirmed": bool(effective_evidence_confirmed),
        "promotion_evidence_ready": ready,
        "heuristic_note": (
            "Settled-count thresholds are RESEARCH_HEURISTIC. Raw count alone never permits promotion; "
            "effective evidence must be independently confirmed."
        ),
    }


def persist_shadow(record: dict, artifact_dir="eth_reports/shadow"):
    dsn = os.getenv("DATABASE_URL")
    if dsn:
        import psycopg

        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "CREATE TABLE IF NOT EXISTS eth_forecasts("
                    "forecast_id TEXT PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
                    "mode TEXT NOT NULL, horizon TEXT NOT NULL, settled BOOLEAN NOT NULL DEFAULT FALSE, payload JSONB NOT NULL)"
                )
                cur.execute(
                    "INSERT INTO eth_forecasts(forecast_id,mode,horizon,settled,payload) "
                    "VALUES(%s,%s,%s,%s,%s::jsonb) ON CONFLICT(forecast_id) DO UPDATE SET "
                    "settled=EXCLUDED.settled,payload=EXCLUDED.payload",
                    (
                        record["forecast_id"],
                        record.get("mode", "SHADOW"),
                        record["horizon"],
                        bool(record.get("settled")),
                        json.dumps(record, default=str),
                    ),
                )
            conn.commit()
    else:
        root = Path(artifact_dir)
        root.mkdir(parents=True, exist_ok=True)
        (root / f"{record['forecast_id']}.json").write_text(
            json.dumps(record, indent=2, default=str), encoding="utf-8"
        )
    return record["forecast_id"]


def load_shadow_records(artifact_dir="eth_reports/shadow", mode: str | None = None) -> list[dict]:
    dsn = os.getenv("DATABASE_URL")
    records: list[dict] = []
    if dsn:
        import psycopg

        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                if mode:
                    cur.execute("SELECT payload FROM eth_forecasts WHERE mode=%s ORDER BY created_at", (mode,))
                else:
                    cur.execute("SELECT payload FROM eth_forecasts ORDER BY created_at")
                records = [r[0] for r in cur.fetchall()]
    else:
        root = Path(artifact_dir)
        if root.exists():
            for path in sorted(root.glob("*.json")):
                try:
                    record = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if mode and record.get("mode") != mode:
                    continue
                records.append(record)
    return records
