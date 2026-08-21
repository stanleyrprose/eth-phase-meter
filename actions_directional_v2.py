from __future__ import annotations
import csv, datetime as dt
from pathlib import Path
import numpy as np, pandas as pd
import eth_phase_meter as m

FULL=100.0
_orig_macro=m.fetch_macro

def add(a,n,v,w,ok=True,src=''):
    if not ok or v is None or not np.isfinite(v): a.append((n,w,None,0.0,src)); return
    v=max(-1.,min(1.,float(v))); a.append((n,w,v,v*w,src))

def norm(a):
    active=sum(w for _,w,v,_,_ in a if v is not None); raw=sum(c for *_,v,c,_ in a if v is not None)
    return raw,active,(round(raw/active*100) if active else 0),active/FULL*100

def deribit24(inst):
    end=int(dt.datetime.now(dt.timezone.utc).timestamp()*1000); start=end-26*3600*1000
    p=m.safe_get(f'{m.DERIBIT_BASE}/public/get_tradingview_chart_data',{'instrument_name':inst,'start_timestamp':start,'end_timestamp':end,'resolution':'60'})
    r=p.get('result') if isinstance(p,dict) else None; c=r.get('close') if isinstance(r,dict) else None
    if not c or len(c)<2 or float(c[0])<=0:return None
    p0,p1=float(c[0]),float(c[-1]); return p0,p1,(p1/p0-1)*100

def fetch_macro():
    x=_orig_macro() or {}; btc=eth=None
    if 'btc_change_24h' not in x or 'ethbtc_change' not in x: btc,eth=deribit24('BTC-PERPETUAL'),deribit24('ETH-PERPETUAL')
    if 'btc_change_24h' not in x and btc: x.update(btc_price=btc[1],btc_change_24h=btc[2],btc_src='Deribit')
    if 'ethbtc_change' not in x and btc and eth:
        r0=eth[0]/btc[0]; r1=eth[1]/btc[1]
        if r0>0:x.update(ethbtc_price=r1,ethbtc_change=(r1/r0-1)*100,ethbtc_src='Deribit synthetic')
    return x

def technical(df):
    a=[]
    if df is None or len(df)<100:
        for n,w in [('MA',10),('MACD',8),('RSI',5),('KDJ',4),('Structure',8),('Trend',5)]: add(a,n,None,w,False)
        return a
    c,h,l=df.close,df.high,df.low; last=float(c.iloc[-1]); ma7,ma25,ma99=[float(m.sma(c,n).iloc[-1]) for n in (7,25,99)]
    v=1 if ma7>ma25>ma99 else -1 if ma7<ma25<ma99 else .4 if ma7>ma25 else -.4 if ma7<ma25 else 0; add(a,'MA',v,10,src='candles')
    _,_,hist=m.calc_macd(c); h0,h1=float(hist.iloc[-1]),float(hist.iloc[-2]); v=1 if h0>0 and h0>h1 else .4 if h0>0 else -1 if h0<0 and h0<h1 else -.4 if h0<0 else 0; add(a,'MACD',v,8,src='candles')
    r=float(m.calc_rsi(c).iloc[-1]); v=1 if r>=65 else .6 if r>=55 else 0 if r>45 else -.6 if r>35 else -1; add(a,'RSI',v,5,src='candles')
    k,d,_=m.calc_kdj(h,l,c); k0,d0=float(k.iloc[-1]),float(d.iloc[-1]); ku=k0>d0 and float(k.iloc[-2])<=float(d.iloc[-2]); kd=k0<d0 and float(k.iloc[-2])>=float(d.iloc[-2]); v=1 if ku else -1 if kd else .5 if k0>d0 else -.5 if k0<d0 else 0; add(a,'KDJ',v,4,src='candles')
    prev=float(c.iloc[-2]); h20,l20=float(h.iloc[:-1].tail(20).max()),float(l.iloc[:-1].tail(20).min()); h50,l50=float(h.iloc[:-1].tail(50).max()),float(l.iloc[:-1].tail(50).min())
    if prev<=h50<last:v=1
    elif prev>=l50>last:v=-1
    elif prev<=h20<last:v=.75
    elif prev>=l20>last:v=-.75
    else:v=max(-.5,min(.5,((last-l50)/(h50-l50)-.5) if h50!=l50 else 0))
    add(a,'Structure',v,8,src='candles')
    tr=pd.concat([(h-l),(h-c.shift(1)).abs(),(l-c.shift(1)).abs()],axis=1).max(axis=1); atr=float(tr.rolling(14).mean().iloc[-1]); slope=float(np.polyfit(np.arange(30),c.tail(30).values,1)[0])/atr if atr>0 else 0
    up=h.diff(); dn=-l.diff(); pdm=np.where((up>dn)&(up>0),up,0.); mdm=np.where((dn>up)&(dn>0),dn,0.); tr14=tr.rolling(14).sum(); pdi=100*(pd.Series(pdm,index=df.index).rolling(14).sum()/tr14); mdi=100*(pd.Series(mdm,index=df.index).rolling(14).sum()/tr14); di=1 if pdi.iloc[-1]>mdi.iloc[-1] else -1 if mdi.iloc[-1]>pdi.iloc[-1] else 0; add(a,'Trend',.5*di+.5*max(-1,min(1,slope/.12)),5,src='candles')
    return a

