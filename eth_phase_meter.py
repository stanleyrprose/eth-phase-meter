#!/usr/bin/env python3
"""
ETH 阶段仪 (ETH Phase Meter)
============================
每4小时周期性收集 ETH 多维度数据 → 打分 → 判断阶段 → 输出 Excel

四大维度:
  1. 技术面 + 衍生品结构 (权重 35%)
  2. 期权结构 (权重 25%)
  3. 社交情绪 (权重 15%)
  4. 宏观经济 (权重 25%)

总分范围: -100 ~ +100
阶段划分:
  [+70, +100]  极度贪婪/过热 → 分批止盈, 卖 call
  [+30,  +70)  偏多趋势     → 持有/回调加仓, 做多 delta
  [-30,  +30)  震荡/中性     → 区间高抛低吸, 卖 straddle
  [-70,  -30)  偏空趋势     → 减仓/对冲, 买 put
  [-100, -70)  极度恐慌     → 左侧布局/抄底, 卖 put

Author: 小爪 for Stanley
"""

import json
import os
import time
import math
import datetime as dt
import traceback
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# ─────────────────────────── 配置 ───────────────────────────

BINANCE_BASE = "https://api.binance.com"
BINANCE_FAPI = "https://fapi.binance.com"
DERIBIT_BASE = "https://www.deribit.com/api/v2"
FNG_API = "https://api.alternative.me/fng/"

OUTPUT_DIR = Path(__file__).parent / "eth_reports"
OUTPUT_DIR.mkdir(exist_ok=True)

# Telegram 配置
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "").strip()
TG_API = f"https://api.telegram.org/bot{TG_BOT_TOKEN}" if TG_BOT_TOKEN else ""

# API Keys (from env)
FRED_API_KEY = os.environ.get("FRED_API_KEY", "").strip()
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "").strip()
CRYPTOPANIC_API_KEY = os.environ.get("CRYPTOPANIC_API_KEY", "").strip()
ETHERSCAN_API_KEY = os.environ.get("ETHERSCAN_API_KEY", "").strip()

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "ETH-Phase-Meter/1.0"})

# ─────────────────────────── 工具函数 ───────────────────────────


def safe_get(url, params=None, timeout=15):
    """安全 GET 请求, 失败返回 None"""
    try:
        r = SESSION.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  [WARN] GET {url} 失败: {e}")
        return None


def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def sma(series, period):
    return series.rolling(window=period).mean()


def clamp(val, lo, hi):
    return max(lo, min(hi, val))


# ═══════════════════════════════════════════════════════════════
#  第一维度: 技术面 + 衍生品 (满分 ±35)
# ═══════════════════════════════════════════════════════════════


def fetch_binance_klines(symbol="ETHUSDT", interval="4h", limit=200):
    """获取 K 线数据"""
    data = safe_get(f"{BINANCE_BASE}/api/v3/klines",
                    {"symbol": symbol, "interval": interval, "limit": limit})
    if not data:
        return None
    df = pd.DataFrame(data, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_vol", "trades", "taker_buy_vol",
        "taker_buy_quote", "ignore"
    ])
    for c in ["open", "high", "low", "close", "volume", "quote_vol",
              "taker_buy_vol", "taker_buy_quote"]:
        df[c] = df[c].astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    return df


def calc_macd(close, fast=12, slow=26, signal=9):
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    dif = ema_fast - ema_slow
    dea = ema(dif, signal)
    hist = (dif - dea) * 2
    return dif, dea, hist


def calc_rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_kdj(high, low, close, n=9, m1=3, m2=3):
    low_n = low.rolling(n).min()
    high_n = high.rolling(n).max()
    rsv = (close - low_n) / (high_n - low_n).replace(0, np.nan) * 100
    k = rsv.ewm(com=m1 - 1, adjust=False).mean()
    d = k.ewm(com=m2 - 1, adjust=False).mean()
    j = 3 * k - 2 * d
    return k, d, j


def score_technical(df):
    """
    技术面评分 (满分 ±25)
    - MA 趋势对齐:     ±5
    - MACD 状态:       ±5
    - RSI 状态:        ±5
    - KDJ 共振:        ±5
    - 关键价位突破:     ±5
    """
    if df is None or len(df) < 60:
        return 0, {}

    close = df["close"]
    high = df["high"]
    low = df["low"]
    last = close.iloc[-1]

    details = {"price": last}

    # --- MA 趋势 ---
    ma7 = sma(close, 7).iloc[-1]
    ma25 = sma(close, 25).iloc[-1]
    ma99 = sma(close, 99).iloc[-1]
    ma_score = 0
    if ma7 > ma25 > ma99:
        ma_score = 5  # 多头排列
    elif ma7 < ma25 < ma99:
        ma_score = -5  # 空头排列
    elif ma7 > ma25:
        ma_score = 2
    elif ma7 < ma25:
        ma_score = -2
    details["MA排列"] = f"MA7={ma7:.1f} MA25={ma25:.1f} MA99={ma99:.1f} → {ma_score:+d}"

    # --- MACD ---
    dif, dea, hist = calc_macd(close)
    macd_now = hist.iloc[-1]
    macd_prev = hist.iloc[-2]
    macd_score = 0
    if macd_now > 0 and macd_now > macd_prev:
        macd_score = 5  # 红柱放大
    elif macd_now > 0 and macd_now <= macd_prev:
        macd_score = 2  # 红柱缩小
    elif macd_now < 0 and macd_now > macd_prev:
        macd_score = -2  # 绿柱缩小
    elif macd_now < 0 and macd_now <= macd_prev:
        macd_score = -5  # 绿柱放大
    # 金叉/死叉加分
    if dif.iloc[-1] > dea.iloc[-1] and dif.iloc[-2] <= dea.iloc[-2]:
        macd_score = min(macd_score + 2, 5)  # 金叉
    elif dif.iloc[-1] < dea.iloc[-1] and dif.iloc[-2] >= dea.iloc[-2]:
        macd_score = max(macd_score - 2, -5)  # 死叉
    details["MACD"] = f"DIF={dif.iloc[-1]:.2f} DEA={dea.iloc[-1]:.2f} HIST={macd_now:.2f} → {macd_score:+d}"

    # --- RSI ---
    rsi = calc_rsi(close)
    rsi_val = rsi.iloc[-1]
    rsi_score = 0
    if rsi_val >= 80:
        rsi_score = -4  # 极度超买(反转信号)
    elif rsi_val >= 70:
        rsi_score = -2  # 超买
    elif rsi_val >= 55:
        rsi_score = 3  # 偏强
    elif rsi_val >= 45:
        rsi_score = 0  # 中性
    elif rsi_val >= 30:
        rsi_score = -3  # 偏弱
    elif rsi_val >= 20:
        rsi_score = 2  # 超卖(反弹信号)
    else:
        rsi_score = 4  # 极度超卖
    details["RSI"] = f"{rsi_val:.1f} → {rsi_score:+d}"

    # --- KDJ 共振 ---
    k, d, j = calc_kdj(high, low, close)
    kdj_score = 0
    k_val, d_val, j_val = k.iloc[-1], d.iloc[-1], j.iloc[-1]
    if j_val > 80 and k_val > d_val:
        kdj_score = 3
    elif j_val > 100:
        kdj_score = -2  # 超买钝化
    elif j_val < 20 and k_val < d_val:
        kdj_score = -3
    elif j_val < 0:
        kdj_score = 2  # 超卖反弹
    elif k_val > d_val:
        kdj_score = 2
    else:
        kdj_score = -2
    # KDJ 金叉/死叉
    if k.iloc[-1] > d.iloc[-1] and k.iloc[-2] <= d.iloc[-2] and j_val < 30:
        kdj_score = 5  # 低位金叉
    elif k.iloc[-1] < d.iloc[-1] and k.iloc[-2] >= d.iloc[-2] and j_val > 70:
        kdj_score = -5  # 高位死叉
    details["KDJ"] = f"K={k_val:.1f} D={d_val:.1f} J={j_val:.1f} → {kdj_score:+d}"

    # --- 关键价位 / 结构突破（A1） ---
    # 用多个回看窗口（根数）衡量结构：20/50/100 根
    def key_levels(lookback):
        hh = high.tail(lookback).max()
        ll = low.tail(lookback).min()
        return hh, ll

    lvl_20_h, lvl_20_l = key_levels(20)
    lvl_50_h, lvl_50_l = key_levels(50)
    lvl_100_h, lvl_100_l = key_levels(100)

    prev_close = close.iloc[-2]
    # 收盘确认突破/跌破（避免影线假突破）
    brk20_up = (prev_close <= lvl_20_h) and (last > lvl_20_h)
    brk20_dn = (prev_close >= lvl_20_l) and (last < lvl_20_l)
    brk50_up = (prev_close <= lvl_50_h) and (last > lvl_50_h)
    brk50_dn = (prev_close >= lvl_50_l) and (last < lvl_50_l)

    dist20h = (last / lvl_20_h - 1) if lvl_20_h else 0
    dist20l = (last / lvl_20_l - 1) if lvl_20_l else 0

    level_score = 0
    # 结构突破优先级：50 根 > 20 根
    if brk50_up:
        level_score = 5
        tag = "收盘突破50根前高"
    elif brk50_dn:
        level_score = -5
        tag = "收盘跌破50根前低"
    elif brk20_up:
        level_score = 3
        tag = "收盘突破20根前高"
    elif brk20_dn:
        level_score = -3
        tag = "收盘跌破20根前低"
    else:
        # 没有突破时，用位置评分（50根区间）
        range_pct = (last - lvl_50_l) / (lvl_50_h - lvl_50_l) if lvl_50_h != lvl_50_l else 0.5
        if range_pct > 0.9:
            level_score = 2
            tag = "逼近区间上沿"
        elif range_pct < 0.1:
            level_score = -2
            tag = "逼近区间下沿"
        else:
            level_score = 0
            tag = "区间中部"

    details["结构关键位"] = (
        f"20[{lvl_20_l:.0f}-{lvl_20_h:.0f}] 50[{lvl_50_l:.0f}-{lvl_50_h:.0f}] 100[{lvl_100_l:.0f}-{lvl_100_h:.0f}] | "
        f"{tag} → {level_score:+d}"
    )
    details["距离前高/前低(20)"] = f"距20H={dist20h:+.2%} 距20L={dist20l:+.2%}"

    # --- 趋势强度（A2）: ATR/ADX + 斜率 ---
    # ATR(14)
    tr = pd.concat([
        (high - low),
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean().iloc[-1]

    # ADX(14) 简版
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr14 = tr.rolling(14).sum()
    plus_di = 100 * (pd.Series(plus_dm).rolling(14).sum() / tr14)
    minus_di = 100 * (pd.Series(minus_dm).rolling(14).sum() / tr14)
    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di)).replace([np.inf, -np.inf], np.nan)
    adx14 = dx.rolling(14).mean().iloc[-1]

    # 价格斜率（最近 30 根）用 ATR 标准化
    n_slope = 30
    slope_score = 0
    if len(close) >= n_slope + 2 and atr14 and not np.isnan(atr14) and atr14 > 0:
        y = close.tail(n_slope).values
        x = np.arange(len(y))
        # 线性回归斜率（每根K线价格变化）
        b = np.polyfit(x, y, 1)[0]
        b_norm = b / atr14  # 每根ATR单位的斜率
        if b_norm > 0.12:
            slope_score = 3
        elif b_norm > 0.05:
            slope_score = 1
        elif b_norm < -0.12:
            slope_score = -3
        elif b_norm < -0.05:
            slope_score = -1
        details["趋势斜率(30)/ATR"] = f"{b_norm:+.3f} → {slope_score:+d}"
    else:
        details["趋势斜率(30)/ATR"] = "N/A → +0"

    adx_score = 0
    if not np.isnan(adx14):
        if adx14 >= 28:
            adx_score = 3
        elif adx14 >= 20:
            adx_score = 1
        else:
            adx_score = 0
    details["ATR14"] = f"{atr14:.2f}" if atr14 and not np.isnan(atr14) else "N/A"
    details["ADX14"] = f"{adx14:.1f} → {adx_score:+d}" if not np.isnan(adx14) else "N/A → +0"

    # 把趋势强度合并进原关键位项（保持总分仍为±25）
    # 这里把 level_score（±5）拆为：结构(±3~5) + 强度(±0~3) + 斜率(±0~3)，再截断到±5
    level_combo = clamp(level_score + adx_score + slope_score, -5, 5)
    details["关键位+强度合成"] = f"结构{level_score:+d} + ADX{adx_score:+d} + 斜率{slope_score:+d} → {level_combo:+d} (cap±5)"

    total = ma_score + macd_score + rsi_score + kdj_score + level_combo
    details["技术面总分"] = f"{total:+d}/±25"
    return total, details


