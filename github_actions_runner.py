"""GitHub Actions runner with market-data fallbacks.

GitHub-hosted runner IPs can be rejected by Binance. The core application is kept
unchanged; this wrapper falls back to Deribit public market data so missing Binance
data is not reported as a fake $0 ETH price.
"""
from __future__ import annotations

import datetime as dt
import pandas as pd
import eth_phase_meter as meter

_orig_klines = meter.fetch_binance_klines
_orig_deriv = meter.fetch_binance_derivatives
_orig_score_deriv = meter.score_derivatives


def _deribit_chart(timeframe="4h", limit=200):
    """Fetch Deribit candles with 4h bars aggregated locally from 1h data."""
    if timeframe == "1d":
        source_resolution = "1D"
        source_minutes = 1440
        source_limit = limit
    else:
        source_resolution = "60"
        source_minutes = 60
        source_limit = limit * (4 if timeframe == "4h" else 1) + (8 if timeframe == "4h" else 0)

    end_ms = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    start_ms = end_ms - (source_limit + 10) * source_minutes * 60 * 1000
    payload = meter.safe_get(
        f"{meter.DERIBIT_BASE}/public/get_tradingview_chart_data",
        {
            "instrument_name": "ETH-PERPETUAL",
            "start_timestamp": start_ms,
            "end_timestamp": end_ms,
            "resolution": source_resolution,
        },
    )
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        return None
    ticks = result.get("ticks") or []
    opens = result.get("open") or []
    highs = result.get("high") or []
    lows = result.get("low") or []
    closes = result.get("close") or []
    volumes = result.get("volume") or []
    n = min(len(ticks), len(opens), len(highs), len(lows), len(closes))
    if n < 2:
        return None

    rows = []
    for i in range(n):
        close = float(closes[i])
        volume = float(volumes[i]) if i < len(volumes) and volumes[i] is not None else 0.0
        rows.append({
            "open_time": pd.to_datetime(int(ticks[i]), unit="ms", utc=True),
            "open": float(opens[i]), "high": float(highs[i]),
            "low": float(lows[i]), "close": close, "volume": volume,
            "quote_vol": volume * close,
            "taker_buy_vol": 0.0, "taker_buy_quote": 0.0,
        })
    df = pd.DataFrame(rows).sort_values("open_time").drop_duplicates("open_time")

    if timeframe == "4h":
        frame = df.set_index("open_time")
        df = frame.resample("4h", origin="start_day", label="left", closed="left").agg({
            "open": "first", "high": "max", "low": "min", "close": "last",
            "volume": "sum", "quote_vol": "sum",
            "taker_buy_vol": "sum", "taker_buy_quote": "sum",
        }).dropna(subset=["open", "high", "low", "close"]).reset_index()

    return df.tail(limit).reset_index(drop=True)


def fetch_market_klines(symbol="ETHUSDT", interval="4h", limit=200):
    df = _orig_klines(symbol=symbol, interval=interval, limit=limit)
    if df is not None and len(df) >= 50:
        print(f"  [DATA] technical candles: Binance ({len(df)} rows)")
        return df
    print("  [WARN] Binance candles unavailable; falling back to Deribit ETH-PERPETUAL")
    df = _deribit_chart(interval, limit)
    if df is not None:
        print(f"  [DATA] technical candles: Deribit ({len(df)} rows)")
    return df


def fetch_derivatives(oi_limit=48, ratio_period="4h"):
    data = _orig_deriv(oi_limit=oi_limit, ratio_period=ratio_period) or {}
    data.setdefault("ratio_period", ratio_period)
    if any(k in data for k in ("funding_rate", "oi_change_window", "long_short_ratio", "cvd_current")):
        data["_data_source"] = "Binance"
        return data

    print("  [WARN] Binance futures unavailable; falling back to Deribit ETH-PERPETUAL")
    payload = meter.safe_get(
        f"{meter.DERIBIT_BASE}/public/ticker",
        {"instrument_name": "ETH-PERPETUAL"},
    )
    ticker = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(ticker, dict):
        data["_data_source"] = "unavailable"
        return data

    data["_data_source"] = "Deribit"
    data["_fallback_mode"] = True
    if ticker.get("open_interest") is not None:
        data["OI"] = float(ticker["open_interest"])
    funding = ticker.get("funding_8h")
    if funding is None:
        funding = ticker.get("current_funding")
    if funding is not None:
        data["funding_rate"] = float(funding)

    chart = _deribit_chart(ratio_period, 3)
    if chart is not None and len(chart) >= 2:
        p0, p1 = float(chart.iloc[-2]["close"]), float(chart.iloc[-1]["close"])
        if p0:
            data["price_change_period"] = (p1 - p0) / p0
    return data


def score_derivatives(deriv):
    score, details = _orig_score_deriv(deriv)
    if not deriv:
        return score, details
    source = deriv.get("_data_source")
    if source:
        details["衍生品数据源"] = source
    if deriv.get("_fallback_mode"):
        if "oi_change_window" not in deriv and "OI_change_4h" not in deriv:
            details["OI变化(窗口)"] = "N/A (Deribit仅有当前OI；历史变化未计分)"
            details["OI×价格象限"] = "N/A (缺少历史OI变化；未计分)"
            details["短线策略提示(OI×价格)"] = "OI历史缺失：降低该项权重，参考价格与资金费率"
        if "long_short_ratio" not in deriv:
            details["多空比"] = "N/A (Binance不可用；未计分)"
        if "taker_buy_sell_avg" not in deriv:
            details["CVD买卖比"] = "N/A (Binance不可用；未计分)"
        if "cvd_current" not in deriv:
            details["CVD累积净值"] = "N/A (Binance不可用；未计分)"
    return score, details


def main():
    meter.fetch_binance_klines = fetch_market_klines
    meter.fetch_binance_derivatives = fetch_derivatives
    meter.score_derivatives = score_derivatives
    print("[ACTIONS] market-data fallback layer enabled")
    return meter.main()


if __name__ == "__main__":
    main()