def deriv(d):
    a=[]; hasoi='oi_change_window' in d or 'OI_change_4h' in d; haspx='price_change_period' in d
    if hasoi and haspx:
        oi=float(d.get('oi_change_window',d.get('OI_change_4h'))); px=float(d['price_change_period']); v=1 if px>0 and oi>0 else -1 if px<0 and oi>0 else .35 if px>0 and oi<0 else -.35 if px<0 and oi<0 else 0; add(a,'Price×OI',v,10,src=d.get('_data_source',''))
    else:add(a,'Price×OI',None,10,False)
    if 'taker_buy_sell_avg' in d:add(a,'TakerFlow',max(-1,min(1,(float(d['taker_buy_sell_avg'])-1)/.15)),6,src='Binance')
    else:add(a,'TakerFlow',None,6,False)
    if 'cvd_slope_recent' in d:
        sr=float(d['cvd_slope_recent']); se=float(d.get('cvd_slope_earlier',0)); add(a,'CVDTrend',max(-1,min(1,sr/max(abs(sr),abs(se),5e6))),5,src='Binance')
    else:add(a,'CVDTrend',None,5,False)
    if 'cvd_current' in d:add(a,'CVDNet',max(-1,min(1,float(d['cvd_current'])/15e6)),4,src='Binance')
    else:add(a,'CVDNet',None,4,False)
    return a

def options(o):
    a=[]
    if o.get('otm_put_iv_near') and o.get('otm_call_iv_near'):add(a,'OptionSkew',max(-1,min(1,-float(o.get('iv_skew_25d_proxy_near',0))/10)),6,src='Deribit')
    else:add(a,'OptionSkew',None,6,False)
    if 'put_call_oi_ratio' in o:add(a,'PutCallOI',max(-1,min(1,(.8-float(o['put_call_oi_ratio']))/.6)),4,src='Deribit')
    else:add(a,'PutCallOI',None,4,False)
    return a

def sentiment(s):
    a=[]
    if 'fng_value' in s:
        f=float(s['fng_value']); add(a,'FearGreed',max(-1,min(1,(f-50)/40)),3,src='Alternative.me'); prev=float(s.get('fng_prev',f)); avg=float(s.get('fng_7d_avg',f)); add(a,'SentTrend',max(-1,min(1,((f-prev)+(f-avg))/20)),2,src='Alternative.me')
    else:add(a,'FearGreed',None,3,False);add(a,'SentTrend',None,2,False)
    return a

def macro(x):
    a=[]
    for key,n,w,scale,sign in [('btc_change_24h','BTC24h',5,5,1),('ethbtc_change','ETHBTC',4,3,1),('dxy_chg','DXY',3,.005,-1)]:
        if x.get(key) is not None:add(a,n,max(-1,min(1,sign*float(x[key])/scale)),w,src=x.get(key.replace('_chg','_src'),'market'))
        else:add(a,n,None,w,False)
    if x.get('vix') is not None:
        vi=float(x['vix']); ch=x.get('vix_chg'); v=.7*max(-1,min(1,(18-vi)/12))+.3*(max(-1,min(1,-float(ch)/.10)) if ch is not None else 0); add(a,'VIX',v,2,src=x.get('vix_src',''))
    else:add(a,'VIX',None,2,False)
    ys=[y for y in (x.get('us10y_chg'),x.get('us2y_chg')) if y is not None]
    if ys:add(a,'Yields',max(-1,min(1,-(sum(ys)/len(ys))/.02)),2,src='FRED/yfinance')
    else:add(a,'Yields',None,2,False)
    if x.get('tvl_7d_chg') is not None:add(a,'TVL7d',max(-1,min(1,float(x['tvl_7d_chg'])/.08)),2,src='DefiLlama')
    else:add(a,'TVL7d',None,2,False)
    news=x.get('crypto_news',{}) or {}
    if news.get('total',0)>0 and news.get('sentiment'):add(a,'News',1 if news['sentiment']=='bullish' else -1 if news['sentiment']=='bearish' else 0,2,src=news.get('source',''))
    else:add(a,'News',None,2,False)
    return a

