from __future__ import annotations
from collections import defaultdict

CLUSTERS={
 "momentum":{"MA","MACD","RSI","KDJ","Trend"},
 "structure":{"Structure"},
 "derivatives_positioning":{"Price×OI"},
 "order_flow":{"TakerFlow","CVDTrend","CVDNet"},
 "options_positioning":{"OptionSkew","PutCallOI"},
 "sentiment":{"FearGreed","SentTrend"},
 "macro_risk":{"BTC24h","ETHBTC","DXY","VIX","Yields","TVL7d","News"},
}

def cluster_factors(factors)->dict:
    grouped=defaultdict(list); reverse={n:c for c,names in CLUSTERS.items() for n in names}
    for f in factors:
        grouped[reverse.get(f.name,f.family.lower())].append(f)
    out={}
    for cluster,fs in grouped.items():
        active=[f for f in fs if f.active]; w=sum(f.weight for f in active); nominal=sum(f.weight for f in fs)
        score=sum(f.contribution for f in active)/w*100 if w else None
        out[cluster]={"score":round(score,3) if score is not None else None,"coverage":round(100*w/nominal,1) if nominal else 0,"features":[f.name for f in fs]}
    return out
