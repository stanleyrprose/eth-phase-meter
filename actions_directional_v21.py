"""Direction Model v2.1 semantics.

Final Direction is the net directional evidence on the full 100-point model.
Available-signal bias is kept separately as a diagnostic. This prevents missing
signals from being renormalized into false confidence.
"""
from __future__ import annotations

import eth_phase_meter as m
import actions_directional_v2 as v2

_BUCKETS = {
    "Technical": ({"MA", "MACD", "RSI", "KDJ", "Structure", "Trend"}, 40),
    "Derivatives": ({"Price×OI", "TakerFlow", "CVDTrend", "CVDNet"}, 25),
    "Options": ({"OptionSkew", "PutCallOI"}, 10),
    "Sentiment": ({"FearGreed", "SentTrend"}, 5),
    "Macro": ({"BTC24h", "ETHBTC", "DXY", "VIX", "Yields", "TVL7d", "News"}, 20),
}


def _bucket_stats(result):
    factors = result.get("direction_factors", []) or []
    out = {}
    for bucket, (names, nominal) in _BUCKETS.items():
        selected = [f for f in factors if f.get("factor") in names]
        active = sum(float(f.get("weight", 0)) for f in selected if f.get("value") is not None)
        contribution = sum(float(f.get("contribution", 0)) for f in selected if f.get("value") is not None)
        out[bucket] = {
            "contribution": round(contribution, 2),
            "active": round(active, 2),
            "nominal": nominal,
            "coverage": round(active / nominal * 100, 1) if nominal else 0.0,
        }
    return out


def _factor_text(result):
    factors = [f for f in (result.get("direction_factors", []) or []) if f.get("value") is not None]
    positives = sorted((f for f in factors if float(f.get("contribution", 0)) > 0), key=lambda x: float(x.get("contribution", 0)), reverse=True)[:3]
    negatives = sorted((f for f in factors if float(f.get("contribution", 0)) < 0), key=lambda x: float(x.get("contribution", 0)))[:3]

    def fmt(items):
        return ", ".join(f"{x['factor']} {float(x['contribution']):+.1f}" for x in items) if items else "无"

    return fmt(positives), fmt(negatives)


def apply():
    original_run_analysis = m.run_analysis
    original_filter = m.apply_1h_filter_by_4h

    def run_analysis(timeframe="4h", **kwargs):
        result = original_run_analysis(timeframe=timeframe)
        if not result:
            return result

        # v2 total_score is the available-only normalized score:
        # raw / active_weight * 100. Keep it as a diagnostic.
        available_bias = int(result.get("total_score", 0))

        # direction_raw is already the sum of signed contributions where the
        # complete model's nominal weights add to exactly 100. Therefore it is
        # the coverage-adjusted evidence score on a stable [-100, +100] scale.
        final_direction = int(round(float(result.get("direction_raw", 0.0))))

        result["available_signal_score"] = available_bias
        result["effective_direction_score"] = final_direction
        result["total_score"] = final_direction
        result["factor_buckets"] = _bucket_stats(result)
        result["score_semantics"] = "full-model net directional evidence; not a probability"
        result["phase"], result["strategy"] = v2.phase(
            final_direction,
            float(result.get("data_coverage", 0)),
            int(result.get("crowding_score", 0)),
            int(result.get("volatility_score", 0)),
        )
        return result

    def apply_filter(results, enabled=True):
        # Preserve market state; treat the 4h rule only as an execution gate.
        saved = {}
        for tf, r in (results or {}).items():
            if r:
                saved[tf] = (r.get("phase"), r.get("strategy"))

        out = original_filter(results, enabled=enabled)
        r1 = (out or {}).get("1h")
        if r1 and "1h" in saved:
            before_phase, before_strategy = saved["1h"]
            after_phase, after_strategy = r1.get("phase"), r1.get("strategy")
            changed = (after_phase != before_phase) or (after_strategy != before_strategy)
            if changed:
                r1["execution_gate"] = "BLOCKED"
                r1["execution_gate_reason"] = after_phase or "4h filter"
                r1["execution_instruction"] = after_strategy or "等待1h与4h同向"
                r1["gate_4h_score"] = ((out or {}).get("4h") or {}).get("total_score")
                r1["phase"], r1["strategy"] = before_phase, before_strategy
            elif enabled:
                r1["execution_gate"] = "PASS"
                r1["gate_4h_score"] = ((out or {}).get("4h") or {}).get("total_score")
        return out

    def tg(result):
        buckets = result.get("factor_buckets") or _bucket_stats(result)
        pos, neg = _factor_text(result)
        missing = [f["factor"] for f in (result.get("direction_factors", []) or []) if f.get("value") is None]

        lines = [
            f"📊 <b>ETH Direction Model v2.1 [{result['timeframe']}]</b> | {result['timestamp']}",
            "━━━━━━━━━━━━━━━━━━━━",
            f"💰 价格: <b>${result['price']:,.2f}</b>",
            f"🎯 Final Direction: <b>{result['total_score']:+d}</b> /100",
            f"🔎 Available-signal bias: <b>{result.get('available_signal_score', 0):+d}</b> /100",
            f"📡 Coverage: <b>{result['data_coverage']:.0f}%</b> | Confidence: <b>{result['confidence']}</b>",
            f"👥 Crowding: <b>{result['crowding_score']}</b>/100",
            f"🌪 Volatility: <b>{result['volatility_score']}</b>/100",
            "━━━━━━━━━━━━━━━━━━━━",
            f"⭐ 市场状态: <b>{result['phase']}</b>",
            f"⭐ 状态解释: {result['strategy']}",
        ]

        if result.get("execution_gate"):
            gate = result["execution_gate"]
            score4 = result.get("gate_4h_score")
            score4_txt = f" | 4h={score4:+d}" if isinstance(score4, int) else ""
            lines.append(f"🚦 Execution Gate: <b>{gate}</b>{score4_txt}")
            if result.get("execution_instruction"):
                lines.append(f"   {result['execution_instruction']}")

        lines += [
            "",
            "方向证据分桶:",
        ]
        labels = {
            "Technical": "技术",
            "Derivatives": "衍生品",
            "Options": "期权",
            "Sentiment": "情绪",
            "Macro": "宏观",
        }
        for key in ("Technical", "Derivatives", "Options", "Sentiment", "Macro"):
            b = buckets[key]
            lines.append(
                f"  {labels[key]}: {b['contribution']:+.1f} | 可用权重 {b['active']:.0f}/{b['nominal']} ({b['coverage']:.0f}%)"
            )

        lines += [
            "",
            f"⬆️ 主要偏多因子: {pos}",
            f"⬇️ 主要偏空因子: {neg}",
            "",
            f"数学含义: 全模型净贡献 {float(result.get('direction_raw', 0)):+.1f}/100 → Final {result['total_score']:+d}",
            f"可用信号内部: {float(result.get('direction_raw', 0)):+.1f}/{float(result.get('direction_active_max', 0)):.0f}×100 → {result.get('available_signal_score', 0):+d}",
            "注: Final Direction 是方向证据强度，不是上涨概率。",
        ]
        if missing:
            lines.append("⚠️ 缺失方向因子: " + ", ".join(missing))
        return "\n".join(lines)

    m.run_analysis = run_analysis
    m.apply_1h_filter_by_4h = apply_filter
    m.format_tg_summary = tg