def crowd(df,d,o,s):
    z=[]
    if df is not None and len(df)>=30:z += [(max(0,(abs(float(m.calc_rsi(df.close).iloc[-1])-50)-15)/25),15)]
    if d.get('funding_percentile') is not None:z += [(abs(float(d['funding_percentile'])-.5)*2,25)]
    elif d.get('funding_rate') is not None:z += [(min(1,abs(float(d['funding_rate']))/.001),15)]
    if d.get('long_short_ratio') is not None:z += [(min(1,abs(np.log(max(float(d['long_short_ratio']),1e-6)))/np.log(2.5)),15)]
    if s.get('fng_value') is not None:z += [(max(0,(abs(float(s['fng_value'])-50)-20)/30),15)]
    if o.get('put_call_oi_ratio') is not None:z += [(min(1,abs(float(o['put_call_oi_ratio'])-.8)/.8),10)]
    if o.get('iv_skew_25d_proxy_near') is not None:z += [(min(1,abs(float(o['iv_skew_25d_proxy_near']))/12),20)]
    return round(100*sum(v*w for v,w in z)/sum(w for _,w in z)) if z else 0

def vol(df,o,x):
    z=[]
    if df is not None and len(df)>=30:
        c,h,l=df.close,df.high,df.low; tr=pd.concat([(h-l),(h-c.shift(1)).abs(),(l-c.shift(1)).abs()],axis=1).max(axis=1); z += [(min(1,float(tr.rolling(14).mean().iloc[-1]/c.iloc[-1])/.05),25)]
    iv=[float(v) for v in (o.get('atm_iv_near'),o.get('atm_iv_next')) if v is not None and v>0]
    if iv:z += [(max(0,min(1,(sum(iv)/len(iv)-25)/75)),25)]
    if o.get('dvol_current') is not None:z += [(max(0,min(1,(float(o['dvol_current'])-25)/75)),25)]
    if x.get('vix') is not None:z += [(max(0,min(1,(float(x['vix'])-12)/28)),15)]
    if x.get('econ_calendar'):z += [(1,10)]
    return round(100*sum(v*w for v,w in z)/sum(w for _,w in z)) if z else 0

def phase(sc,cov,cr,vo):
    if cov<50:return '⚪ 数据不足','覆盖率<50%，等待更多数据恢复'
    if sc>=70:p,st='🟢 强多趋势','方向偏多：回调/确认后做多优先'
    elif sc>=30:p,st='🟢 偏多','偏多：回调做多优先'
    elif sc<=-70:p,st='🔴 强空趋势','方向偏空：反弹做空/降低多头敞口优先'
    elif sc<=-30:p,st='🔴 偏空','偏空：反弹减仓或轻仓做空'
    else:p,st='🟡 方向中性','方向优势不足；不要仅因中性就卖straddle'
    if cr>=70:st+='；拥挤度高，避免追涨杀跌'
    if vo>=70:st+='；波动率高，缩仓且避免裸卖波动率'
    return p,st

def run_analysis(tf='4h'):
    ts=dt.datetime.utcnow(); oi={'1h':12,'4h':48,'1d':288}; kl=m.fetch_binance_klines(interval=tf,limit=200); d=m.fetch_binance_derivatives(oi_limit=oi.get(tf,48),ratio_period=tf) or {}; o=m.fetch_deribit_options() or {}; s=m.fetch_sentiment() or {}; x=m.fetch_macro() or {}
    groups={'Technical':technical(kl),'Derivatives':deriv(d),'Options':options(o),'Sentiment':sentiment(s),'Macro':macro(x)}; allp=sum(groups.values(),[]); raw,active,sc,cov=norm(allp); cr,vo=crowd(kl,d,o,s),vol(kl,o,x); conf='High' if cov>=80 else 'Medium' if cov>=60 else 'Low'; ph,st=phase(sc,cov,cr,vo)
    def dim(names,mx):
        p=sum((groups[n] for n in names),[]); return {'score':round(sum(c for _,_,v,c,_ in p if v is not None)),'max':mx,'方向有效权重':f"{sum(w for _,w,v,_,_ in p if v is not None):.0f}/{mx}"}
    dims={'技术面+衍生品':dim(['Technical','Derivatives'],65),'期权结构':dim(['Options'],10),'社交情绪':dim(['Sentiment'],5),'宏观经济':dim(['Macro'],20)}
    return {'timeframe':tf,'timestamp':ts.strftime('%Y-%m-%d %H:%M UTC'),'price':float(kl.close.iloc[-1]) if kl is not None and len(kl) else 0,'dimensions':dims,'total_score':int(sc),'direction_raw':round(raw,2),'direction_active_max':round(active,2),'data_coverage':round(cov,1),'confidence':conf,'crowding_score':int(cr),'volatility_score':int(vo),'direction_factors':[{'factor':n,'weight':w,'value':v,'contribution':round(c,2),'source':src} for n,w,v,c,src in allp],'phase':ph,'strategy':st}

