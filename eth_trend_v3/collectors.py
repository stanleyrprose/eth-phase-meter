from __future__ import annotations
import datetime as dt
import eth_phase_meter as core
import github_actions_runner as fallback
from .external_state import collect_external_state

def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def _deribit_24h(inst: str):
    end = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000); start = end - 26 * 3600 * 1000
    payload = core.safe_get(f'{core.DERIBIT_BASE}/public/get_tradingview_chart_data', {'instrument_name': inst, 'start_timestamp': start, 'end_timestamp': end, 'resolution': '60'})
    r = payload.get('result') if isinstance(payload, dict) else None; closes = r.get('close') if isinstance(r, dict) else None
    if not closes or len(closes) < 2 or float(closes[0]) <= 0: return None
    p0, p1 = float(closes[0]), float(closes[-1]); return p0, p1, (p1 / p0 - 1) * 100

def collect(timeframe: str) -> dict:
    oi_windows = {'1h': 12, '4h': 48, '1d': 288}
    stamps={}
    candles = fallback.fetch_market_klines(interval=timeframe, limit=220); stamps['candles']={'observed_at':_now(),'source':'Binance->Deribit fallback'}
    derivatives = fallback.fetch_derivatives(oi_limit=oi_windows.get(timeframe, 48), ratio_period=timeframe) or {}; stamps['derivatives']={'observed_at':_now(),'source':derivatives.get('_data_source','exchange')}
    options = core.fetch_deribit_options() or {}; stamps['options']={'observed_at':_now(),'source':'Deribit'}
    sentiment = core.fetch_sentiment() or {}; stamps['sentiment']={'observed_at':_now(),'source':'Alternative.me/optional news'}
    macro = core.fetch_macro() or {}; stamps['macro']={'observed_at':_now(),'source':'FRED/yfinance/DefiLlama'}
    btc = eth = None
    if macro.get('btc_change_24h') is None or macro.get('ethbtc_change') is None: btc, eth = _deribit_24h('BTC-PERPETUAL'), _deribit_24h('ETH-PERPETUAL')
    if macro.get('btc_change_24h') is None and btc: macro.update(btc_price=btc[1], btc_change_24h=btc[2], btc_src='Deribit')
    if macro.get('ethbtc_change') is None and btc and eth:
        r0, r1 = eth[0] / btc[0], eth[1] / btc[1]
        if r0 > 0: macro.update(ethbtc_price=r1, ethbtc_change=(r1 / r0 - 1) * 100, ethbtc_src='Deribit synthetic')
    ext=collect_external_state()
    for key in ('valuation','capital_flow','structural'):
        stamps[key]={'observed_at':_now(),'source':'configured external provider' if ext.get(key) else 'not configured'}
    return {'candles':candles,'derivatives':derivatives,'options':options,'sentiment':sentiment,'macro':macro,**ext,'_meta':stamps}
