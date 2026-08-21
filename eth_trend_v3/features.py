from __future__ import annotations
import numpy as np
import pandas as pd
import eth_phase_meter as core
from .models import Factor

def _add(out, family, name, value, weight, source='', status='GOOD'):
    if value is None or not np.isfinite(value): out.append(Factor(family, name, weight, None, 0.0, source, 'UNAVAILABLE')); return
    value = max(-1.0, min(1.0, float(value))); out.append(Factor(family, name, weight, value, value * weight, source, status))

def technical(df) -> list[Factor]:
    out=[]; specs=[('MA',10),('MACD',8),('RSI',5),('KDJ',4),('Structure',8),('Trend',5)]
    if df is None or len(df)<100:
        for n,w in specs: _add(out,'Technical',n,None,w)
        return out
    c,h,l=df.close,df.high,df.low; last=float(c.iloc[-1]); ma20,ma50,ma200=[float(core.sma(c,n).iloc[-1]) for n in (20,50,200)]
    ma=1 if last>ma20>ma50>ma200 else -1 if last<ma20<ma50<ma200 else .5 if last>ma20>ma50 else -.5 if last<ma20<ma50 else 0; _add(out,'Technical','MA',ma,10,'candles')
    _,_,hist=core.calc_macd(c); h0,h1=float(hist.iloc[-1]),float(hist.iloc[-2]); macd=1 if h0>0 and h0>h1 else .4 if h0>0 else -1 if h0<0 and h0<h1 else -.4 if h0<0 else 0; _add(out,'Technical','MACD',macd,8,'candles')
    rsi=float(core.calc_rsi(c).iloc[-1]); rv=1 if rsi>=65 else .6 if rsi>=55 else 0 if rsi>45 else -.6 if rsi>35 else -1; _add(out,'Technical','RSI',rv,5,'candles')
    k,d,_=core.calc_kdj(h,l,c); k0,d0=float(k.iloc[-1]),float(d.iloc[-1]); cu=k0>d0 and float(k.iloc[-2])<=float(d.iloc[-2]); cd=k0<d0 and float(k.iloc[-2])>=float(d.iloc[-2]); kv=1 if cu else -1 if cd else .5 if k0>d0 else -.5 if k0<d0 else 0; _add(out,'Technical','KDJ',kv,4,'candles')
    prev=float(c.iloc[-2]); h20,l20=float(h.iloc[:-1].tail(20).max()),float(l.iloc[:-1].tail(20).min()); h50,l50=float(h.iloc[:-1].tail(50).max()),float(l.iloc[:-1].tail(50).min())
    if prev<=h50<last: sv=1
    elif prev>=l50>last: sv=-1
    elif prev<=h20<last: sv=.75
    elif prev>=l20>last: sv=-.75
    else: sv=max(-.5,min(.5,((last-l50)/(h50-l50)-.5) if h50!=l50 else 0))
    _add(out,'Technical','Structure',sv,8,'candles')
    tr=pd.concat([(h-l),(h-c.shift(1)).abs(),(l-c.shift(1)).abs()],axis=1).max(axis=1); atr=float(tr.rolling(14).mean().iloc[-1]); slope=float(np.polyfit(np.arange(30),c.tail(30).values,1)[0])/atr if atr>0 else 0
    up,dn=h.diff(),-l.diff(); pdm=np.where((up>dn)&(up>0),up,0.); mdm=np.where((dn>up)&(dn>0),dn,0.); tr14=tr.rolling(14).sum(); pdi=100*(pd.Series(pdm,index=df.index).rolling(14).sum()/tr14); mdi=100*(pd.Series(mdm,index=df.index).rolling(14).sum()/tr14); di=1 if pdi.iloc[-1]>mdi.iloc[-1] else -1 if mdi.iloc[-1]>pdi.iloc[-1] else 0
    _add(out,'Technical','Trend',.5*di+.5*max(-1,min(1,slope/.12)),5,'candles'); return out

