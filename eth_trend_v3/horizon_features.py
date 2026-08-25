from __future__ import annotations

from dataclasses import asdict, dataclass
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
    source_version: str | None = None
    event_time_field: str | None = None
    retrieval_time_field: str | None = None
    available_at_field: str = "available_at"
    expected_direction: str | None = None

    def to_dict(self):
        return asdict(self)


def validate_feature_contract(meta: FeatureMeta) -> None:
    required = {
        "feature_name": meta.feature_name,
        "feature_version": meta.feature_version,
        "source": meta.source,
        "formula": meta.formula,
        "timestamp_semantics": meta.timestamp_semantics,
        "missing_policy": meta.missing_policy,
        "information_cluster": meta.information_cluster,
        "horizon_relevance": meta.horizon_relevance,
    }
    missing = [key for key, value in required.items() if not str(value).strip()]
    if missing:
        raise ValueError("incomplete feature contract: " + ",".join(missing))
    if meta.missing_policy.lower() in {"zero", "fill_zero", "silent_zero"}:
        raise ValueError("silent zero filling is prohibited")


def external_feature_contracts() -> list[FeatureMeta]:
    return [
        FeatureMeta("funding", "v1", "derivatives", "provider funding rate", "point", "closed/observed provider value", "provider-specific", "mark_missing", "derivatives_crowding", "3d,7d"),
        FeatureMeta("basis", "v1", "derivatives", "futures basis", "point", "observed provider value", "provider-specific", "mark_missing", "derivatives_crowding", "3d,7d"),
        FeatureMeta("open_interest", "v1", "derivatives", "open interest", "point", "observed provider value", "provider-specific", "mark_missing", "derivatives_positioning", "3d,7d"),
        FeatureMeta("exchange_netflow_eth", "v1", "onchain", "exchange inflow - outflow", "rolling", "event-time aggregation available after query completion", "query-specific", "mark_missing", "capital_flow", "3d,7d,30d"),
        FeatureMeta("stablecoin_flow_usd", "v1", "onchain", "stablecoin exchange netflow", "rolling", "event-time aggregation available after query completion", "query-specific", "mark_missing", "capital_flow", "7d,30d"),
        FeatureMeta("staking_netflow_eth", "v1", "onchain", "staking inflow - outflow", "rolling", "event-time aggregation available after query completion", "query-specific", "mark_missing", "structural_supply", "7d,30d"),
        FeatureMeta("dxy_return", "v1", "macro", "DXY return", "rolling", "available only after source observation timestamp", "source-specific", "mark_missing", "macro_dollar", "7d,30d"),
        FeatureMeta("us10y_change", "v1", "macro", "US10Y yield change", "rolling", "available only after source observation timestamp", "source-specific", "mark_missing", "macro_rates", "7d,30d"),
    ]


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
        if "available_at" not in macro.columns:
            raise ValueError("macro data requires available_at for PIT-safe join")
        m = macro.copy()
        m["available_at"] = pd.to_datetime(m["available_at"], utc=True)
        m = m.sort_values("available_at")
        df = pd.merge_asof(
            df.sort_values("timestamp"),
            m,
            left_on="timestamp",
            right_on="available_at",
            direction="backward",
        )
    return df.replace([np.inf, -np.inf], np.nan)


def correlation_audit(df: pd.DataFrame, features: list[str], threshold: float = 0.8) -> dict:
    corr = df[features].corr()
    pairs = []
    for i, a in enumerate(features):
        for b in features[i + 1 :]:
            v = corr.loc[a, b]
            if pd.notna(v) and abs(v) >= threshold:
                pairs.append({"a": a, "b": b, "r": float(v)})
    return {"threshold": threshold, "high_correlation_pairs": pairs, "matrix": corr.to_dict()}


def missingness_report(df: pd.DataFrame, features: list[str]) -> dict:
    return {f: float(df[f].isna().mean()) for f in features}
