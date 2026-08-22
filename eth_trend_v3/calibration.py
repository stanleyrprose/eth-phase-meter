from __future__ import annotations

def reliability_from_metrics(metrics:dict,coverage:float,sample_size:int)->str:
    if not metrics or sample_size<100 or coverage<50: return "Low"
    lift=metrics.get("brier_lift",0); cal=metrics.get("calibration") or []; errors=[abs(x["predicted"]-x["actual"]) for x in cal if x.get("n",0)>=10]; ece=sum(errors)/len(errors) if errors else 1
    if lift>.01 and ece<.08 and coverage>=80 and sample_size>=250: return "High"
    if lift>0 and ece<.15 and coverage>=70 and sample_size>=150: return "Medium"
    return "Low"

def probability_state(p):
    if p is None:return "UNAVAILABLE"
    if p>.65:return "Bullish"
    if p>=.55:return "Mild Bullish"
    if p>=.45:return "Neutral"
    if p>=.35:return "Mild Bearish"
    return "Bearish"