def derivatives(d: dict) -> list[Factor]:
    out=[]; has_oi='oi_change_window' in d or 'OI_change_4h' in d; has_px='price_change_period' in d
    if has_oi and has_px:
        oi=float(d.get('oi_change_window',d.get('OI_change_4h'))); px=float(d['price_change_period']); v=1 if px>0 and oi>0 else -1 if px<0 and oi>0 else .35 if px>0 and oi<0 else -.35 if px<0 and oi<0 else 0; _add(out,'Derivatives','Price×OI',v,10,d.get('_data_source',''))
    else: _add(out,'Derivatives','Price×OI',None,10)
    _add(out,'Derivatives','TakerFlow',max(-1,min(1,(float(d['taker_buy_sell_avg'])-1)/.15)) if d.get('taker_buy_sell_avg') is not None else None,6,d.get('_data_source',''))
    if d.get('cvd_slope_recent') is not None:
        sr,se=float(d['cvd_slope_recent']),float(d.get('cvd_slope_earlier',0)); cvdt=max(-1,min(1,sr/max(abs(sr),abs(se),5e6)))
    else: cvdt=None
    _add(out,'Derivatives','CVDTrend',cvdt,5,d.get('_data_source','')); _add(out,'Derivatives','CVDNet',max(-1,min(1,float(d['cvd_current'])/15e6)) if d.get('cvd_current') is not None else None,4,d.get('_data_source','')); return out

def options(o: dict) -> list[Factor]:
    out=[]; ok=o.get('otm_put_iv_near') is not None and o.get('otm_call_iv_near') is not None; _add(out,'Options','OptionSkew',max(-1,min(1,-float(o.get('iv_skew_25d_proxy_near',0))/10)) if ok else None,6,'Deribit'); _add(out,'Options','PutCallOI',max(-1,min(1,(.8-float(o['put_call_oi_ratio']))/.6)) if o.get('put_call_oi_ratio') is not None else None,4,'Deribit'); return out

def sentiment(s: dict) -> list[Factor]:
    out=[]
    if s.get('fng_value') is not None:
        f=float(s['fng_value']); prev=float(s.get('fng_prev',f)); avg=float(s.get('fng_7d_avg',f)); _add(out,'Sentiment','FearGreed',max(-1,min(1,(f-50)/40)),3,'Alternative.me'); _add(out,'Sentiment','SentTrend',max(-1,min(1,((f-prev)+(f-avg))/20)),2,'Alternative.me')
    else: _add(out,'Sentiment','FearGreed',None,3); _add(out,'Sentiment','SentTrend',None,2)
    return out

def macro(x: dict) -> list[Factor]:
    out=[]
    for key,name,w,scale,sign in [('btc_change_24h','BTC24h',5,5,1),('ethbtc_change','ETHBTC',4,3,1),('dxy_chg','DXY',3,.005,-1)]:
        val=x.get(key); _add(out,'Macro',name,max(-1,min(1,sign*float(val)/scale)) if val is not None else None,w,x.get(key.replace('_chg','_src'),'market'))
    if x.get('vix') is not None:
        vi=float(x['vix']); ch=x.get('vix_chg'); vv=.7*max(-1,min(1,(18-vi)/12))+.3*(max(-1,min(1,-float(ch)/.10)) if ch is not None else 0); _add(out,'Macro','VIX',vv,2,x.get('vix_src',''))
    else: _add(out,'Macro','VIX',None,2)
    ys=[float(y) for y in (x.get('us10y_chg'),x.get('us2y_chg')) if y is not None]; _add(out,'Macro','Yields',max(-1,min(1,-(sum(ys)/len(ys))/.02)) if ys else None,2,'FRED/yfinance'); _add(out,'Macro','TVL7d',max(-1,min(1,float(x['tvl_7d_chg'])/.08)) if x.get('tvl_7d_chg') is not None else None,2,'DefiLlama')
    news=x.get('crypto_news',{}) or {}; nv=1 if news.get('sentiment')=='bullish' else -1 if news.get('sentiment')=='bearish' else 0 if news.get('total',0)>0 else None; _add(out,'Macro','News',nv,2,news.get('source','')); return out

def all_factors(raw: dict) -> list[Factor]: return technical(raw['candles'])+derivatives(raw['derivatives'])+options(raw['options'])+sentiment(raw['sentiment'])+macro(raw['macro'])
