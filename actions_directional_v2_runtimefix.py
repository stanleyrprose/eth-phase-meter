import eth_phase_meter as m
import actions_directional_v2 as v2


def run_analysis(timeframe='4h'):
    return v2.run_analysis(timeframe)


def main():
    results={'4h':m.run_single('4h',send=False),'1h':m.run_single('1h',send=False)}
    enabled=m.os.environ.get('ETH_FILTER_1H_BY_4H','1').strip() not in ('0','false','False')
    results=m.apply_1h_filter_by_4h(results,enabled=enabled)
    for tf in ('4h','1h'):
        r=results.get(tf)
        if not r: continue
        if m.TG_BOT_TOKEN and m.TG_CHAT_ID:
            m.send_tg_message(m.format_tg_summary(r))
            if r.get('_detail_path'):
                m.send_tg_file(r['_detail_path'],caption=f"ETH Direction v2 [{tf}] | {r['timestamp']}")
    res=m.compute_resonance(results)
    if res:
        msg=(f"🧩 多周期共振(v2): {res['resonance']}\n"
             f"- Direction: 1h={res['d1_1h']:+d} | 4h={res['d1_4h']:+d}\n"
             f"- 结论: {res['note']}\n- 过滤开关: {'ON' if enabled else 'OFF'}")
        print(msg)
        if m.TG_BOT_TOKEN and m.TG_CHAT_ID: m.send_tg_message(msg)
    return results


def apply():
    m.PHASES=[
        (70,100,'🟢 强多趋势','回调/确认后做多优先'),
        (30,69,'🟢 偏多','偏多，回调做多优先'),
        (-29,29,'🟡 方向中性','无明确方向优势，结合波动率/拥挤度'),
        (-69,-30,'🔴 偏空','反弹减仓或轻仓做空'),
        (-100,-70,'🔴 强空趋势','反弹做空/降低多头敞口优先'),
    ]
    m.run_analysis=run_analysis
    m.main=main
