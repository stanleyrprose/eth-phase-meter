from __future__ import annotations


def _regime_name(payload: dict | None):
    if not isinstance(payload, dict):
        return None
    r = payload.get("regime")
    if isinstance(r, dict):
        return r.get("regime")
    if isinstance(r, str):
        return r
    return None


def build_alerts(current, previous=None, anomalies=None):
    alerts = []
    previous = previous or {}
    anomalies = anomalies or []

    prev_regime = _regime_name(previous)
    cur_regime = _regime_name(current)
    if prev_regime and cur_regime and prev_regime != cur_regime:
        alerts.append({
            "level": 1,
            "type": "STRUCTURAL_CHANGE",
            "message": f"Regime {prev_regime} → {cur_regime}",
        })

    for h, v in (current.get("forecasts") or {}).items():
        p = v.get("probability_up")
        pp = ((previous.get("forecasts") or {}).get(h) or {}).get("probability_up")
        if isinstance(p, (int, float)) and isinstance(pp, (int, float)) and abs(p - pp) >= 0.12:
            alerts.append({
                "level": 2,
                "type": "PROBABILITY_SHIFT",
                "message": f"P({h} Up) {pp:.0%} → {p:.0%}",
            })

    if current.get("data_health", {}).get("status") != "NORMAL":
        alerts.append({
            "level": 3,
            "type": "DATA_FAILURE",
            "message": current.get("data_health", {}).get("status"),
        })
    if current.get("volatility_risk", 0) >= 75:
        alerts.append({
            "level": 3,
            "type": "VOLATILITY_SURGE",
            "message": f"Volatility risk {current['volatility_risk']:.0f}/100",
        })
    if current.get("crowding", 0) >= 80:
        alerts.append({
            "level": 3,
            "type": "LEVERAGE_EXTREME",
            "message": f"Crowding {current['crowding']:.0f}/100",
        })

    for a in anomalies:
        alerts.append({
            "level": 3,
            "type": a.get("type", "ANOMALY"),
            "message": f"{a.get('type','ANOMALY')} robust_z={a.get('robust_z')} value={a.get('value')}",
        })

    return alerts
