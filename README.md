# 🔬 ETH Phase Meter（ETH阶段仪）

> 多维度 ETH 市场分析工具 —— 每4小时自动评分，输出 Excel 报告 + Telegram 推送

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

---

## 📖 简介

ETH阶段仪是一个面向**短线交易者**的自动化分析工具。它每4小时从多个数据源收集数据，通过 **四大维度** 打分，判断当前 ETH 所处的市场阶段，并给出策略建议。

### 核心特性

- 🔄 **双周期分析**：同时运行 4h（趋势过滤）+ 1h（短线信号）
- 📊 **四维度评分**：技术面、期权结构、市场情绪、宏观经济
- 🧩 **多周期共振**：1h 信号与 4h 方向不同时自动过滤
- 📈 **Excel 报告**：详细指标 + 日报汇总 + 走势图表
- 📱 **Telegram 推送**：实时发送评分摘要 + Excel 文件

---

## 🏗 架构

```
┌─────────────────────────────────────────────────┐
│               ETH Phase Meter                    │
├──────────┬──────────┬──────────┬─────────────────┤
│ 技术面   │ 期权结构 │ 社交情绪 │ 宏观经济        │
│ +衍生品  │          │          │                 │
│ (±35)    │ (±25)    │ (±15)    │ (±25)           │
├──────────┼──────────┼──────────┼─────────────────┤
│ Binance  │ Deribit  │ Alt.me   │ FRED            │
│ 现货+合约│ 期权API  │ FNG指数  │ Finnhub         │
│          │          │ Binance  │ CryptoPanic     │
│          │          │          │ DefiLlama       │
│          │          │          │ Etherscan       │
│          │          │          │ yfinance(备选)  │
└──────────┴──────────┴──────────┴─────────────────┘
                      │
              总分: -100 ~ +100
                      │
         ┌────────────┼────────────┐
         ▼            ▼            ▼
    Excel 报告   Telegram 推送  日报汇总+图表
```

---

## 📊 评分体系

### 维度一：技术面 + 衍生品（±35 分）

| 指标 | 分值 | 说明 |
|------|------|------|
| MA 排列（EMA7/25/99） | ±5 | 多头/空头/交叉排列 |
| MACD | ±5 | 金叉/死叉 + 柱状趋势 |
| RSI(14) | ±5 | 超买/超卖（逆向指标） |
| KDJ | ±5 | 超买/超卖 + 金叉/死叉 |
| 结构关键位 + 趋势强度 | ±5 | 多窗口突破 + ADX + 斜率 |
| OI×价格四象限 | ±5 | 增仓/回补/增空/去杠杆 |
| 资金费率分位 | ±2 | 30天历史分位数 |
| CVD（买卖力量） | ±3 | 买方/卖方加速/减速 |

### 维度二：期权结构（±25 分）

| 指标 | 分值 | 说明 |
|------|------|------|
| ATM IV（近月/次月） | ±5 | 隐含波动率水平 |
| IV 期限结构 | — | Backwardation / Contango / 平坦 |
| Put/Call OI Ratio | ±5 | 多空保护需求 |
| Put/Call Volume Ratio | ±3 | 当日交易方向 |
| 25Δ IV偏度 (proxy) | ±2 | OTM Put vs Call IV |
| OI 集中度 | — | 近月 Top3 行权价（pin/max-pain 参考） |

### 维度三：社交情绪（±15 分）

| 指标 | 分值 | 说明 |
|------|------|------|
| Fear & Greed 指数 | ±7 | 极端情绪作反指 |
| 情绪趋势 | ±4 | 当前 vs 前值 vs 7日均值 |
| 24h 价格动量 | ±4 | 涨跌幅辅助 |

### 维度四：宏观经济（±25 分）

| 指标 | 分值 | 数据源 |
|------|------|--------|
| BTC 动量 | ±5 | Binance |
| ETH/BTC 强弱 | ±4 | Binance |
| USDC/USDT 溢价 | ±2 | Binance |
| DXY / VIX / US10Y / US2Y | ±6 | FRED → yfinance |
| 经济日历新闻 | ±1 | Finnhub |
| 加密新闻情绪 | ±2 | CryptoPanic → Finnhub |
| 链上因子（TVL + Gas） | ±2 | DefiLlama + Etherscan |

### 阶段划分

