def telegram_text(r):
    fam=r.quality['families']; missing=[f.name for f in r.factors if not f.active]; pos=sorted((f for f in r.factors if f.active and f.contribution>0),key=lambda x:x.contribution,reverse=True)[:3]; neg=sorted((f for f in r.factors if f.active and f.contribution<0),key=lambda x:x.contribution)[:3]; fmt=lambda xs:', '.join(f'{x.name} {x.contribution:+.1f}' for x in xs) if xs else '无'
    lines=[f'📊 <b>ETH Trend Engine v3 [{r.timeframe}]</b> | {r.timestamp}','━━━━━━━━━━━━━━━━━━━━',f'💰 Price: <b>${r.price:,.2f}</b>',f'🎯 Final Direction: <b>{r.final_direction:+d}</b>/100',f'🔎 Available bias: <b>{r.available_bias:+d}</b>/100',f'📡 Coverage: <b>{r.coverage:.0f}%</b> | Confidence: <b>{r.confidence}</b>',f'🧭 Regime: <b>{r.regime}</b>',f'👥 Crowding: <b>{r.crowding}</b>/100',f'🌪 Volatility: <b>{r.volatility}</b>/100','━━━━━━━━━━━━━━━━━━━━',f'⭐ State: <b>{r.state}</b>',f'📝 {r.state_explanation}','','方向证据分桶:']
    labels={'Technical':'技术','Derivatives':'衍生品','Options':'期权','Sentiment':'情绪','Macro':'宏观'}
    for key in ('Technical','Derivatives','Options','Sentiment','Macro'):
        x=fam[key]; lines.append(f"  {labels[key]}: {x['contribution']:+.1f} | {x['active']:.0f}/{x['nominal']:.0f} ({x['coverage']:.0f}%)")
    lines+=['',f'⬆️ 主要偏多: {fmt(pos)}',f'⬇️ 主要偏空: {fmt(neg)}',f'数学含义: 全100权重净方向证据 = {r.final_direction:+d}',f'可用信号内部偏向 = {r.available_bias:+d}；Coverage={r.coverage:.0f}%','注：Direction不是上涨概率。']
    if missing: lines.append('⚠️ 缺失因子: '+', '.join(missing))
    return '\n'.join(lines)
