from __future__ import annotations
import math
import numpy as np

def validate_proxy(proxy:list[float],benchmark:list[float],min_n:int=60)->dict:
    pairs=[(float(a),float(b)) for a,b in zip(proxy,benchmark) if isinstance(a,(int,float)) and isinstance(b,(int,float)) and math.isfinite(a) and math.isfinite(b)]
    if len(pairs)<min_n: return {'status':'GATED','kill':False,'reason':'INSUFFICIENT_BENCHMARK_SAMPLE','n':len(pairs)}
    a=np.asarray([x[0] for x in pairs]); b=np.asarray([x[1] for x in pairs]); corr=float(np.corrcoef(a,b)[0,1]); aq=np.quantile(a,[.1,.9]); bq=np.quantile(b,[.1,.9]); extreme=((a<=aq[0])==(b<=bq[0]))|((a>=aq[1])==(b>=bq[1])); extreme_agreement=float(extreme.mean())
    passed=bool(corr>=.6 and extreme_agreement>=.7)
    return {'status':'PASS' if passed else 'KILL','kill':not passed,'n':len(pairs),'correlation':round(corr,4),'extreme_agreement':round(extreme_agreement,4),'reason':'' if passed else 'Benchmark correlation/extreme-zone gate failed'}
