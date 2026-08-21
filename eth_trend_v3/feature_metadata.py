from __future__ import annotations

METHODOLOGY={
 'MA':'High','MACD':'High','RSI':'High','KDJ':'Medium','Structure':'High','Trend':'High',
 'Price×OI':'High','TakerFlow':'Medium','CVDTrend':'Medium','CVDNet':'Medium',
 'OptionSkew':'Medium/High','PutCallOI':'Medium','FearGreed':'Low/Medium','SentTrend':'Low/Medium',
 'BTC24h':'High','ETHBTC':'High','DXY':'High','VIX':'High','Yields':'High','TVL7d':'Medium','News':'Low/Medium',
}

def enrich_factor_metadata(factors, predictive_weights:dict|None=None)->list[dict]:
    predictive_weights=predictive_weights or {}
    out=[]
    for f in factors:
        out.append({
          'family':f.family,'name':f.name,'source_type':f.source or 'unknown',
          'data_quality':'High' if f.active and f.source else 'Medium' if f.active else 'Unavailable',
          'freshness':'current-run' if f.active else 'unavailable',
          'coverage':100 if f.active else 0,
          'methodology_reliability':METHODOLOGY.get(f.name,'Experimental'),
          'predictive_weight':predictive_weights.get(f.name),
          'status':f.status,
        })
    return out
