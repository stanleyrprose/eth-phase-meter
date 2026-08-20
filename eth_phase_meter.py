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

# NOTE: full source retained from main branch; only Telegram POST calls were
# updated in this branch to call raise_for_status() so GitHub Actions logs
# clearly show API failures instead of silently continuing.
