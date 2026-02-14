# Changelog

## [1.0.0] - 2026-02-13

### 🎉 初始版本

#### 四大评分维度（总分 ±100）
- **技术面 + 衍生品** (±35)：MA/MACD/RSI/KDJ + OI×价格四象限 + 资金费率分位 + CVD
- **期权结构** (±25)：ATM IV + IV期限结构 + PCR + IV偏度 + OI集中度
- **社交情绪** (±15)：Fear & Greed 指数 + 情绪趋势 + 24h动量
- **宏观经济** (±25)：DXY/VIX/US10Y/US2Y + BTC动量 + 新闻情绪 + TVL + Gas

#### 功能
- 双周期分析（4h + 1h），每4小时自动运行
- A1：多窗口结构化关键位（20/50根突破确认）
- A2：趋势强度（ATR14 + ADX14 + 斜率/ATR）
- A3：多周期共振 + 4h过滤1h信号开关
- B1：OI×价格四象限 + 短线策略提示
- B2：资金费率30天分位数
- C1/C2：IV偏度（OTM Put vs Call proxy）
- C3：近月OI集中度（Top3 strikes）
- D：FRED宏观 + Finnhub新闻 + CryptoPanic + DefiLlama TVL + Etherscan Gas
- E：日报Excel折线图（总分 + 四维度走势）
- Telegram 自动推送（文字摘要 + Excel 附件）
- systemd 服务化部署
