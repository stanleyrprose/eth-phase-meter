from __future__ import annotations
import datetime as dt
import eth_phase_meter as core
import github_actions_runner as fallback

def _deribit_24h(inst: str):
    end = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000); start = end - 26 * 3600 * 1000
    payload = core.safe_get(f'{core.DERIBIT_BASE}/public/get_tradingview_chart_data', {'instrument_name': inst, 'start_timestamp': start, 'end_timestamp': end, 'resolution': '60'})
    r = payload.get('result') if isinstance(payload, dict) else None; closes = r.get('close') if isinstance(r, dict) else None
    if not closes or len(closes) < 2 or float(closes[0]) <= 0: return None
    p0, p1 = float(closes[0]), float(closes[-1]); return p0, p1, (p1 / p0 - 1) * 100

def collect(timeframe: str) -> dict:
    oi_windows = {'1h': 12, '4h': 48, '1d': 288}
    candles = fallback.fetch_market_klines(interval=timeframe, limit=220)
    derivatives = fallback.fetch_derivatives(oi_limit=oi_windows.get(timeframe, 48), ratio_period=timeframe) or {}
    options = core.fetch_deribit_options() or {}; sentiment = core.fetch_sentiment() or {}; macro = core.fetch_macro() or {}
    btc = eth = None
    if macro.get('btc_change_24h') is None or macro.get('ethbtc_change') is None: btc, eth = _deribit_24h('BTC-PERPETUAL'), _deribit_24h('ETH-PERPETUAL')
    if macro.get('btc_change_24h') is None and btc: macro.update(btc_price=btc[1], btc_change_24h=btc[2], btc_src='Deribit')
    if macro.get('ethbtc_change') is None and btc and eth:
        r0, r1 = eth[0] / btc[0], eth[1] / btc[1]
        if r0 > 0: macro.update(ethbtc_price=r1, ethbtc_change=(r1 / r0 - 1) * 100, ethbtc_src='Deribit synthetic')
    return {'candles': candles, 'derivatives': derivatives, 'options': options, 'sentiment': sentiment, 'macro': macro}