def tg(r):
    d=r['dimensions']; miss=[x['factor'] for x in r['direction_factors'] if x['value'] is None]
    lines=[f"📊 <b>ETH Direction Model v2 [{r['timeframe']}]</b> | {r['timestamp']}","━━━━━━━━━━━━━━━━━━━━",f"💰 价格: <b>${r['price']:,.2f}</b>",f"🎯 Direction: <b>{r['total_score']:+d}</b> /100",f"📡 Coverage: <b>{r['data_coverage']:.0f}%</b> | Confidence: <b>{r['confidence']}</b>",f"👥 Crowding: <b>{r['crowding_score']}</b>/100",f"🌪 Volatility: <b>{r['volatility_score']}</b>/100","━━━━━━━━━━━━━━━━━━━━",f"⭐ 阶段: <b>{r['phase']}</b>",f"⭐ 策略: {r['strategy']}","",f"方向贡献: 技术+衍生品 {d['技术面+衍生品']['score']:+d}/65 | 期权 {d['期权结构']['score']:+d}/10 | 情绪 {d['社交情绪']['score']:+d}/5 | 宏观 {d['宏观经济']['score']:+d}/20",f"数学含义: {r['direction_raw']:+.1f} / 可用权重 {r['direction_active_max']:.0f} ×100 = {r['total_score']:+d}"]
    if miss:lines.append('⚠️ 缺失方向因子: '+', '.join(miss))
    return '\n'.join(lines)

def resonance(rs):
    a,b=rs.get('4h'),rs.get('1h');
    if not a or not b:return None
    def t(r):return '?' if r.get('data_coverage',0)<50 else '多' if r['total_score']>=30 else '空' if r['total_score']<=-30 else '震'
    t4,t1=t(a),t(b)
    if '?' in (t4,t1):rr,n='⚪ 数据不足','至少一个周期覆盖率<50%'
    elif t4==t1 and t4!='震':rr,n='✅ 共振','1h/4h方向一致'
    elif t4!='震' and t1!='震' and t4!=t1:rr,n='⚠️ 背离','1h/4h方向相反'
    elif t4=='震' and t1!='震':rr,n='🟡 1h主导','4h方向不足，1h有方向'
    elif t4!='震' and t1=='震':rr,n='🟠 4h主导','4h有方向，1h等待确认'
    else:rr,n='🟡 双周期中性','方向优势不足'
    return {'resonance':rr,'note':n,'d1_4h':a['total_score'],'d1_1h':b['total_score'],'tag4':t4,'tag1':t1}

def history(r):
    p=Path(m.OUTPUT_DIR)/'direction_v2_history.csv'; p.parent.mkdir(parents=True,exist_ok=True); fields=['timestamp','timeframe','price','direction_score','coverage','crowding','volatility','confidence']; row=dict(zip(fields,[r['timestamp'],r['timeframe'],r['price'],r['total_score'],r['data_coverage'],r['crowding_score'],r['volatility_score'],r['confidence']])); ex=p.exists()
    with p.open('a',newline='',encoding='utf-8') as f:w=csv.DictWriter(f,fieldnames=fields); (None if ex else w.writeheader()); w.writerow(row)

def apply():
    m.fetch_macro=fetch_macro; m.run_analysis=run_analysis; m.format_tg_summary=tg; m.compute_resonance=resonance; old=m.run_single
    def wrapped(*a,**k):
        r=old(*a,**k)
        if r:
            try:history(r)
            except Exception as e:print('[WARN] history',e)
        return r
    m.run_single=wrapped
