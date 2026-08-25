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
    """Registered research candidates; registration does not imply predictive eligibility."""
    return [
        FeatureMeta("funding_rate", "v2", "derivatives", "perpetual funding rate as reported by active provider", "point", "PIT snapshot retrieval; provider timestamp if exposed", "provider-specific", "mark_missing", "derivatives_crowding", "3d,7d", retrieval_time_field="observed_at"),
        FeatureMeta("basis", "v1", "derivatives", "futures basis", "point", "observed provider value", "provider-specific", "mark_missing", "derivatives_crowding", "3d,7d"),
        FeatureMeta("open_interest", "v2", "derivatives", "provider-native open interest level; compare only within a consistent provider/unit regime", "point", "PIT snapshot retrieval", "provider-specific", "mark_missing", "derivatives_positioning", "3d,7d", retrieval_time_field="observed_at"),
        FeatureMeta("put_call_oi_ratio", "v1", "Deribit options", "aggregate put open interest / call open interest", "point", "PIT snapshot retrieval", "collector latency", "mark_missing", "options_positioning", "3d,7d", retrieval_time_field="observed_at"),
        FeatureMeta("atm_iv_near", "v1", "Deribit options", "near-expiry ATM mark implied volatility", "point", "PIT snapshot retrieval", "collector latency", "mark_missing", "options_volatility", "3d,7d", retrieval_time_field="observed_at"),
        FeatureMeta("iv_skew_25d_proxy_near", "v1", "Deribit options", "near-expiry OTM put mark IV - OTM call mark IV proxy", "point", "PIT snapshot retrieval", "collector latency", "mark_missing", "options_skew", "3d,7d", retrieval_time_field="observed_at"),
        FeatureMeta("iv_term_structure_near_next", "v1", "Deribit options", "near ATM IV - next-expiry ATM IV", "point", "PIT snapshot retrieval", "collector latency", "mark_missing", "options_term_structure", "3d,7d", retrieval_time_field="observed_at"),
        FeatureMeta("exchange_netflow_eth", "v1", "onchain", "exchange inflow - outflow", "rolling", "event-time aggregation available after query completion", "query-specific", "mark_missing", "capital_flow", "3d,7d,30d"),
        FeatureMeta("stablecoin_flow_usd", "v1", "onchain", "stablecoin exchange netflow", "rolling", "event-time aggregation available after query completion", "query-specific", "mark_missing", "capital_flow", "7d,30d"),
        FeatureMeta("staking_netflow_eth", "v1", "onchain", "staking inflow - outflow", "rolling", "event-time aggregation available after query completion", "query-specific", "mark_missing", "structural_supply", "7d,30d"),
        FeatureMeta("dxy_return", "v2", "FRED DTWEXBGS / fallback", "daily return of Nominal Broad U.S. Dollar Index", "1 observation", "PIT snapshot retrieval; FRED observation date retained", "daily/source-specific", "mark_missing", "macro_dollar", "7d,30d", event_time_field="raw_payload.macro.dxy_observation_date", retrieval_time_field="observed_at"),
        FeatureMeta("us10y_change_bps", "v2", "FRED DGS10", "daily 10Y Treasury yield change in basis points", "1 observation", "PIT snapshot retrieval; FRED observation date retained", "daily/source-specific", "mark_missing", "macro_rates", "7d,30d", event_time_field="raw_payload.macro.us10y_observation_date", retrieval_time_field="observed_at"),
        FeatureMeta("us2y_change_bps", "v1", "FRED DGS2", "daily 2Y Treasury yield change in basis points", "1 observation", "PIT snapshot retrieval; FRED observation date retained", "daily/source-specific", "mark_missing", "macro_rates", "7d,30d", event_time_field="raw_payload.macro.us2y_observation_date", retrieval_time_field="observed_at"),
        FeatureMeta("real10y_change_bps", "v1", "FRED DFII10", "daily 10Y inflation-indexed Treasury real-yield change in basis points", "1 observation", "PIT snapshot retrieval; FRED observation date retained", "daily/source-specific", "mark_missing", "macro_real_rates", "7d,30d", event_time_field="raw_payload.macro.real10y_observation_date", retrieval_time_field="observed_at"),
        FeatureMeta("yield_curve_10y2y_pp", "v1", "FRED DGS10-DGS2 / fallback", "10Y nominal yield - 2Y nominal yield in percentage points", "point", "PIT snapshot retrieval", "daily/source-specific", "mark_missing", "macro_curve", "7d,30d", retrieval_time_field="observed_at"),
        FeatureMeta("btc_return_24h_pct", "v1", "Binance/Deribit", "BTC 24h price return in percent", "24h", "PIT snapshot retrieval", "exchange latency", "mark_missing", "macro_crypto_beta", "3d,7d,30d", retrieval_time_field="observed_at"),
        FeatureMeta("ethbtc_return_24h_pct", "v1", "Binance/Deribit synthetic", "ETH/BTC 24h relative return in percent", "24h", "PIT snapshot retrieval", "exchange latency", "mark_missing", "macro_relative_strength", "3d,7d,30d", retrieval_time_field="observed_at"),
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
