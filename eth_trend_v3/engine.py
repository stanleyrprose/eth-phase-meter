from __future__ import annotations
import numpy as np
import pandas as pd
import eth_phase_meter as core
from .quality import summarize_factors
from .models import SnapshotResult

def crowding(raw: dict) -> int:
    df,d,o,s=raw['candles'],raw['derivatives'],raw['options'],raw['sentiment']; z=[]
    if df is not None and len(df)>=30: z.append((max(0,(abs(float(core.calc_rsi(df.close).iloc[-1])-50)-15)/25),15))
    if d.get('funding_percentile') is not None: z.append((abs(float(d['funding_percentile'])-.5)*2,25))
    elif d.get('funding_rate') is not None: z.append((min(1,abs(float(d['funding_rate']))/.001),15))
    if d.get('long_short_ratio') is not None: z.append((min(1,abs(np.log(max(float(d['long_short_ratio']),1e-6)))/np.log(2.5)),15))
    if s.get('fng_value') is not None: z.append((max(0,(abs(float(s['fng_value'])-50)-20)/30),15))
    if o.get('put_call_oi_ratio') is not None: z.append((min(1,abs(float(o['put_call_oi_ratio'])-.8)/.8),10))
    if o.get('iv_skew_25d_proxy_near') is not None: z.append((min(1,abs(float(o['iv_skew_25d_proxy_near']))/12),20))
    return round(100*sum(v*w for v,w in z)/sum(w for _,w in z)) if z else 0

def volatility(raw: dict) -> int:
    df,o,x=raw['candles'],raw['options'],raw['macro']; z=[]
    if df is not None and len(df)>=30:
        c,h,l=df.close,df.high,df.low; tr=pd.concat([(h-l),(h-c.shift(1)).abs(),(l-c.shift(1)).abs()],axis=1).max(axis=1); z.append((min(1,float(tr.rolling(14).mean().iloc[-1]/c.iloc[-1])/.05),25))
    iv=[float(v) for v in (o.get('atm_iv_near'),o.get('atm_iv_next')) if v is not None and float(v)>0]
    if iv: z.append((max(0,min(1,(sum(iv)/len(iv)-25)/75)),25))
    if o.get('dvol_current') is not None: z.append((max(0,min(1,(float(o['dvol_current'])-25)/75)),25))
    if x.get('vix') is not None: z.append((max(0,min(1,(float(x['vix'])-12)/28)),15))
    if x.get('econ_calendar'): z.append((1,10))
    return round(100*sum(v*w for v,w in z)/sum(w for _,w in z)) if z else 0

def regime(raw: dict,direction:int,vol:int)->str:
    df=raw['candles']
    if df is None or len(df)<60: return 'DATA_DEGRADED'
    c,h,l=df.close,df.high,df.low; tr=pd.concat([(h-l),(h-c.shift(1)).abs(),(l-c.shift(1)).abs()],axis=1).max(axis=1); atr=float(tr.rolling(14).mean().iloc[-1]); atr_pct=atr/float(c.iloc[-1]) if c.iloc[-1] else 0; efficiency=abs(float(c.iloc[-1]-c.iloc[-20]))/max(float(c.diff().abs().tail(20).sum()),1e-9)
    if vol>=75 or atr_pct>=.05: return 'VOL_EXPANSION'
    if direction>=30 and efficiency>=.35: return 'TREND_UP'
    if direction<=-30 and efficiency>=.35: return 'TREND_DOWN'
    if abs(direction)<20 and efficiency<.30: return 'RANGE'
    return 'TRANSITION'

def state(direction:int,coverage:float,crowd:int,vol:int):
    if coverage<50: return 'DATA_INSUFFICIENT','覆盖率不足50%，不输出方向结论'
    if direction>=60: s,text='STRONG_BULL','强多方向证据'
    elif direction>=20: s,text='WEAK_BULL','偏多方向证据'
    elif direction<=-60: s,text='STRONG_BEAR','强空方向证据'
    elif direction<=-20: s,text='WEAK_BEAR','偏空方向证据'
    else: s,text='NEUTRAL','方向证据不足'
    if crowd>=70: text+='；拥挤度高'
    if vol>=70: text+='；波动风险高'
    return s,text

def evaluate(timeframe,raw,factors,timestamp):
    q=summarize_factors(factors); crowd=crowding(raw); vol=volatility(raw); reg=regime(raw,q['final_direction'],vol); st,expl=state(q['final_direction'],q['coverage'],crowd,vol); df=raw['candles']; price=float(df.close.iloc[-1]) if df is not None and len(df) else 0.0
    return SnapshotResult(timeframe,timestamp,price,int(q['final_direction']),int(q['available_bias']),q['coverage'],q['confidence'],crowd,vol,reg,st,expl,factors,q)