def fetch_binance_derivatives(oi_limit=48, ratio_period="4h"):
    """获取衍生品数据: OI + 资金费率 + 多空比
    oi_limit: 5min 粒度的 OI 历史条数 (12=1h, 48=4h)
    ratio_period: 多空比/CVD/价格窗口的周期 ("1h", "4h")
    """
    result = {"ratio_period": ratio_period}

    # 持仓量(OI)
    oi = safe_get(f"{BINANCE_FAPI}/fapi/v1/openInterest", {"symbol": "ETHUSDT"})
    if oi:
        result["OI"] = float(oi.get("openInterest", 0))

    # OI 历史 (5min 粒度)
    oi_hist = safe_get(f"{BINANCE_FAPI}/futures/data/openInterestHist",
                       {"symbol": "ETHUSDT", "period": "5m", "limit": oi_limit})
    if oi_hist and len(oi_hist) >= 2:
        oi_start = float(oi_hist[0]["sumOpenInterest"])
        oi_end = float(oi_hist[-1]["sumOpenInterest"])
        chg = (oi_end - oi_start) / oi_start if oi_start else 0
        # 窗口小时数（5min 粒度）
        window_hours = (len(oi_hist) * 5) / 60
        result["oi_window_hours"] = window_hours
        result["oi_change_window"] = chg
        # backward compat
        result["OI_change_4h"] = chg

    # 资金费率（最新 + 分位数参考 B2）
    fr = safe_get(f"{BINANCE_FAPI}/fapi/v1/fundingRate",
                  {"symbol": "ETHUSDT", "limit": 1})
    if fr:
        result["funding_rate"] = float(fr[0].get("fundingRate", 0))

    # 资金费率历史（默认取近30天，每8h一条 ≈ 90 条）
    fr_hist = safe_get(f"{BINANCE_FAPI}/fapi/v1/fundingRate",
                       {"symbol": "ETHUSDT", "limit": 200})
    if fr_hist and isinstance(fr_hist, list) and len(fr_hist) >= 10:
        rates = [float(x.get("fundingRate", 0)) for x in fr_hist if x.get("fundingRate") is not None]
        rates = [r for r in rates if not math.isnan(r)]
        if rates:
            result["funding_hist"] = rates
            # 分位数：最新 funding 在历史里的位置（0~1）
            latest = result.get("funding_rate", rates[0])
            sorted_rates = sorted(rates)
            # rank: <= latest
            rank = sum(1 for r in sorted_rates if r <= latest)
            result["funding_percentile"] = rank / len(sorted_rates)

    # 同周期价格变化（用于 OI×价格四象限 B1）
    px_klines = safe_get(f"{BINANCE_FAPI}/fapi/v1/klines",
                         {"symbol": "ETHUSDT", "interval": ratio_period, "limit": 3})
    if px_klines and len(px_klines) >= 2:
        # close 是第5列
        c0 = float(px_klines[-2][4])
        c1 = float(px_klines[-1][4])
        result["price_change_period"] = (c1 - c0) / c0 if c0 else 0

    # 多空比 (top trader)
    lsr = safe_get(f"{BINANCE_FAPI}/futures/data/topLongShortAccountRatio",
                   {"symbol": "ETHUSDT", "period": ratio_period, "limit": 1})
    if lsr:
        result["long_short_ratio"] = float(lsr[0].get("longShortRatio", 1))

    # Taker Buy/Sell Ratio (多空比方式)
    taker = safe_get(f"{BINANCE_FAPI}/futures/data/takerlongshortRatio",
                     {"symbol": "ETHUSDT", "period": ratio_period, "limit": 10})
    if taker:
        ratios = [float(t["buySellRatio"]) for t in taker]
        result["taker_buy_sell_avg"] = sum(ratios) / len(ratios)
        result["taker_buy_sell_latest"] = ratios[-1] if ratios else 1
        # 趋势: 最近 5 条 vs 前 5 条
        if len(ratios) >= 6:
            recent = sum(ratios[len(ratios)//2:]) / (len(ratios) - len(ratios)//2)
            earlier = sum(ratios[:len(ratios)//2]) / (len(ratios)//2)
            result["taker_trend"] = recent - earlier  # >0 买方增强, <0 卖方增强

    # 真实 CVD (从合约 K 线的 taker buy volume 计算)
    # aggTrades 太大, 用 klines 的 taker_buy_quote_vol 近似
    cvd_klines = safe_get(f"{BINANCE_FAPI}/fapi/v1/klines",
                          {"symbol": "ETHUSDT", "interval": ratio_period, "limit": 20})
    if cvd_klines:
        cvd_values = []
        cumulative = 0
        for k in cvd_klines:
            quote_vol = float(k[7])        # 总成交额 (USDT)
            taker_buy_vol = float(k[10])   # taker 买入成交额
            taker_sell_vol = quote_vol - taker_buy_vol
            net = taker_buy_vol - taker_sell_vol  # 正=净买入, 负=净卖出
            cumulative += net
            cvd_values.append(cumulative)
        result["cvd_values"] = cvd_values
        result["cvd_current"] = cvd_values[-1] if cvd_values else 0
        # CVD 变化: 最近值 vs 中间值
        if len(cvd_values) >= 4:
            mid = len(cvd_values) // 2
            result["cvd_recent"] = cvd_values[-1]
            result["cvd_mid"] = cvd_values[mid]
            result["cvd_start"] = cvd_values[0]
            # 斜率 (后半段 vs 前半段)
            result["cvd_slope_recent"] = cvd_values[-1] - cvd_values[mid]
            result["cvd_slope_earlier"] = cvd_values[mid] - cvd_values[0]

    return result


def score_derivatives(deriv):
    """
    衍生品评分 (满分 ±10)
    - OI 变化 + 资金费率 + 多空比 + CVD
    """
    if not deriv:
        return 0, {}

    details = {}
    score = 0

    # B1: OI × 价格 四象限（先记录，再打分）
    oi_chg = deriv.get("oi_change_window", deriv.get("OI_change_4h", 0))
    oi_hours = deriv.get("oi_window_hours", None)
    px_chg = deriv.get("price_change_period", 0)

    # 价格变化打一个轻权重分（短线更关注）
    px_score = 0
    if px_chg > 0.01:
        px_score = 1
    elif px_chg < -0.01:
        px_score = -1

    # OI 变化基础分（仍保留）
    oi_score = 0
    if oi_chg > 0.05:
        oi_score = 2
    elif oi_chg > 0.02:
        oi_score = 1
    elif oi_chg < -0.05:
        oi_score = -2
    elif oi_chg < -0.02:
        oi_score = -1

    # 四象限解释（不直接加太多分，主要用于策略判断）
    quadrant = ""
    quad_score = 0
    if px_chg > 0 and oi_chg > 0:
        quadrant = "价↑OI↑ 趋势增仓(强)"
        quad_score = 2
    elif px_chg > 0 and oi_chg < 0:
        quadrant = "价↑OI↓ 空头回补(偏弱)"
        quad_score = 0
    elif px_chg < 0 and oi_chg > 0:
        quadrant = "价↓OI↑ 空头增仓(强空)"
        quad_score = -2
    elif px_chg < 0 and oi_chg < 0:
        quadrant = "价↓OI↓ 去杠杆/多头止损(尾声)"
        quad_score = -1
    else:
        quadrant = "价≈0 或 OI≈0 结构不明"
        quad_score = 0

    score += (oi_score + px_score + quad_score)
    oi_w = f"{oi_hours:.1f}h" if oi_hours is not None else "窗口"
    details["OI变化(窗口)"] = f"{oi_chg:+.2%} ({oi_w}) → {oi_score:+d}"
    details["价格变化(窗口)"] = f"{px_chg:+.2%} ({deriv.get('ratio_period', '窗口')}) → {px_score:+d}"
    details["OI×价格象限"] = f"{quadrant} → {quad_score:+d}"

    # 四象限 → 短线策略提示
    tip = ""
    if px_chg > 0 and oi_chg > 0:
        tip = "顺势为主：回踩不破关键位做多/突破追多；止损放在结构位下方；避免逆势抄顶"
    elif px_chg > 0 and oi_chg < 0:
        tip = "上涨偏回补：不追高，等回踩确认再多；更适合快进快出/区间上沿减仓"
    elif px_chg < 0 and oi_chg > 0:
        tip = "空头增仓：反弹优先做空/卖出；做多只做超短反抽且严格止损；关注破位加速"
    elif px_chg < 0 and oi_chg < 0:
        tip = "去杠杆尾声：可等恐慌后博反弹，但必须看到卖压衰竭信号（CVD转正/跌不动）；仓位小"
    else:
        tip = "结构不明：降低仓位，等突破/回踩给方向"
    details["短线策略提示(OI×价格)"] = tip

    # B2: 资金费率分位数（替换原来的绝对阈值）
    fr = deriv.get("funding_rate", 0)
    pct = deriv.get("funding_percentile", None)
    fr_score = 0
    if pct is None:
        # 回退：绝对阈值
        if fr > 0.001:
            fr_score = -2
        elif fr > 0.0005:
            fr_score = 1
        elif fr < -0.001:
            fr_score = 2
        elif fr < -0.0005:
            fr_score = -1
        else:
            fr_score = 0
        details["资金费率(无分位)"] = f"{fr:.4%} → {fr_score:+d}"
    else:
        # 分位解释：高分位=拥挤多头(反指)，低分位=拥挤空头(反弹)
        if pct >= 0.95:
            fr_score = -2
            lab = "极高(拥挤多)"
        elif pct >= 0.80:
            fr_score = -1
            lab = "偏高"
        elif pct <= 0.05:
            fr_score = 2
            lab = "极低(拥挤空)"
        elif pct <= 0.20:
            fr_score = 1
            lab = "偏低"
        else:
            fr_score = 0
            lab = "中性"
        details["资金费率分位"] = f"{fr:.4%} | pct={pct:.0%} {lab} → {fr_score:+d}"
    score += fr_score

    # 多空比
    lsr = deriv.get("long_short_ratio", 1)
    if lsr > 2.0:
        s = -2  # 过度偏多(反指)
    elif lsr > 1.2:
        s = 1
    elif lsr < 0.5:
        s = 2  # 过度偏空(反弹信号)
    elif lsr < 0.8:
        s = -1
    else:
        s = 0
    score += s
    details["多空比"] = f"{lsr:.2f} → {s:+d}"

    # ── CVD 综合 (买卖比 + 累积值 + 趋势) ──

    # CVD 买卖比
    cvd_ratio = deriv.get("taker_buy_sell_avg", 1)
    cvd_latest = deriv.get("taker_buy_sell_latest", cvd_ratio)
    if cvd_ratio > 1.1:
        s = 1
    elif cvd_ratio < 0.9:
        s = -1
    else:
        s = 0
    score += s
    details["CVD买卖比"] = f"均值={cvd_ratio:.3f} 最新={cvd_latest:.3f} → {s:+d}"

    # CVD 累积净值 (USDT)
    cvd_current = deriv.get("cvd_current", 0)
    cvd_abs = abs(cvd_current)
    # 用百万 USDT 为单位展示
    cvd_m = cvd_current / 1e6
    if cvd_current > 5e6:
        s = 1  # 净买入 > 500万U
    elif cvd_current < -5e6:
        s = -1  # 净卖出 > 500万U
    else:
        s = 0
    score += s
    details["CVD累积净值"] = f"{cvd_m:+.2f}M USDT → {s:+d}"

    # CVD 趋势变化 (后半段斜率 vs 前半段)
    slope_recent = deriv.get("cvd_slope_recent", 0)
    slope_earlier = deriv.get("cvd_slope_earlier", 0)
    taker_trend = deriv.get("taker_trend", 0)
    trend_label = ""
    if slope_recent > 0 and slope_recent > slope_earlier:
        trend_label = "📈 买方加速"
        s = 1
    elif slope_recent > 0 and slope_recent <= slope_earlier:
        trend_label = "📈 买方减速"
        s = 0
    elif slope_recent < 0 and slope_recent < slope_earlier:
        trend_label = "📉 卖方加速"
        s = -1
    elif slope_recent < 0 and slope_recent >= slope_earlier:
        trend_label = "📉 卖方减速"
        s = 0
    else:
        trend_label = "⏸ 平衡"
        s = 0
    score += s
    sr_m = slope_recent / 1e6
    se_m = slope_earlier / 1e6
    details["CVD趋势"] = f"{trend_label} | 后半={sr_m:+.2f}M 前半={se_m:+.2f}M → {s:+d}"

    score = clamp(score, -10, 10)
    details["衍生品总分"] = f"{score:+d}/±10"
    return score, details


# ═══════════════════════════════════════════════════════════════
#  第二维度: 期权结构 (满分 ±25)
# ═══════════════════════════════════════════════════════════════


def fetch_deribit_options():
    """从 Deribit 获取 ETH 期权数据"""
    result = {}

    # 汇总数据
    summary = safe_get(f"{DERIBIT_BASE}/public/get_book_summary_by_currency",
                       {"currency": "ETH", "kind": "option"})
    if not summary or "result" not in summary:
        return result

    options = summary["result"]

    total_call_oi = 0
    total_put_oi = 0
    total_call_vol = 0
    total_put_vol = 0

    # 解析每个期权的到期日、行权价、IV
    # Deribit instrument name 格式: ETH-13FEB26-2700-C
    from datetime import datetime as _dt
    expiry_options = {}  # {expiry_str: [(strike, iv, type, oi), ...]}

    for opt in options:
        name = opt.get("instrument_name", "")
        oi = float(opt.get("open_interest", 0) or 0)
        vol = opt.get("volume", 0) or 0
        iv = opt.get("mark_iv", 0) or 0

        if "-C" in name:
            total_call_oi += oi
            total_call_vol += vol
        elif "-P" in name:
            total_put_oi += oi
            total_put_vol += vol

        # 解析到期日和行权价
        parts = name.split("-")
        if len(parts) >= 4 and iv and iv > 0:
            expiry_str = parts[1]  # e.g. "13FEB26"
            try:
                strike = float(parts[2])
            except (ValueError, IndexError):
                continue
            opt_type = parts[3]  # C or P
            if expiry_str not in expiry_options:
                expiry_options[expiry_str] = []
            expiry_options[expiry_str].append((strike, iv, opt_type, oi))

    result["call_oi"] = total_call_oi
    result["put_oi"] = total_put_oi
    result["put_call_oi_ratio"] = total_put_oi / total_call_oi if total_call_oi else 0
    result["call_vol"] = total_call_vol
    result["put_vol"] = total_put_vol
    result["put_call_vol_ratio"] = total_put_vol / total_call_vol if total_call_vol else 0

    # ETH index price
    idx = safe_get(f"{DERIBIT_BASE}/public/get_index_price",
                   {"index_name": "eth_usd"})
    spot = 0
    if idx and "result" in idx:
        spot = idx["result"].get("index_price", 0)
        result["index_price"] = spot

    # ── ATM IV near / ATM IV next ──
    # 按到期日排序，找最近两个到期日的 ATM IV
    def parse_expiry(s):
        """解析 Deribit 到期日字符串, e.g. '13FEB26' → datetime"""
        try:
            return _dt.strptime(s, "%d%b%y")
        except Exception:
            return None

    now = _dt.utcnow()
    sorted_expiries = []
    for exp_str in expiry_options:
        exp_dt = parse_expiry(exp_str)
        if exp_dt and exp_dt > now:
            sorted_expiries.append((exp_dt, exp_str))
    sorted_expiries.sort(key=lambda x: x[0])

    def find_atm_iv(exp_str):
        """找指定到期日中最接近 spot 的行权价的 ATM IV (call+put 平均)"""
        if not spot or exp_str not in expiry_options:
            return 0, 0
        opts_list = expiry_options[exp_str]
        calls = [(s, iv) for s, iv, t, _oi in opts_list if t == "C"]
        puts = [(s, iv) for s, iv, t, _oi in opts_list if t == "P"]
        if not calls:
            return 0, 0
        calls.sort(key=lambda x: abs(x[0] - spot))
        atm_strike = calls[0][0]
        atm_call_iv = calls[0][1]
        atm_put_iv = next((iv for s, iv in puts if s == atm_strike), atm_call_iv)
        atm_iv = (atm_call_iv + atm_put_iv) / 2
        return atm_iv, atm_strike

    def find_iv_near_strike(exp_str, target_strike, opt_type):
        """找指定到期日、指定类型(call/put)中最接近 target_strike 的 IV"""
        if exp_str not in expiry_options:
            return 0, 0
        opts_list = [(s, iv) for s, iv, t, _oi in expiry_options[exp_str] if t == opt_type]
        if not opts_list:
            return 0, 0
        opts_list.sort(key=lambda x: abs(x[0] - target_strike))
        return opts_list[0][1], opts_list[0][0]

    def top_oi_strikes(exp_str, topn=3):
        """C3: 按 strike 汇总 OI，返回 topn"""
        if exp_str not in expiry_options:
            return []
        m = {}
        for s, _iv, _t, oi in expiry_options[exp_str]:
            m[s] = m.get(s, 0.0) + float(oi or 0)
        items = sorted(m.items(), key=lambda x: x[1], reverse=True)
        return items[:topn]

    if len(sorted_expiries) >= 1:
        near_exp = sorted_expiries[0][1]
        near_iv, near_strike = find_atm_iv(near_exp)
        result["atm_iv_near"] = near_iv
        result["atm_iv_near_expiry"] = near_exp
        result["atm_iv_near_strike"] = near_strike

        # C1/C2: 用“近月”做 skew proxy（OTM put vs OTM call）
        if spot:
            put_target = spot * 0.90
            call_target = spot * 1.10
            put_iv, put_k = find_iv_near_strike(near_exp, put_target, "P")
            call_iv, call_k = find_iv_near_strike(near_exp, call_target, "C")
            result["otm_put_iv_near"] = put_iv
            result["otm_put_strike_near"] = put_k
            result["otm_call_iv_near"] = call_iv
            result["otm_call_strike_near"] = call_k
            if put_iv and call_iv:
                result["iv_skew_25d_proxy_near"] = put_iv - call_iv  # >0 恐慌偏度

        # C3: 近月 OI 集中度（top strikes）
        tops = top_oi_strikes(near_exp, topn=3)
        if tops:
            result["oi_top_strikes_near"] = tops

    if len(sorted_expiries) >= 2:
        next_exp = sorted_expiries[1][1]
        next_iv, next_strike = find_atm_iv(next_exp)
        result["atm_iv_next"] = next_iv
        result["atm_iv_next_expiry"] = next_exp
        result["atm_iv_next_strike"] = next_strike

    # DVol (Deribit 波动率指数)
    dvol = safe_get(f"{DERIBIT_BASE}/public/get_volatility_index_data",
                    {"currency": "ETH", "resolution": "3600", "start_timestamp": int((time.time() - 86400) * 1000),
                     "end_timestamp": int(time.time() * 1000)})
    if dvol and "result" in dvol and dvol["result"].get("data"):
        data_points = dvol["result"]["data"]
        result["dvol_current"] = data_points[-1][1] if data_points else 0
        if len(data_points) >= 2:
            result["dvol_prev"] = data_points[0][1]

    return result


def score_options(opts):
    """
    期权结构评分 (满分 ±25)
    - Put/Call OI 比率:   ±7
    - Put/Call 成交量比:  ±6
    - IV 水平:           ±6
    - DVol 趋势:         ±6
    """
    if not opts:
        return 0, {}

    details = {}
    score = 0

    # Put/Call OI Ratio: >1 = 保护性多, <0.5 = 过度乐观
    pcr_oi = opts.get("put_call_oi_ratio", 0.7)
    if pcr_oi > 1.2:
        s = -5  # 极度恐慌对冲
    elif pcr_oi > 0.9:
        s = -2  # 偏空保护
    elif pcr_oi > 0.6:
        s = 3  # 健康偏多
    elif pcr_oi > 0.4:
        s = 5  # 偏多
    else:
        s = -3  # 过度乐观(反指)
    score += s
    details["P/C OI比"] = f"{pcr_oi:.3f} → {s:+d}"

    # Put/Call Volume Ratio
    pcr_vol = opts.get("put_call_vol_ratio", 0.7)
    if pcr_vol > 1.5:
        s = -5
    elif pcr_vol > 1.0:
        s = -2
    elif pcr_vol > 0.5:
        s = 3
    elif pcr_vol > 0.3:
        s = 5
    else:
        s = -2
    score += s
    details["P/C成交量比"] = f"{pcr_vol:.3f} → {s:+d}"

    # ATM IV Near (近月, ±3)
    atm_near = opts.get("atm_iv_near", 50)
    near_exp = opts.get("atm_iv_near_expiry", "?")
    near_strike = opts.get("atm_iv_near_strike", 0)
    if atm_near > 100:
        s = -3  # 极高=恐慌
    elif atm_near > 75:
        s = -1
    elif atm_near > 40:
        s = 2  # 温和
    elif atm_near > 25:
        s = 3  # 低IV=便宜期权
    else:
        s = 1  # 极低=暴风雨前的平静
    score += s
    details["ATM IV Near"] = f"{atm_near:.1f}% (到期{near_exp} K={near_strike:.0f}) → {s:+d}"

    # ATM IV Next (次月, ±3)
    atm_next = opts.get("atm_iv_next", 50)
    next_exp = opts.get("atm_iv_next_expiry", "?")
    next_strike = opts.get("atm_iv_next_strike", 0)
    if atm_next > 100:
        s = -3
    elif atm_next > 75:
        s = -1
    elif atm_next > 40:
        s = 2
    elif atm_next > 25:
        s = 3
    else:
        s = 1
    score += s
    details["ATM IV Next"] = f"{atm_next:.1f}% (到期{next_exp} K={next_strike:.0f}) → {s:+d}"

    # IV 期限结构 (near vs next)
    if atm_near > 0 and atm_next > 0:
        iv_spread = atm_near - atm_next
        if iv_spread > 10:
            details["IV期限结构"] = f"Backwardation (近-次={iv_spread:+.1f}%) → 短期恐慌"
        elif iv_spread < -10:
            details["IV期限结构"] = f"Contango (近-次={iv_spread:+.1f}%) → 远期不确定性高"
        else:
            details["IV期限结构"] = f"平坦 (近-次={iv_spread:+.1f}%)"

    # C1/C2: 偏度（用 OTM Put IV - OTM Call IV 近似 RR/Skew）
    put_iv = opts.get("otm_put_iv_near", 0)
    call_iv = opts.get("otm_call_iv_near", 0)
    skew = opts.get("iv_skew_25d_proxy_near", 0)
    if put_iv and call_iv:
        details["OTM Put IV(Near)"] = f"{put_iv:.1f}% (K={opts.get('otm_put_strike_near',0):.0f})"
        details["OTM Call IV(Near)"] = f"{call_iv:.1f}% (K={opts.get('otm_call_strike_near',0):.0f})"
        # skew > 0: put 更贵（恐慌/保护需求）；skew < 0: call 更贵（追涨）
        if skew > 8:
            s2 = -2
            lab = "偏度极高(保护需求强)"
        elif skew > 3:
            s2 = -1
            lab = "偏度偏高"
        elif skew < -3:
            s2 = 1
            lab = "call偏贵(追涨)"
        else:
            s2 = 0
            lab = "偏度中性"
        score += s2
        details["IV偏度(近月proxy)"] = f"put-call={skew:+.1f}% {lab} → {s2:+d}"

    # C3: OI 集中（近月 top strikes）
    tops = opts.get("oi_top_strikes_near")
    if tops:
        # tops: [(strike, oi), ...]
        pretty = ", ".join([f"{s:.0f}:{oi:.0f}" for s, oi in tops])
        details["OI集中(近月Top3)"] = pretty
        details["OI结构提示"] = "OI 集中位可能出现 pin/max-pain 行为；价格靠近集中位时，短线更偏震荡/回归"

    # DVol 趋势
    dvol = opts.get("dvol_current", 0)
    dvol_prev = opts.get("dvol_prev", dvol)
    dvol_chg = dvol - dvol_prev
    if dvol_chg > 10:
        s = -4  # 波动急升=恐慌
    elif dvol_chg > 3:
        s = -2
    elif dvol_chg < -10:
        s = 4  # 波动下降=信心
    elif dvol_chg < -3:
        s = 2
    else:
        s = 0
    score += s
    details["DVol"] = f"{dvol:.1f}(Δ{dvol_chg:+.1f}) → {s:+d}"

    score = clamp(score, -25, 25)
    details["期权总分"] = f"{score:+d}/±25"
    return score, details


# ═══════════════════════════════════════════════════════════════
#  第三维度: 社交情绪 (满分 ±15)
# ═══════════════════════════════════════════════════════════════


def fetch_sentiment():
    """获取市场情绪数据"""
    result = {}

    # Fear & Greed Index
    fng = safe_get(FNG_API, {"limit": 7})
    if fng and fng.get("data"):
        entries = fng["data"]
        result["fng_value"] = int(entries[0].get("value", 50))
        result["fng_label"] = entries[0].get("value_classification", "Neutral")
        if len(entries) >= 7:
            result["fng_7d_avg"] = sum(int(e["value"]) for e in entries) / len(entries)
        result["fng_prev"] = int(entries[1]["value"]) if len(entries) > 1 else result["fng_value"]

    # Binance 24h ticker (价格变化 as sentiment proxy)
    ticker = safe_get(f"{BINANCE_BASE}/api/v3/ticker/24hr", {"symbol": "ETHUSDT"})
    if ticker:
        result["price_change_24h"] = float(ticker.get("priceChangePercent", 0))
        result["volume_24h"] = float(ticker.get("quoteVolume", 0))

    return result


def score_sentiment(sent):
    """
    情绪评分 (满分 ±15)
    注意: 情绪作为反向指标在极端时特别有效
    - Fear & Greed 指数:   ±7
    - 情绪变化趋势:       ±4
    - 价格动量辅助:       ±4
    """
    if not sent:
        return 0, {}

    details = {}
    score = 0

    fng = sent.get("fng_value", 50)
    # 华尔街逻辑: 极端情绪是反指, 温和情绪顺势
    if fng >= 90:
        s = -5  # 极度贪婪 → 见顶风险
    elif fng >= 75:
        s = -2  # 贪婪
    elif fng >= 55:
        s = 4  # 温和偏贪婪 → 趋势健康
    elif fng >= 45:
        s = 0  # 中性
    elif fng >= 25:
        s = -3  # 恐惧
    elif fng >= 10:
        s = 3  # 极度恐惧 → 反弹机会
    else:
        s = 6  # 恐慌投降 → 强烈反指
    score += s
    details["恐贪指数"] = f"{fng} ({sent.get('fng_label', 'N/A')}) → {s:+d}"

    # 情绪趋势
    fng_prev = sent.get("fng_prev", fng)
    fng_7d = sent.get("fng_7d_avg", fng)
    if fng > fng_prev and fng > fng_7d:
        s = 2  # 情绪转暖
    elif fng < fng_prev and fng < fng_7d:
        s = -2  # 情绪转冷
    else:
        s = 0
    score += s
    details["情绪趋势"] = f"当前={fng} 前值={fng_prev} 7D均值={fng_7d:.0f} → {s:+d}"

    # 24h 价格动量
    pchg = sent.get("price_change_24h", 0)
    if pchg > 5:
        s = 3
    elif pchg > 2:
        s = 2
    elif pchg < -5:
        s = -3
    elif pchg < -2:
        s = -2
    else:
        s = 0
    score += s
    details["24h涨跌"] = f"{pchg:+.2f}% → {s:+d}"

    score = clamp(score, -15, 15)
    details["情绪总分"] = f"{score:+d}/±15"
    return score, details


# ═══════════════════════════════════════════════════════════════
#  第四维度: 宏观经济 (满分 ±25)
# ═══════════════════════════════════════════════════════════════


def fetch_stooq_daily(symbol: str):
    """从 stooq 拉取日线 OHLC（无需 key）。返回最近两天 close。"""
    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
    try:
        r = SESSION.get(url, timeout=15)
        r.raise_for_status()
        lines = r.text.strip().splitlines()
        if len(lines) < 3:
            return None
        # csv: Date,Open,High,Low,Close,Volume
        last = lines[-1].split(',')
        prev = lines[-2].split(',')
        return {
            "symbol": symbol,
            "date": last[0],
            "close": float(last[4]),
            "prev_date": prev[0],
            "prev_close": float(prev[4]),
        }
    except Exception as e:
        print(f"  [WARN] stooq {symbol} 失败: {e}")
        return None


# ─── FRED ───
def fetch_fred_series(series_id: str, limit: int = 5):
    """从 FRED 拉取最近 N 个观测值"""
    if not FRED_API_KEY:
        return None
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit,
    }
    try:
        r = SESSION.get(url, params=params, timeout=15)
        r.raise_for_status()
        obs = r.json().get("observations", [])
        # 过滤掉 value="." 的占位行
        valid = [o for o in obs if o.get("value", ".") not in (".", "")]
        if not valid:
            return None
        return valid  # 最新在前
    except Exception as e:
        print(f"  [WARN] FRED {series_id} 失败: {e}")
        return None


def fred_latest_and_change(series_id: str):
    """返回 (latest_value, day_change_pct)"""
    obs = fetch_fred_series(series_id, limit=5)
    if not obs or len(obs) < 2:
        if obs and len(obs) == 1:
            return float(obs[0]["value"]), None
        return None, None
    latest = float(obs[0]["value"])
    prev = float(obs[1]["value"])
    chg = (latest - prev) / abs(prev) if prev else 0
    return latest, chg


# ─── yfinance 备选 ───
def fetch_yfinance_quote(ticker: str):
    """用 yfinance 拉取最近两日收盘 (备选)"""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period="5d")
        if hist is None or len(hist) < 2:
            return None, None
        latest = float(hist["Close"].iloc[-1])
        prev = float(hist["Close"].iloc[-2])
        chg = (latest - prev) / abs(prev) if prev else 0
        return latest, chg
    except Exception as e:
        print(f"  [WARN] yfinance {ticker} 失败: {e}")
        return None, None


def get_macro_indicator(fred_id: str, yf_ticker: str):
    """FRED 优先，失败回退 yfinance"""
    val, chg = fred_latest_and_change(fred_id)
    if val is not None:
        return val, chg, "FRED"
    val, chg = fetch_yfinance_quote(yf_ticker)
    if val is not None:
        return val, chg, "yfinance"
    return None, None, None


# ─── Finnhub 经济日历 + 新闻 ───
def fetch_econ_calendar():
    """获取经济相关新闻（Finnhub general news 里筛选关键词）
    注: Finnhub /calendar/economic 是 Premium，改用 news 里关键词匹配"""
    if not FINNHUB_API_KEY:
        return []
    try:
        url = "https://finnhub.io/api/v1/news"
        params = {"category": "general", "token": FINNHUB_API_KEY}
        r = SESSION.get(url, params=params, timeout=15)
        r.raise_for_status()
        articles = r.json() if isinstance(r.json(), list) else []

        # 用关键词匹配经济数据相关新闻
        keywords = ["nonfarm", "payroll", "cpi", "inflation", "fomc", "fed rate",
                     "rate decision", "ppi", "gdp", "unemployment", "consumer price",
                     "treasury", "yield", "jobs report", "retail sales", "ism"]
        matched = []
        for a in articles:
            headline = (a.get("headline", "") + " " + a.get("summary", "")).lower()
            if any(kw in headline for kw in keywords):
                matched.append({
                    "event": a.get("headline", "")[:100],
                    "source": a.get("source", ""),
                    "url": a.get("url", ""),
                })
        return matched[:5]
    except Exception as e:
        print(f"  [WARN] Finnhub 经济新闻失败: {e}")
        return []


# ─── CryptoPanic 加密新闻（恢复） ───
# 需求：阶段仪仍按 interval 推送；但 CryptoPanic API 只每天拉取一次。
# 做法：将 CryptoPanic 结果缓存到本地文件，并用 24h TTL 节流；未到 TTL 时复用旧新闻。

def _cryptopanic_cache_path() -> str:
    try:
        base = os.path.join(os.path.dirname(__file__), "eth_reports", "cache")
    except Exception:
        base = os.path.join(os.getcwd(), "eth_reports", "cache")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "cryptopanic_eth.json")


def _load_cryptopanic_cache(max_age_seconds: int = 86400):
    path = _cryptopanic_cache_path()
    try:
        if not os.path.exists(path):
            return None
        mtime = os.path.getmtime(path)
        if (time.time() - mtime) > max_age_seconds:
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_cryptopanic_cache(payload: dict):
    path = _cryptopanic_cache_path()
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        pass


def fetch_crypto_news():
    """获取 ETH 相关新闻 + 情绪（CryptoPanic API developer/v2）。

    注意：为了降低 API 调用频率，本函数会优先读取 24h 内缓存。
    """
    # 1) 没 key：走 Finnhub（现有逻辑）
    if not CRYPTOPANIC_API_KEY:
        return _fetch_crypto_news_finnhub()

    # 2) 有缓存且未过期：直接复用旧新闻
    cached = _load_cryptopanic_cache(max_age_seconds=86400)
    if cached:
        cached["cached"] = True
        cached.setdefault("source", "CryptoPanic")
        return cached

    # 3) 缓存过期：当天第一次才请求 CryptoPanic
    try:
        url = "https://cryptopanic.com/api/developer/v2/posts/"
        params = {
            "auth_token": CRYPTOPANIC_API_KEY,
            "currencies": "ETH",
        }
        r = SESSION.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        posts = data.get("results", [])[:15]

        if not posts:
            return _fetch_crypto_news_finnhub()

        # Developer 级别只有 title+description，用关键词做情绪
        bullish_words = ["surge", "soar", "rally", "bullish", "pump", "gain", "record",
                         "approval", "adopt", "milestone", "breakout", "recovery",
                         "upgrade", "accumulating", "inflow", "all-time", "support"]
        bearish_words = ["crash", "plunge", "dump", "bearish", "fall", "drop", "ban",
                         "hack", "exploit", "lawsuit", "sell-off", "decline", "fear",
                         "collapse", "risk", "outflow", "liquidat", "warning"]

        bullish = 0
        bearish = 0
        for p in posts:
            text = (p.get("title", "") + " " + (p.get("description", "") or "")).lower()
            is_bull = any(w in text for w in bullish_words)
            is_bear = any(w in text for w in bearish_words)
            if is_bull and not is_bear:
                bullish += 1
            elif is_bear and not is_bull:
                bearish += 1

        total = len(posts)
        sentiment = "neutral"
        if total > 0:
            if bullish > bearish + 1:
                sentiment = "bullish"
            elif bearish > bullish + 1:
                sentiment = "bearish"

        post_items = [{"title": p.get("title", ""), "source": "CryptoPanic"} for p in posts]

        payload = {
            "posts": post_items,
            "bullish": bullish,
            "bearish": bearish,
            "total": total,
            "sentiment": sentiment,
            "source": "CryptoPanic",
            "cached": False,
        }
        _save_cryptopanic_cache(payload)
        return payload
    except Exception as e:
        print(f"  [WARN] CryptoPanic 失败: {e}, 回退 Finnhub")
        return _fetch_crypto_news_finnhub()


def _fetch_crypto_news_finnhub():
    """备选：Finnhub crypto news"""
    if not FINNHUB_API_KEY:
        return {"posts": [], "sentiment": None}
    try:
        url = "https://finnhub.io/api/v1/news"
        params = {"category": "crypto", "token": FINNHUB_API_KEY}
        r = SESSION.get(url, params=params, timeout=15)
        r.raise_for_status()
        articles = r.json() if isinstance(r.json(), list) else []

        eth_keywords = ["eth", "ethereum", "ether", "vitalik", "layer 2", "l2",
                         "defi", "staking"]
        broad_keywords = ["crypto", "bitcoin", "btc", "sec", "regulation", "binance",
                           "coinbase", "blackrock", "etf"]

        eth_news = []
        broad_news = []
        for a in articles:
            headline = a.get("headline", "").lower()
            if any(kw in headline for kw in eth_keywords):
                eth_news.append(a)
            elif any(kw in headline for kw in broad_keywords):
                broad_news.append(a)

        all_news = (eth_news[:5] + broad_news[:5])[:10]

        bullish_words = ["surge", "soar", "rally", "bullish", "pump", "high", "gain",
                          "record", "approval", "adopt", "milestone", "breakout", "up"]
        bearish_words = ["crash", "plunge", "dump", "bearish", "fall", "drop", "ban",
                          "hack", "exploit", "lawsuit", "sell", "decline", "fear", "risk"]

        bull_count = 0
        bear_count = 0
        for a in all_news:
            h = a.get("headline", "").lower()
            if any(w in h for w in bullish_words):
                bull_count += 1
            if any(w in h for w in bearish_words):
                bear_count += 1

        total = len(all_news)
        sentiment = "neutral"
        if total > 0:
            if bull_count > bear_count + 1:
                sentiment = "bullish"
            elif bear_count > bull_count + 1:
                sentiment = "bearish"

        posts = [{"title": a.get("headline", ""), "source": a.get("source", "")}
                 for a in all_news]

        return {
            "posts": posts,
            "bullish": bull_count,
            "bearish": bear_count,
            "total": total,
            "sentiment": sentiment,
            "source": "Finnhub",
        }
    except Exception as e:
        print(f"  [WARN] Finnhub 加密新闻也失败: {e}")
        return {"posts": [], "sentiment": None}


# ─── DefiLlama（ETH TVL，完全免费无 key）───
def fetch_defilama_tvl():
    """获取 ETH 链 TVL 及近期变化"""
    try:
        # 当前 TVL
        url = "https://api.llama.fi/v2/historicalChainTvl/Ethereum"
        r = SESSION.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        if not data or len(data) < 2:
            return None

        latest = data[-1]
        prev_1d = data[-2] if len(data) >= 2 else latest
        prev_7d = data[-8] if len(data) >= 8 else data[0]

        tvl_now = float(latest.get("tvl", 0))
        tvl_1d = float(prev_1d.get("tvl", tvl_now))
        tvl_7d = float(prev_7d.get("tvl", tvl_now))

        chg_1d = (tvl_now - tvl_1d) / tvl_1d if tvl_1d else 0
        chg_7d = (tvl_now - tvl_7d) / tvl_7d if tvl_7d else 0

        return {
            "tvl": tvl_now,
            "tvl_1d_chg": chg_1d,
            "tvl_7d_chg": chg_7d,
        }
    except Exception as e:
        print(f"  [WARN] DefiLlama TVL 失败: {e}")
        return None


# ─── Etherscan（Gas Price + ETH Supply）───
def fetch_etherscan_onchain():
    """获取链上数据：Gas Price + ETH Supply（Etherscan API V2）"""
    if not ETHERSCAN_API_KEY:
        return None
    result = {}
    base_url = "https://api.etherscan.io/v2/api"
    try:
        # Gas Oracle
        params = {
            "chainid": "1",
            "module": "gastracker",
            "action": "gasoracle",
            "apikey": ETHERSCAN_API_KEY,
        }
        r = SESSION.get(base_url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        if data.get("status") == "1" and data.get("result"):
            gas = data["result"]
            result["gas_safe"] = float(gas.get("SafeGasPrice", 0))
            result["gas_propose"] = float(gas.get("ProposeGasPrice", 0))
            result["gas_fast"] = float(gas.get("FastGasPrice", 0))
    except Exception as e:
        print(f"  [WARN] Etherscan Gas 失败: {e}")

    try:
        # ETH Supply + Staking
        params2 = {
            "chainid": "1",
            "module": "stats",
            "action": "ethsupply2",
            "apikey": ETHERSCAN_API_KEY,
        }
        r2 = SESSION.get(base_url, params=params2, timeout=15)
        r2.raise_for_status()
        data2 = r2.json()
        if data2.get("status") == "1" and data2.get("result"):
            res = data2["result"]
            # 单位 wei → ETH
            eth_supply = float(res.get("EthSupply", 0)) / 1e18
            eth2_staking = float(res.get("Eth2Staking", 0)) / 1e18
            burnt = float(res.get("BurntFees", 0)) / 1e18
            result["eth_supply"] = eth_supply
            result["eth2_staking"] = eth2_staking
            result["eth_burnt"] = burnt
            if eth_supply > 0:
                result["staking_ratio"] = eth2_staking / eth_supply
    except Exception as e:
        print(f"  [WARN] Etherscan Supply 失败: {e}")

    return result if result else None


def fetch_macro():
    """获取宏观经济数据（增强版）

    数据源优先级: FRED(主) → yfinance(备)
    - 加密风险代理：BTC 动量、ETH/BTC、稳定币溢价
    - 传统宏观：DXY、VIX、US10Y、US2Y（FRED/yfinance）
    - 经济日历：Finnhub（NFP/CPI 等）
    - 加密新闻情绪：CryptoPanic
    """
    result = {}

    # BTC 作为大盘方向
    ticker_btc = safe_get(f"{BINANCE_BASE}/api/v3/ticker/24hr", {"symbol": "BTCUSDT"})
    if ticker_btc:
        result["btc_change_24h"] = float(ticker_btc.get("priceChangePercent", 0))
        result["btc_price"] = float(ticker_btc.get("lastPrice", 0))

    # ETH/BTC 相对强弱
    ethbtc = safe_get(f"{BINANCE_BASE}/api/v3/ticker/24hr", {"symbol": "ETHBTC"})
    if ethbtc:
        result["ethbtc_change"] = float(ethbtc.get("priceChangePercent", 0))
        result["ethbtc_price"] = float(ethbtc.get("lastPrice", 0))

    # USDC/USDT 溢价
    usdcusdt = safe_get(f"{BINANCE_BASE}/api/v3/ticker/price", {"symbol": "USDCUSDT"})
    if usdcusdt:
        result["usdc_usdt"] = float(usdcusdt.get("price", 1))

    # 传统宏观（FRED 优先 → yfinance 备选）
    # FRED series: DTWEXBGS(DXY宽), DGS10(10Y), DGS2(2Y), VIXCLS(VIX)
    print("  📡 拉取 DXY...")
    dxy_val, dxy_chg, dxy_src = get_macro_indicator("DTWEXBGS", "DX-Y.NYB")
    if dxy_val is not None:
        result["dxy"] = dxy_val
        result["dxy_chg"] = dxy_chg
        result["dxy_src"] = dxy_src

    print("  📡 拉取 VIX...")
    vix_val, vix_chg, vix_src = get_macro_indicator("VIXCLS", "^VIX")
    if vix_val is not None:
        result["vix"] = vix_val
        result["vix_chg"] = vix_chg
        result["vix_src"] = vix_src

    print("  📡 拉取 US10Y...")
    us10y_val, us10y_chg, us10y_src = get_macro_indicator("DGS10", "^TNX")
    if us10y_val is not None:
        result["us10y"] = us10y_val
        result["us10y_chg"] = us10y_chg
        result["us10y_src"] = us10y_src

    print("  📡 拉取 US2Y...")
    us2y_val, us2y_chg, us2y_src = get_macro_indicator("DGS2", "^IRX")
    if us2y_val is not None:
        result["us2y"] = us2y_val
        result["us2y_chg"] = us2y_chg
        result["us2y_src"] = us2y_src

    # 经济日历
    print("  📡 拉取经济日历...")
    result["econ_calendar"] = fetch_econ_calendar()

    # 加密新闻情绪
    print("  📡 拉取加密新闻...")
    result["crypto_news"] = fetch_crypto_news()

    # 链上数据
    print("  📡 拉取链上数据(DefiLlama)...")
    tvl_data = fetch_defilama_tvl()
    if tvl_data:
        result["tvl"] = tvl_data["tvl"]
        result["tvl_1d_chg"] = tvl_data["tvl_1d_chg"]
        result["tvl_7d_chg"] = tvl_data["tvl_7d_chg"]

    print("  📡 拉取链上数据(Etherscan)...")
    onchain = fetch_etherscan_onchain()
    if onchain:
        result.update(onchain)

    return result


def score_macro(macro):
    """
    宏观经济评分 (满分 ±25)
    - 加密大盘方向(BTC):   ±6
    - ETH/BTC 相对强弱:    ±5
    - 稳定币/资金流:       ±3
    - 美元/风险因子(DXY/VIX/10Y/2Y): ±6
    - 经济日历风险:        ±2
    - 加密新闻情绪:        ±3
    """
    if not macro:
        return 0, {}

    details = {}
    score = 0

    # BTC 作为大盘方向
    btc_chg = macro.get("btc_change_24h", 0)
    if btc_chg > 5:
        s = 5
    elif btc_chg > 2:
        s = 3
    elif btc_chg > 0:
        s = 1
    elif btc_chg > -2:
        s = -1
    elif btc_chg > -5:
        s = -3
    else:
        s = -5
    score += s
    details["BTC动量"] = f"{btc_chg:+.2f}% (${macro.get('btc_price', 0):,.0f}) → {s:+d}"

    # ETH/BTC 相对强弱
    ethbtc = macro.get("ethbtc_change", 0)
    if ethbtc > 3:
        s = 4
    elif ethbtc > 1:
        s = 2
    elif ethbtc > -1:
        s = 0
    elif ethbtc > -3:
        s = -2
    else:
        s = -4
    score += s
    details["ETH/BTC"] = f"{ethbtc:+.2f}% ({macro.get('ethbtc_price', 0):.5f}) → {s:+d}"

    # USDC/USDT 溢价
    usdc_usdt = macro.get("usdc_usdt", 1.0)
    if usdc_usdt > 1.002:
        s = -2
    elif usdc_usdt > 1.0005:
        s = -1
    elif usdc_usdt < 0.998:
        s = 2
    elif usdc_usdt < 0.9995:
        s = 1
    else:
        s = 0
    score += s
    details["USDC/USDT"] = f"{usdc_usdt:.4f} → {s:+d}"

    # ─── 传统宏观：DXY / VIX / US10Y / US2Y ───
    dxy_chg = macro.get("dxy_chg", None)
    vix_val = macro.get("vix", None)
    vix_chg = macro.get("vix_chg", None)
    us10y_chg = macro.get("us10y_chg", None)
    us2y_chg = macro.get("us2y_chg", None)

    risk_score = 0

    # DXY
    if dxy_chg is not None:
        if dxy_chg > 0.005:
            risk_score -= 2
        elif dxy_chg > 0.002:
            risk_score -= 1
        elif dxy_chg < -0.005:
            risk_score += 2
        elif dxy_chg < -0.002:
            risk_score += 1
        src = macro.get("dxy_src", "")
        details["DXY"] = f"{macro.get('dxy',0):.2f} ({dxy_chg:+.2%}) [{src}]"
    else:
        details["DXY"] = "N/A"

    # VIX（绝对值 + 变化率）
    if vix_val is not None:
        if vix_val > 30:
            risk_score -= 2
        elif vix_val > 20:
            risk_score -= 1
        elif vix_val < 15:
            risk_score += 1
        if vix_chg is not None and vix_chg > 0.10:
            risk_score -= 1  # VIX 暴涨额外扣分
        src = macro.get("vix_src", "")
        chg_str = f" ({vix_chg:+.2%})" if vix_chg is not None else ""
        details["VIX"] = f"{vix_val:.2f}{chg_str} [{src}]"
    else:
        details["VIX"] = "N/A"

    # US10Y
    if us10y_chg is not None:
        if us10y_chg > 0.02:
            risk_score -= 1
        elif us10y_chg < -0.02:
            risk_score += 1
        src = macro.get("us10y_src", "")
        details["US10Y"] = f"{macro.get('us10y',0):.2f}% ({us10y_chg:+.2%}) [{src}]"
    else:
        details["US10Y"] = "N/A"

    # US2Y
    if us2y_chg is not None:
        if us2y_chg > 0.02:
            risk_score -= 1
        elif us2y_chg < -0.02:
            risk_score += 1
        src = macro.get("us2y_src", "")
        details["US2Y"] = f"{macro.get('us2y',0):.2f}% ({us2y_chg:+.2%}) [{src}]"
    else:
        details["US2Y"] = "N/A"

    # 期限利差（10Y-2Y）：倒挂额外警示
    if macro.get("us10y") is not None and macro.get("us2y") is not None:
        spread = macro["us10y"] - macro["us2y"]
        if spread < 0:
            details["收益率曲线"] = f"10Y-2Y={spread:+.2f}% ⚠️ 倒挂(衰退信号)"
        else:
            details["收益率曲线"] = f"10Y-2Y={spread:+.2f}%"

    risk_score = clamp(risk_score, -6, 6)
    score += risk_score
    details["美元/风险因子"] = f"{risk_score:+d}"

    # ─── 经济日历（Finnhub news 关键词匹配）───
    cal = macro.get("econ_calendar", [])
    cal_score = 0
    if cal:
        events_str = "; ".join([e.get("event", "")[:50] for e in cal[:3]])
        cal_score = -1  # 有经济数据相关新闻 → 微偏空（不确定性）
        details["经济日历(7d)"] = f"⚠️ 相关: {events_str} → {cal_score:+d}"
    else:
        details["经济日历(7d)"] = "无重大经济数据新闻"

    score += cal_score

    # ─── 加密新闻情绪（CryptoPanic）───
    news = macro.get("crypto_news", {})
    news_score = 0
    news_sentiment = news.get("sentiment")
    news_total = news.get("total", 0)

    if news_sentiment and news_total > 0:
        bull = news.get("bullish", 0)
        bear = news.get("bearish", 0)
        if news_sentiment == "bullish":
            news_score = 2
        elif news_sentiment == "bearish":
            news_score = -2
        else:
            news_score = 0

        # 提取最新3条标题
        titles = [p.get("title", "")[:60] for p in news.get("posts", [])[:3]]
        titles_str = " | ".join(titles)
        news_src = news.get("source", "")
        details["加密新闻情绪"] = f"{news_sentiment} (多{bull}/空{bear}/共{news_total}) [{news_src}] → {news_score:+d}"
        details["近期新闻"] = titles_str if titles_str else "无"
    else:
        details["加密新闻情绪"] = "N/A"
        details["近期新闻"] = "N/A"

    score += news_score

    # ─── 链上数据（DefiLlama TVL + Etherscan Gas）───
    onchain_score = 0

    # TVL 变化
    tvl = macro.get("tvl")
    tvl_1d = macro.get("tvl_1d_chg")
    tvl_7d = macro.get("tvl_7d_chg")
    if tvl is not None and tvl_1d is not None:
        tvl_b = tvl / 1e9  # 转十亿
        if tvl_7d is not None and tvl_7d < -0.05:
            onchain_score -= 1
            lab = "7d 资金外流"
        elif tvl_7d is not None and tvl_7d > 0.05:
            onchain_score += 1
            lab = "7d 资金流入"
        elif tvl_1d < -0.02:
            onchain_score -= 1
            lab = "1d 资金外流"
        elif tvl_1d > 0.02:
            onchain_score += 1
            lab = "1d 资金流入"
        else:
            lab = "平稳"
        details["ETH TVL(DefiLlama)"] = f"${tvl_b:.1f}B (1d:{tvl_1d:+.2%} 7d:{tvl_7d:+.2%}) {lab} → {onchain_score:+d}"
    else:
        details["ETH TVL(DefiLlama)"] = "N/A"

    # Gas Price（当前 ETH 主网 gas 通常 0.x ~ 几十 Gwei）
    gas_fast = macro.get("gas_fast")
    gas_propose = macro.get("gas_propose")
    if gas_fast is not None:
        gas_s = 0
        if gas_fast > 50:
            gas_s = -1  # 极端拥堵，可能恐慌清算
            gas_lab = "极端拥堵(可能恐慌)"
        elif gas_fast > 10:
            gas_s = 1   # 活跃
            gas_lab = "链上活跃"
        elif gas_fast < 0.5:
            gas_s = -1  # 极低活跃度
            gas_lab = "链上冷清"
        else:
            gas_lab = "正常"
        onchain_score += gas_s
        safe = macro.get('gas_safe', 0)
        details["Gas Price(Etherscan)"] = f"Safe={safe:.2f} Propose={gas_propose:.2f} Fast={gas_fast:.2f} Gwei | {gas_lab} → {gas_s:+d}"
    else:
        details["Gas Price(Etherscan)"] = "N/A"

    # Staking ratio（参考，不计分）
    staking_ratio = macro.get("staking_ratio")
    eth2_staking = macro.get("eth2_staking")
    if staking_ratio is not None and eth2_staking is not None:
        details["ETH质押率"] = f"{staking_ratio:.1%} ({eth2_staking/1e6:.2f}M ETH)"

    onchain_score = clamp(onchain_score, -2, 2)
    score += onchain_score
    details["链上因子"] = f"{onchain_score:+d}"

    score = clamp(score, -25, 25)
    details["宏观总分"] = f"{score:+d}/±25"
    return score, details


# ═══════════════════════════════════════════════════════════════
#  综合评分 + 阶段判断
# ═══════════════════════════════════════════════════════════════

PHASES = [
    (+70, +100, "🔴 极度过热", "分批止盈, 卖 call, 保护性 put"),
    (+30, +70,  "🟠 偏多趋势", "持有, 回调加仓, 做多 delta"),
    (-30, +30,  "🟡 震荡中性", "区间高抛低吸, 卖 straddle"),
    (-70, -30,  "🟢 偏空趋势", "减仓/对冲, 买 put, 轻仓做空"),
    (-100, -70, "🔵 极度恐慌", "左侧抄底, 卖 put, 分批建仓"),
]


def determine_phase(total_score):
    for lo, hi, name, strategy in PHASES:
        if lo <= total_score <= hi:
            return name, strategy
    return "未知", "观望"


def run_analysis(timeframe="4h"):
    """执行完整分析"""
    ts = dt.datetime.utcnow()
    print(f"\n{'='*60}")
    print(f"  ETH 阶段仪 [{timeframe}] - {ts.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}")

    # 衍生品 OI 历史周期映射
    oi_periods = {"1h": 12, "4h": 48, "1d": 288}  # 5min 粒度
    deriv_period = {"1h": "1h", "4h": "4h", "1d": "1d"}

    # 收集数据
    print(f"\n📊 [{timeframe}] [1/4] 获取技术面数据...")
    klines = fetch_binance_klines(interval=timeframe, limit=200)
    tech_score, tech_details = score_technical(klines)

    print(f"📊 [{timeframe}] [2/4] 获取衍生品数据...")
    deriv_data = fetch_binance_derivatives(
        oi_limit=oi_periods.get(timeframe, 48),
        ratio_period=deriv_period.get(timeframe, "4h"))
    deriv_score, deriv_details = score_derivatives(deriv_data)

    print(f"📊 [{timeframe}] [3/4] 获取期权数据...")
    options_data = fetch_deribit_options()
    opt_score, opt_details = score_options(options_data)

    print(f"📊 [{timeframe}] [4/4] 获取情绪数据...")
    sentiment_data = fetch_sentiment()
    sent_score, sent_details = score_sentiment(sentiment_data)

    print(f"📊 [{timeframe}] [5/5] 获取宏观+日历+新闻...")
    macro_data = fetch_macro()
    macro_score, macro_details = score_macro(macro_data)

    # 加权总分
    # 技术(25) + 衍生品(10) = 第一维度 35
    dim1_score = tech_score + deriv_score  # ±35
    # 期权 = 第二维度 25
    dim2_score = opt_score  # ±25
    # 情绪 = 第三维度 15
    dim3_score = sent_score  # ±15
    # 宏观 = 第四维度 25
    dim4_score = macro_score  # ±25

    total = dim1_score + dim2_score + dim3_score + dim4_score  # ±100
    total = clamp(total, -100, 100)

    phase_name, strategy = determine_phase(total)

    print(f"\n{'─'*60}")
    print(f"  [{timeframe}] 技术面 + 衍生品: {dim1_score:+d}/±35")
    print(f"  [{timeframe}] 期权结构:        {dim2_score:+d}/±25")
    print(f"  [{timeframe}] 社交情绪:        {dim3_score:+d}/±15")
    print(f"  [{timeframe}] 宏观经济:        {dim4_score:+d}/±25")
    print(f"{'─'*60}")
    print(f"  ★ [{timeframe}] 总分: {total:+d}/±100")
    print(f"  ★ [{timeframe}] 阶段: {phase_name}")
    print(f"  ★ [{timeframe}] 策略: {strategy}")
    print(f"{'─'*60}")

    # 组装结果
    result = {
        "timeframe": timeframe,
        "timestamp": ts.strftime("%Y-%m-%d %H:%M UTC"),
        "price": tech_details.get("price", 0),
        "dimensions": {
            "技术面+衍生品": {
                "score": dim1_score, "max": 35,
                "技术面": tech_details,
                "衍生品": deriv_details
            },
            "期权结构": {"score": dim2_score, "max": 25, **opt_details},
            "社交情绪": {"score": dim3_score, "max": 15, **sent_details},
            "宏观经济": {"score": dim4_score, "max": 25, **macro_details},
        },
        "total_score": total,
        "phase": phase_name,
        "strategy": strategy,
    }

    return result


# ═══════════════════════════════════════════════════════════════
#  Excel 输出
# ═══════════════════════════════════════════════════════════════

# 样式
HEADER_FILL = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
TITLE_FONT = Font(bold=True, size=14, color="1F4E79")
SCORE_FONT = Font(bold=True, size=12)
THIN_BORDER = Border(
    left=Side(style="thin"), right=Side(style="thin"),
    top=Side(style="thin"), bottom=Side(style="thin")
)

PHASE_COLORS = {
    "🔴": "FF4444",
    "🟠": "FF8C00",
    "🟡": "FFD700",
    "🟢": "32CD32",
    "🔵": "4169E1",
}


def get_phase_color(phase_name):
    for emoji, color in PHASE_COLORS.items():
        if emoji in phase_name:
            return color
    return "808080"


def generate_excel(result, filepath=None):
    """生成格式化 Excel 报告"""
    tf = result.get("timeframe", "4h")
    if filepath is None:
        ts_str = dt.datetime.utcnow().strftime("%Y%m%d_%H%M")
        filepath = OUTPUT_DIR / f"ETH_Phase_{tf}_{ts_str}.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = f"ETH阶段仪_{tf}"

    # 列宽
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 50
    ws.column_dimensions["C"].width = 15
    ws.column_dimensions["D"].width = 15

    row = 1

    # ── 标题 ──
    ws.merge_cells("A1:D1")
    c = ws.cell(row=1, column=1, value=f"ETH 阶段仪 [{tf}]  |  {result['timestamp']}")
    c.font = TITLE_FONT
    c.alignment = Alignment(horizontal="center")
    row = 3

    # ── 总览 ──
    ws.merge_cells(f"A{row}:D{row}")
    c = ws.cell(row=row, column=1, value="综合总览")
    c.font = Font(bold=True, size=12, color="FFFFFF")
    c.fill = PatternFill(start_color="2C3E50", fill_type="solid")
    c.alignment = Alignment(horizontal="center")
    row += 1

    overview = [
        ("当前价格", f"${result['price']:,.2f}"),
        ("总分", f"{result['total_score']:+d} / ±100"),
        ("当前阶段", result["phase"]),
        ("建议策略", result["strategy"]),
    ]
    if result.get("filter_note"):
        overview.insert(2, ("过滤", result["filter_note"]))
    for label, val in overview:
        ws.cell(row=row, column=1, value=label).font = Font(bold=True)
        c = ws.cell(row=row, column=2, value=val)
        if label == "总分":
            c.font = Font(bold=True, size=13, color=get_phase_color(result["phase"]))
        elif label == "当前阶段":
            c.font = Font(bold=True, size=12, color=get_phase_color(result["phase"]))
            c.fill = PatternFill(start_color=get_phase_color(result["phase"]) + "33",
                                 fill_type="solid")
        row += 1

    row += 1

    # ── 分数条 ──
    ws.merge_cells(f"A{row}:D{row}")
    c = ws.cell(row=row, column=1, value="各维度得分")
    c.font = Font(bold=True, size=12, color="FFFFFF")
    c.fill = PatternFill(start_color="2C3E50", fill_type="solid")
    c.alignment = Alignment(horizontal="center")
    row += 1

    for hdr in ["维度", "得分", "满分", "占比"]:
        idx = ["维度", "得分", "满分", "占比"].index(hdr) + 1
        c = ws.cell(row=row, column=idx, value=hdr)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
        c.border = THIN_BORDER
    row += 1

    dims = result["dimensions"]
    for name, info in dims.items():
        sc = info["score"]
        mx = info["max"]
        pct = sc / mx * 100 if mx else 0
        ws.cell(row=row, column=1, value=name).border = THIN_BORDER
        c = ws.cell(row=row, column=2, value=f"{sc:+d}")
        c.font = Font(bold=True, color="228B22" if sc > 0 else ("CC0000" if sc < 0 else "808080"))
        c.border = THIN_BORDER
        ws.cell(row=row, column=3, value=f"±{mx}").border = THIN_BORDER
        ws.cell(row=row, column=4, value=f"{pct:+.0f}%").border = THIN_BORDER
        row += 1

    row += 1

    # ── 详细指标 ──
    for dim_name, dim_info in dims.items():
        ws.merge_cells(f"A{row}:D{row}")
        c = ws.cell(row=row, column=1, value=dim_name)
        c.font = Font(bold=True, size=11, color="FFFFFF")
        c.fill = PatternFill(start_color="34495E", fill_type="solid")
        row += 1

        for key, val in dim_info.items():
            if key in ("score", "max"):
                continue
            if isinstance(val, dict):
                # 嵌套子维度
                ws.cell(row=row, column=1, value=f"  ── {key} ──").font = Font(bold=True, italic=True)
                row += 1
                for k2, v2 in val.items():
                    ws.cell(row=row, column=1, value=f"    {k2}").border = THIN_BORDER
                    ws.cell(row=row, column=2, value=str(v2)).border = THIN_BORDER
                    row += 1
            else:
                ws.cell(row=row, column=1, value=key).border = THIN_BORDER
                ws.cell(row=row, column=2, value=str(val)).border = THIN_BORDER
                row += 1

        row += 1

    # ── 阶段对照表 ──
    ws.merge_cells(f"A{row}:D{row}")
    c = ws.cell(row=row, column=1, value="阶段对照表")
    c.font = Font(bold=True, size=12, color="FFFFFF")
    c.fill = PatternFill(start_color="2C3E50", fill_type="solid")
    c.alignment = Alignment(horizontal="center")
    row += 1

    for hdr in ["分数区间", "阶段", "交易策略", ""]:
        idx = ["分数区间", "阶段", "交易策略", ""].index(hdr) + 1
        c = ws.cell(row=row, column=idx, value=hdr)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
    row += 1

    for lo, hi, name, strat in PHASES:
        ws.cell(row=row, column=1, value=f"[{lo:+d}, {hi:+d}]").border = THIN_BORDER
        c = ws.cell(row=row, column=2, value=name)
        c.border = THIN_BORDER
        c.fill = PatternFill(start_color=get_phase_color(name), fill_type="solid")
        c.font = Font(bold=True, color="FFFFFF")
        ws.cell(row=row, column=3, value=strat).border = THIN_BORDER
        # 标记当前阶段
        if name == result["phase"]:
            ws.cell(row=row, column=4, value="◄ 当前").font = Font(bold=True, color="FF0000")
        row += 1

    wb.save(filepath)
    print(f"\n📁 报告已保存: {filepath}")
    return str(filepath)


# ═══════════════════════════════════════════════════════════════
#  历史记录追加 (同一天追加到同一个文件)
# ═══════════════════════════════════════════════════════════════


def append_to_daily_excel(result):
    """追加到当日汇总文件"""
    tf = result.get("timeframe", "4h")
    today = dt.datetime.utcnow().strftime("%Y%m%d")
    daily_file = OUTPUT_DIR / f"ETH_Phase_Daily_{tf}_{today}.xlsx"

    # 扁平化一行数据
    row_data = {
        "时间": result["timestamp"],
        "价格": result["price"],
        "总分": result["total_score"],
        "阶段": result["phase"],
        "策略": result["strategy"],
        "技术+衍生品": result["dimensions"]["技术面+衍生品"]["score"],
        "期权": result["dimensions"]["期权结构"]["score"],
        "情绪": result["dimensions"]["社交情绪"]["score"],
        "宏观": result["dimensions"]["宏观经济"]["score"],
    }

    if daily_file.exists():
        df = pd.read_excel(daily_file, sheet_name="汇总")
        df = pd.concat([df, pd.DataFrame([row_data])], ignore_index=True)
    else:
        df = pd.DataFrame([row_data])

    with pd.ExcelWriter(str(daily_file), engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="汇总", index=False)

    # E: 在日报里加入简单走势图（总分 + 维度分）
    try:
        from openpyxl import load_workbook
        from openpyxl.chart import LineChart, Reference

        wb = load_workbook(daily_file)
        ws = wb["汇总"]

        # 删除旧图表（避免叠加）
        ws._charts = []

        n_rows = ws.max_row
        if n_rows >= 3:
            chart = LineChart()
            chart.title = f"ETH阶段仪 {tf} - 分数走势"
            chart.y_axis.title = "Score"
            chart.x_axis.title = "Time"

            # 数据列：总分(3)、技术+衍生品(6)、期权(7)、情绪(8)、宏观(9)
            data = Reference(ws, min_col=3, max_col=9, min_row=1, max_row=n_rows)
            chart.add_data(data, titles_from_data=True)
            cats = Reference(ws, min_col=1, min_row=2, max_row=n_rows)
            chart.set_categories(cats)
            chart.height = 12
            chart.width = 28
            ws.add_chart(chart, "K2")

        wb.save(daily_file)
    except Exception as e:
        print(f"  [WARN] 日报图表生成失败: {e}")

    print(f"📁 追加到日报: {daily_file}")
    return str(daily_file)


# ═══════════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════════


def format_tg_summary(result):
    """生成 Telegram 文字摘要"""
    tf = result.get("timeframe", "4h")
    dims = result["dimensions"]

    filter_note = result.get("filter_note")

    lines = [
        f"📊 <b>ETH 阶段仪 [{tf}]</b>  |  {result['timestamp']}",
        *( [f"⚠️ <b>过滤:</b> {filter_note}"] if filter_note else [] ),
        f"━━━━━━━━━━━━━━━━━━━━",
        f"💰 价格: <b>${result['price']:,.2f}</b>",
        f"",
        f"<b>各维度得分:</b>",
        f"  📈 技术+衍生品:  <b>{dims['技术面+衍生品']['score']:+d}</b> /±35",
        f"  🎯 期权结构:     <b>{dims['期权结构']['score']:+d}</b> /±25",
        f"  💬 社交情绪:     <b>{dims['社交情绪']['score']:+d}</b> /±15",
        f"  🌍 宏观经济:     <b>{dims['宏观经济']['score']:+d}</b> /±25",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"⭐ 总分: <b>{result['total_score']:+d}</b> /±100",
        f"⭐ 阶段: <b>{result['phase']}</b>",
        f"⭐ 策略: {result['strategy']}",
    ]

    # 关键指标速览
    tech = dims["技术面+衍生品"].get("技术面", {})
    deriv = dims["技术面+衍生品"].get("衍生品", {})
    lines += [
        f"",
        f"<b>关键指标:</b>",
    ]
    for key in ["MA排列", "MACD", "RSI", "KDJ"]:
        if key in tech:
            lines.append(f"  {key}: {tech[key]}")
    for key in ["资金费率分位", "资金费率(无分位)", "OI变化(窗口)", "OI×价格象限", "短线策略提示(OI×价格)"]:
        if key in deriv:
            lines.append(f"  {key}: {deriv[key]}")

    # 情绪
    if "恐贪指数" in dims["社交情绪"]:
        lines.append(f"  恐贪指数: {dims['社交情绪']['恐贪指数']}")

    # 宏观关键指标
    macro_d = dims.get("宏观经济", {})
    for key in ["DXY", "VIX", "US10Y", "US2Y", "收益率曲线", "经济日历(7d)", "加密新闻情绪", "ETH TVL(DefiLlama)", "Gas Price(Etherscan)", "ETH质押率"]:
        if key in macro_d and macro_d[key] != "N/A":
            lines.append(f"  {key}: {macro_d[key]}")

    return "\n".join(lines)


def send_tg_message(text):
    """发送文字消息到 Telegram"""
    if not TG_API or not TG_CHAT_ID:
        return
    try:
        requests.post(f"{TG_API}/sendMessage", json={
            "chat_id": TG_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
        }, timeout=15)
    except Exception as e:
        print(f"  [WARN] TG 消息发送失败: {e}")


def send_tg_file(filepath, caption=""):
    """发送文件到 Telegram"""
    if not TG_API or not TG_CHAT_ID:
        return
    try:
        with open(filepath, "rb") as f:
            requests.post(f"{TG_API}/sendDocument", data={
                "chat_id": TG_CHAT_ID,
                "caption": caption[:1024],
            }, files={"document": (Path(filepath).name, f)}, timeout=30)
    except Exception as e:
        print(f"  [WARN] TG 文件发送失败: {e}")


def run_single(timeframe="4h", send=True):
    """运行单个周期的分析; send=True 时发送 TG + 文件"""
    try:
        result = run_analysis(timeframe=timeframe)
        detail_path = generate_excel(result)
        append_to_daily_excel(result)

        # 发送到 Telegram
        if send and TG_BOT_TOKEN and TG_CHAT_ID:
            summary = format_tg_summary(result)
            send_tg_message(summary)
            send_tg_file(detail_path,
                         caption=f"ETH阶段仪 [{timeframe}] 详细报告 | {result['timestamp']}")
            print(f"📨 [{timeframe}] 已发送到 Telegram")

        # 把路径带回去，方便主流程做过滤后再补发
        result["_detail_path"] = detail_path
        return result
    except Exception as e:
        print(f"❌ [{timeframe}] 运行失败: {e}")
        traceback.print_exc()
        if send and TG_BOT_TOKEN and TG_CHAT_ID:
            send_tg_message(f"❌ ETH阶段仪 [{timeframe}] 运行失败: {e}")
        return None


def compute_resonance(results: dict):
    """A3: 1h 与 4h 多周期共振/背离 + 过滤逻辑基础"""
    r4 = results.get("4h")
    r1 = results.get("1h")
    if not r4 or not r1:
        return None

    def dir_tag(score):
        if score >= 15:
            return "多"
        if score <= -15:
            return "空"
        return "震"

    d1_4 = r4["dimensions"]["技术面+衍生品"]["score"]
    d1_1 = r1["dimensions"]["技术面+衍生品"]["score"]

    tag4 = dir_tag(d1_4)
    tag1 = dir_tag(d1_1)

    if tag4 == tag1 and tag4 != "震":
        resonance = "✅ 共振"
        note = "同向趋势，短线信号可信度更高"
    elif tag4 != "震" and tag1 != "震" and tag4 != tag1:
        resonance = "⚠️ 背离"
        note = "1h 与 4h 相反，短线需快进快出/减仓"
    elif tag4 == "震" and tag1 != "震":
        resonance = "🟡 1h主导"
        note = "4h 震荡、1h 出方向，适合短线"
    elif tag4 != "震" and tag1 == "震":
        resonance = "🟠 4h过滤"
        note = "4h 有方向但 1h 震荡，等 1h 回踩/突破确认"
    else:
        resonance = "🟡 双周期震荡"
        note = "区间策略优先"

    return {
        "resonance": resonance,
        "note": note,
        "d1_4h": d1_4,
        "d1_1h": d1_1,
        "tag4": tag4,
        "tag1": tag1,
    }


def apply_1h_filter_by_4h(results: dict, enabled=True):
    """A3-过滤开关：若 4h 与 1h 方向相反，则标记 1h 信号为不执行。"""
    if not enabled:
        return results
    r4 = results.get("4h")
    r1 = results.get("1h")
    if not r4 or not r1:
        return results

    res = compute_resonance(results)
    if not res:
        return results

    # 只有当 4h 有明确方向(非震荡) 且与 1h 相反时过滤
    if res["tag4"] != "震" and res["tag1"] != "震" and res["tag4"] != res["tag1"]:
        r1["filtered_by_4h"] = True
        r1["filter_note"] = f"1h({res['tag1']}) 与 4h({res['tag4']}) 反向：1h 信号不执行，按 4h 为准/轻仓快进快出"
        # 不改分数，但把策略/阶段提示改成执行层面的提醒
        r1["phase"] = f"⚠️ 1h被4h过滤 ({r1['phase']})"
        r1["strategy"] = "执行层：忽略 1h 方向单，等 1h 与 4h 同向再加仓；或只做极短线(快进快出)"

    return results


def main():
    """单次运行: 4h + 1h 双周期（含 4h 过滤 1h 开关）"""
    # 先跑但先不发送（因为 1h 需要看 4h 才能决定是否过滤）
    results = {
        "4h": run_single("4h", send=False),
        "1h": run_single("1h", send=False),
    }

    # A3: 过滤开关（默认开启，短线更稳）
    filter_enabled = os.environ.get("ETH_FILTER_1H_BY_4H", "1").strip() not in ("0", "false", "False")
    results = apply_1h_filter_by_4h(results, enabled=filter_enabled)

    # 发送（4h 先发，再发 1h）
    for tf in ["4h", "1h"]:
        r = results.get(tf)
        if not r:
            continue
        if TG_BOT_TOKEN and TG_CHAT_ID:
            summary = format_tg_summary(r)
            send_tg_message(summary)
            if r.get("_detail_path"):
                send_tg_file(r["_detail_path"], caption=f"ETH阶段仪 [{tf}] 详细报告 | {r['timestamp']}")
            print(f"📨 [{tf}] 已发送到 Telegram")

    # 打印/推送共振结论（短线偏好）
    res = compute_resonance(results)
    if res:
        msg = (
            f"🧩 多周期共振(短线): {res['resonance']}\n"
            f"- 技术+衍生品: 1h={res['d1_1h']:+d} | 4h={res['d1_4h']:+d}\n"
            f"- 结论: {res['note']}\n"
            f"- 过滤开关: {'ON' if filter_enabled else 'OFF'}"
        )
        print(msg)
        if TG_BOT_TOKEN and TG_CHAT_ID:
            send_tg_message(msg)

    return results


def run_scheduler(interval_hours=4):
    """定时循环"""
    print(f"🚀 ETH 阶段仪启动, 每 {interval_hours} 小时运行一次")
    print(f"📂 报告目录: {OUTPUT_DIR}")
    while True:
        main()
        next_run = dt.datetime.utcnow() + dt.timedelta(hours=interval_hours)
        print(f"\n⏰ 下次运行: {next_run.strftime('%Y-%m-%d %H:%M UTC')}")
        time.sleep(interval_hours * 3600)


if __name__ == "__main__":
    import sys
    if "--daemon" in sys.argv:
        interval = 4
        for arg in sys.argv:
            if arg.startswith("--interval="):
                interval = int(arg.split("=")[1])
        run_scheduler(interval)
    else:
        results = main()
        for tf, r in results.items():
            if r:
                print(f"\n✅ [{tf}] 完成! 总分: {r['total_score']:+d} | {r['phase']}")
