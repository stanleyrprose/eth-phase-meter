from __future__ import annotations
import numpy as np

def correlation_report(rows:list[dict],keys:list[str])->dict:
    usable=[]
    for r in rows:
        vals=[r.get(k) for k in keys]
        if all(isinstance(v,(int,float)) and np.isfinite(v) for v in vals): usable.append(vals)
    if len(usable)<30: return {'available':False,'reason':'INSUFFICIENT_HISTORY','n':len(usable),'highly_correlated':[]}
    x=np.asarray(usable,dtype=float); corr=np.corrcoef(x,rowvar=False); high=[]
    for i in range(len(keys)):
        for j in range(i+1,len(keys)):
            if abs(corr[i,j])>=.8: high.append({'a':keys[i],'b':keys[j],'corr':round(float(corr[i,j]),3)})
    return {'available':True,'n':len(usable),'keys':keys,'matrix':corr.round(4).tolist(),'highly_correlated':high}
