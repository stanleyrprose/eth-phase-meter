from __future__ import annotations

def build_alerts(current,previous=None):
    alerts=[]; previous=previous or {}
    if previous.get("regime") and previous.get("regime")!=current.get("regime"): alerts.append({"level":1,"type":"STRUCTURAL_CHANGE","message":f"Regime {previous.get('regime')} → {current.get('regime')}"})
    for h,v in (current.get("forecasts") or {}).items():
        p=v.get("probability_up"); pp=((previous.get("forecasts") or {}).get(h) or {}).get("probability_up")
        if isinstance(p,(int,float)) and isinstance(pp,(int,float)) and abs(p-pp)>=.12: alerts.append({"level":2,"type":"PROBABILITY_SHIFT","message":f"P({h} Up) {pp:.0%} → {p:.0%}"})
    if current.get("data_health",{}).get("status")!="NORMAL": alerts.append({"level":3,"type":"DATA_FAILURE","message":current.get("data_health",{}).get("status")})
    if current.get("volatility_risk",0)>=75: alerts.append({"level":3,"type":"VOLATILITY_SURGE","message":f"Volatility risk {current['volatility_risk']:.0f}/100"})
    if current.get("crowding",0)>=80: alerts.append({"level":3,"type":"LEVERAGE_EXTREME","message":f"Crowding {current['crowding']:.0f}/100"})
    return alerts