| 总分范围 | 阶段 | 建议策略 |
|----------|------|----------|
| +70 ~ +100 | 🔴 极度过热 | 分批止盈，卖 call |
| +30 ~ +70 | 🟠 偏多趋势 | 持有，回调加仓 |
| -30 ~ +30 | 🟡 震荡中性 | 区间高抛低吸，卖 straddle |
| -70 ~ -30 | 🟢 偏空趋势 | 减仓/对冲，买 put |
| -100 ~ -70 | 🔵 极度恐慌 | 左侧抄底，卖 put |

---

## 🚀 快速部署

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp env.example /etc/eth-phase-meter.env
# 编辑填入你的 API keys
nano /etc/eth-phase-meter.env
```

需要的 API Keys（全部免费注册）：

| Key | 用途 | 注册链接 |
|-----|------|----------|
| `TG_BOT_TOKEN` | Telegram 推送 | [@BotFather](https://t.me/BotFather) |
| `TG_CHAT_ID` | 接收消息的 Chat ID | [@userinfobot](https://t.me/userinfobot) |
| `FRED_API_KEY` | 宏观数据 | [FRED](https://fred.stlouisfed.org/docs/api/api_key.html) |
| `FINNHUB_API_KEY` | 新闻 | [Finnhub](https://finnhub.io/register) |
| `CRYPTOPANIC_API_KEY` | 加密新闻（可选） | [CryptoPanic](https://cryptopanic.com/developers/api/) |
| `ETHERSCAN_API_KEY` | 链上数据 | [Etherscan](https://etherscan.io/myapikey) |

### 3. 单次测试运行

```bash
source /etc/eth-phase-meter.env
export TG_BOT_TOKEN TG_CHAT_ID FRED_API_KEY FINNHUB_API_KEY CRYPTOPANIC_API_KEY ETHERSCAN_API_KEY
python3 eth_phase_meter.py
```

### 4. systemd 服务化（推荐）

```bash
cp eth-phase-meter.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now eth-phase-meter.service

# 查看状态
systemctl status eth-phase-meter.service

# 查看日志
journalctl -u eth-phase-meter.service -f
```

---

## 📁 项目结构

```
eth-phase-meter/
├── eth_phase_meter.py          # 核心脚本（~2100+ 行）
├── eth-phase-meter.service     # systemd 服务配置
├── env.example                 # 环境变量模板（不含密钥）
├── requirements.txt            # Python 依赖
├── README.md                   # 本文档
├── CHANGELOG.md                # 变更日志
├── LICENSE                     # MIT 许可证
└── .gitignore                  # Git 忽略规则
```

运行后自动生成：
```
eth_reports/                    # Excel 报告输出目录
├── ETH_Phase_4h_YYYYMMDD_HHMM.xlsx   # 4h 详细报告
├── ETH_Phase_1h_YYYYMMDD_HHMM.xlsx   # 1h 详细报告
├── ETH_Phase_Daily_4h_YYYYMMDD.xlsx   # 4h 日报汇总（含图表）
└── ETH_Phase_Daily_1h_YYYYMMDD.xlsx   # 1h 日报汇总（含图表）
```

---

## ⚙️ 配置项

### 环境变量控制

| 变量 | 默认 | 说明 |
|------|------|------|
| `ETH_FILTER_1H_BY_4H` | `1` | 4h过滤1h信号开关（`0`关闭） |

### 命令行参数

```bash
python3 eth_phase_meter.py                    # 单次运行
python3 eth_phase_meter.py --daemon --interval=4  # 守护模式，每4小时
```

---

## 📡 数据源

| 数据源 | 用途 | 需要 Key | 免费限制 |
|--------|------|----------|----------|
| Binance Spot/Futures | K线、OI、资金费率、多空比、CVD | ❌ | 无 |
| Deribit | 期权 IV、PCR、OI | ❌ | 无 |
| Alternative.me | Fear & Greed 指数 | ❌ | 无 |
| FRED | DXY、VIX、US10Y、US2Y | ✅ | 无限制 |
| yfinance | 宏观数据备选 | ❌ | 偶尔限流 |
| Finnhub | 经济/加密新闻 | ✅ | 60次/分钟 |
| CryptoPanic | ETH 新闻情绪 | ✅ | Developer tier |
| DefiLlama | ETH TVL | ❌ | 无 |
| Etherscan | Gas Price、ETH Supply | ✅ | 5次/秒 |

---

## 🤝 贡献

欢迎 PR 和 Issue！

---

## 📜 License

[MIT](LICENSE) © 2026 stanleyrprose
