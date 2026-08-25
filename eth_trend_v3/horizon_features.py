from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FeatureMeta:
    feature_name: str
    feature_version: str
    source: str
    formula: str
    lookback: str
    timestamp_semantics: str
    source_delay: str
    missing_policy: str
    information_cluster: str
    horizon_relevance: str
    source_version: str = "unknown"
    event_time_field: str = "event_time"
    retrieval_time_field: str = "retrieval_time"
    available_at_field: str = "available_at"
    expected_direction: str | None = None

    def to_dict(self):
        return asdict(self)


def feature_contract(**kwargs) -> dict[str, Any]:
    meta = FeatureMeta(**kwargs)
    if meta.missing_policy.lower() in {"zero", "fill_zero", "silent_zero"}:
        raise ValueError("silent zero filling is prohibited")
    if not meta.timestamp_semantics or not meta.source_delay:
        raise ValueError("timestamp semantics and source delay are required")
    return meta.to_dict()


def _base_frame(candles: pd.DataFrame) -> pd.DataFrame:
    df = candles.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    df["ret_4h"] = np.log(df["close"] / df["close"].shift(1))
    return df


def build_horizon_features(candles: pd.DataFrame, horizon: str, macro: pd.DataFrame | None = None) -> pd.DataFrame:
    df = _base_frame(candles)
    windows = {"3d": [6, 18], "7d": [6, 18, 42], "30d": [18, 42, 84, 180]}[horizon]
    for w in windows:
        tag = {6: "1d", 18: "3d", 42: "7d", 84: "14d", 180: "30d"}.get(w, f"{w}b")
        df[f"return_{tag}"] = np.log(df["close"] / df["close"].shift(w))
        df[f"rv_{tag}"] = df["ret_4h"].rolling(w, min_periods=w).std(ddof=0)
        df[f"volume_change_{tag}"] = np.log1p(df["volume"]) - np.log1p(df["volume"].shift(w))
        df[f"distance_ma_{tag}"] = df["close"] / df["close"].rolling(w, min_periods=w).mean() - 1
        df[f"trend_slope_{tag}"] = np.log(df["close"]).diff(w) / w
    if horizon == "30d":
        rollmax = df["close"].rolling(180, min_periods=180).max()
        df["drawdown_30d"] = df["close"] / rollmax - 1
    if macro is not None and len(macro):
        m = macro.copy()
        if "available_at" not in m:
            raise ValueError("macro/alternative data must expose PIT available_at")
        m["available_at"] = pd.to_datetime(m["available_at"], utc=True)
        m = m.sort_values("available_at")
        # Backward asof is PIT-safe: only information available by candle timestamp is joined.
        df = pd.merge_asof(df.sort_values("timestamp"), m, left_on="timestamp", right_on="available_at", direction="backward")
    return df.replace([np.inf, -np.inf], np.nan)


def correlation_audit(df: pd.DataFrame, features: list[str], threshold: float = .8) -> dict:
    corr = df[features].corr()
    pairs = []
    for i, a in enumerate(features):
        for b in features[i + 1:]:
            v = corr.loc[a, b]
            if pd.notna(v) and abs(v) >= threshold:
                pairs.append({"a": a, "b": b, "r": float(v)})
    return {"threshold": threshold, "high_correlation_pairs": pairs, "matrix": corr.to_dict()}


def missingness_report(df: pd.DataFrame, features: list[str]) -> dict:
    return {f: float(df[f].isna().mean()) for f in features}


def external_feature_schema() -> dict[str, dict[str, Any]]:
    """Schema readiness for future information groups; does not claim predictive value."""
    return {
        "derivatives": {"features": ["funding", "basis", "open_interest", "taker_imbalance"], "requires_available_at": True},
        "capital_flow": {"features": ["exchange_netflow_eth", "stablecoin_flow_usd"], "requires_available_at": True},
        "structural_supply": {"features": ["staking_netflow_eth"], "requires_available_at": True},
        "valuation": {"features": ["mvrv_proxy"], "requires_available_at": True},
        "macro": {"features": ["dxy", "us10y", "us2y", "spx", "nasdaq"], "requires_available_at": True},
    }
