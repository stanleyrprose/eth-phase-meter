from __future__ import annotations
import re
import numpy as np
import pandas as pd
import eth_phase_meter as meter

_orig_get_macro_indicator = meter.get_macro_indicator
_orig_score_macro = meter.score_macro
_orig_score_technical = meter.score_technical


def get_macro_indicator_fixed(fred_series, yfinance_symbol):
    if fred_series == "DGS2":
        yfinance_symbol = "^UST2Y"
    return _orig_get_macro_indicator(fred_series, yfinance_symbol)


def score_macro_fixed(macro):
    score, details = _orig_score_macro(macro)
    if not macro:
        return score, details
    if "btc_change_24h" not in macro:
        score += 1  # original default 0% produces -1; neutralize missing data
        details["BTC动量"] = "N/A (数据源不可用；未计分)"
    if "ethbtc_change" not in macro:
        details["ETH/BTC"] = "N/A (数据源不可用；未计分)"
    if "usdc_usdt" not in macro:
        details["USDC/USDT"] = "N/A (数据源不可用；未计分)"
    details["宏观经济总分"] = f"{score:+d}/±25"
    return score, details


def _extract_int(pattern, text, default=0):
    m = re.search(pattern, text or "")
    return int(m.group(1)) if m else default


def score_technical_fixed(df):
    old_total, details = _orig_score_technical(df)
    if df is None or len(df) < 60:
        return old_total, details
    high, low, close = df["high"], df["low"], df["close"]
    last, prev_close = float(close.iloc[-1]), float(close.iloc[-2])

    def prior_levels(n):
        return float(high.iloc[:-1].tail(n).max()), float(low.iloc[:-1].tail(n).min())

    h20, l20 = prior_levels(20)
    h50, l50 = prior_levels(50)
    h100, l100 = prior_levels(100)
    if prev_close <= h50 and last > h50:
        level_score, tag = 5, "收盘突破50根前高"
    elif prev_close >= l50 and last < l50:
        level_score, tag = -5, "收盘跌破50根前低"
    elif prev_close <= h20 and last > h20:
        level_score, tag = 3, "收盘突破20根前高"
    elif prev_close >= l20 and last < l20:
        level_score, tag = -3, "收盘跌破20根前低"
    else:
        rp = (last - l50) / (h50 - l50) if h50 != l50 else 0.5
        if rp > 0.9:
            level_score, tag = 2, "逼近区间上沿"
        elif rp < 0.1:
            level_score, tag = -2, "逼近区间下沿"
        else:
            level_score, tag = 0, "区间中部"

    tr = pd.concat([
        (high - low),
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr14 = tr.rolling(14).sum()
    plus_di = 100 * (pd.Series(plus_dm, index=df.index).rolling(14).sum() / tr14)
    minus_di = 100 * (pd.Series(minus_dm, index=df.index).rolling(14).sum() / tr14)
    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di)).replace([np.inf, -np.inf], np.nan)
    adx = float(dx.rolling(14).mean().iloc[-1])
    pdi = float(plus_di.iloc[-1])
    mdi = float(minus_di.iloc[-1])
    strength = 3 if adx >= 28 else (1 if adx >= 20 else 0) if not np.isnan(adx) else 0
    adx_score = (
        strength if pdi > mdi else -strength if mdi > pdi else 0
    ) if strength and not np.isnan(pdi) and not np.isnan(mdi) else 0

    old_combo = _extract_int(r"→\s*([+-]?\d+)\s*\(cap±5\)", details.get("关键位+强度合成", ""), 0)
    slope_score = _extract_int(r"斜率([+-]?\d+)", details.get("关键位+强度合成", ""), 0)
    new_combo = max(-5, min(5, level_score + adx_score + slope_score))
    total = old_total - old_combo + new_combo

    details["结构关键位"] = (
        f"20[{l20:.0f}-{h20:.0f}] 50[{l50:.0f}-{h50:.0f}] 100[{l100:.0f}-{h100:.0f}] | "
        f"{tag} → {level_score:+d}"
    )
    details["距离前高/前低(20)"] = f"距20H={last / h20 - 1:+.2%} 距20L={last / l20 - 1:+.2%}"
    details["ADX14"] = (
        f"{adx:.1f} +DI={pdi:.1f} -DI={mdi:.1f} → {adx_score:+d}"
        if not np.isnan(adx)
        else "N/A → +0"
    )
    details["关键位+强度合成"] = (
        f"结构{level_score:+d} + ADX{adx_score:+d} + 斜率{slope_score:+d} → {new_combo:+d} (cap±5)"
    )
    details["技术面总分"] = f"{total:+d}/±25"
    return total, details


def apply():
    meter.get_macro_indicator = get_macro_indicator_fixed
    meter.score_macro = score_macro_fixed
    meter.score_technical = score_technical_fixed
