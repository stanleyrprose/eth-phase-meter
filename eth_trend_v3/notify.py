def telegram_text(r):
    fam=r.quality['families']; missing=[f.name for f in r.factors if not f.active]; pos=sorted((f for f in r.factors if f.active and f.contribution>0),key=lambda x:x.contribution,reverse=True)[:3]; neg=sorted((f for f in r.factors if f.active and f.contribution<0),key=lambda x:x.contribution)[:3]; fmt=lambda xs:', '.join(f'{x.name} {x.contribution:+.1f}' for x in xs) if xs else '无'
    lines=[f'📊 <b>ETH Trend Engine v3 [{r.timeframe}]</b> | {r.timestamp}','━━━━━━━━━━━━━━━━━━━━',f'💰 Price: <b>${r.price:,.2f}</b>',f'🎯 Final Direction: <b>{r.final_direction:+d}</b>/100',f'🔎 Available bias: <b>{r.available_bias:+d}</b>/100',f'📡 Coverage: <b>{r.coverage:.0f}%</b> | Confidence: <b>{r.confidence}</b>',f'🧭 Rule Regime: <b>{r.regime}</b>',f'👥 Crowding: <b>{r.crowding}</b>/100',f'🌪 Volatility: <b>{r.volatility}</b>/100','━━━━━━━━━━━━━━━━━━━━',f'⭐ State: <b>{r.state}</b>',f'📝 {r.state_explanation}','','方向证据分桶:']
    labels={'Technical':'技术','Derivatives':'衍生品','Options':'期权','Sentiment':'情绪','Macro':'宏观'}
    for key in ('Technical','Derivatives','Options','Sentiment','Macro'):
        x=fam[key]; lines.append(f"  {labels[key]}: {x['contribution']:+.1f} | {x['active']:.0f}/{x['nominal']:.0f} ({x['coverage']:.0f}%)")
    lines+=['',f'⬆️ 主要偏多: {fmt(pos)}',f'⬇️ 主要偏空: {fmt(neg)}',f'数学含义: 全100权重净方向证据 = {r.final_direction:+d}',f'可用信号内部偏向 = {r.available_bias:+d}；Coverage={r.coverage:.0f}%','注：Direction不是上涨概率。']
    if missing: lines.append('⚠️ 缺失因子: '+', '.join(missing))
    return '\n'.join(lines)


def prd_summary(payload: dict) -> str:
    state=(payload.get('market_state') or {}).get('dimensions') or {}; forecasts=payload.get('forecasts') or {}; health=payload.get('data_health') or {}; regime=payload.get('regime') or {}
    lines=['📊 <b>ETH Market State [4H]</b>',f"💰 Price: <b>${payload.get('price',0):,.2f}</b>",'━━━━━━━━━━━━━━━━━━━━',f"🧭 Regime: <b>{regime.get('regime','Unavailable')}</b>"]
    engine=regime.get('engine')
    if engine:
        lines.append(f"Engine: {engine}")
    if isinstance(regime.get('max_posterior'),(int,float)):
        lines.append(f"HMM posterior: {regime['max_posterior']:.1%}")
    elif regime.get('probabilities'):
        top=max(regime['probabilities'].items(),key=lambda kv:kv[1]); lines.append(f"Regime probability: {top[1]:.0%}")
    if isinstance(regime.get('entropy'),(int,float)):
        lines.append(f"Regime entropy: {regime['entropy']:.3f}")
    if regime.get('fallback_reason'):
        lines.append(f"Fallback reason: {regime['fallback_reason']}")
    lines+=['','📈 <b>Forecast</b>']
    for h in ('3d','7d','30d'):
        f=forecasts.get(h) or {}; p=f.get('probability_up')
        lines.append(f"{h.upper()} Up: <b>{p:.0%}</b> | {f.get('reliability','Low')}" if isinstance(p,(int,float)) else f"{h.upper()} Up: <b>Unavailable</b> ({f.get('reason','not calibrated')})")
    lines+=['','🔎 <b>Market State</b>']
    labels={'trend':'Trend','valuation':'Valuation','capital_flow':'Capital Flow','crowding':'Crowding','structural_supply':'Structural','volatility_risk':'Volatility Risk'}
    for k,label in labels.items():
        d=state.get(k) or {}; v=d.get('score'); lines.append(f"{label:16} {v:+.0f}" if isinstance(v,(int,float)) else f"{label:16} N/A")
    lines+=['━━━━━━━━━━━━━━━━━━━━',f"📡 Data: <b>{health.get('status','UNKNOWN')}</b> | Coverage {health.get('coverage',0):.0f}%",f"🎯 Model Reliability: <b>{payload.get('model_reliability','Low')}</b>"]
    if payload.get('alerts'):
        lines+=['','⚠️ Alerts']+[f"L{a['level']} {a['type']}: {a['message']}" for a in payload['alerts'][:4]]
    lines+=['','仅用于研究观测，不构成投资建议。']
    return '\n'.join(lines)
