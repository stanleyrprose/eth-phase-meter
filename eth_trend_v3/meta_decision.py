from __future__ import annotations

import datetime as dt
from typing import Any


META_CONTRACT_VERSION = "eth-meta-decision-v1"
TRADINGAGENTS_CONTRACT_VERSION = "tradingagents-decision-v1"

_BUY_DECISIONS = {"BUY", "STRONG BUY", "ADD", "ACCUMULATE"}
_SELL_DECISIONS = {"SELL", "STRONG SELL", "REDUCE", "EXIT"}
_HOLD_DECISIONS = {"HOLD", "WAIT", "NEUTRAL"}
_KNOWN_DECISIONS = _BUY_DECISIONS | _SELL_DECISIONS | _HOLD_DECISIONS


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _cluster_score(snapshot: dict[str, Any], name: str) -> float:
    cluster = ((snapshot.get("feature_clusters") or {}).get(name) or {})
    return _number(cluster.get("score"))


def _health_ok(snapshot: dict[str, Any], *, minimum_coverage: float) -> bool:
    health = snapshot.get("data_health") or {}
    model_health = snapshot.get("model_health") or {}
    coverage = _number(snapshot.get("coverage"))
    if coverage < minimum_coverage:
        return False
    if str(health.get("status") or "UNKNOWN").upper() != "NORMAL":
        return False
    if str(model_health.get("status") or "NORMAL").upper() == "MODEL_UNRELIABLE":
        return False
    return True


def _normalize_tradingagents_decision(payload: dict[str, Any]) -> str:
    raw = payload.get("decision_normalized") or payload.get("decision") or ""
    return str(raw).strip().upper().replace("_", " ")


def _decision_side(decision: str) -> int:
    if decision in _BUY_DECISIONS:
        return 1
    if decision in _SELL_DECISIONS:
        return -1
    return 0


def _parse_timestamp(value: Any) -> dt.datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith(" UTC"):
        try:
            return dt.datetime.strptime(text, "%Y-%m-%d %H:%M UTC").replace(tzinfo=dt.timezone.utc)
        except ValueError:
            return None
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _is_fresh(
    value: Any,
    *,
    now: dt.datetime,
    max_age_hours: float,
    future_skew_seconds: float = 300.0,
) -> bool:
    timestamp = _parse_timestamp(value)
    if timestamp is None:
        return False
    age_seconds = (now - timestamp).total_seconds()
    return -future_skew_seconds <= age_seconds <= max_age_hours * 3600


def evaluate_meta_decision(
    monitor: dict[str, Any],
    tradingagents: dict[str, Any],
    *,
    minimum_coverage: float = 80.0,
    max_source_age_hours: float = 24.0,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Combine TradingAgents judgment with Phase Meter state without inventing probabilities.

    This layer is deterministic decision support. It does not alter model promotion,
    calibrated forecasts, execution gates, or order execution.
    """

    current_time = now or dt.datetime.now(dt.timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=dt.timezone.utc)
    current_time = current_time.astimezone(dt.timezone.utc)

    one_hour = monitor.get("1h") or {}
    four_hour = monitor.get("4h") or {}
    d1 = _number(one_hour.get("rule_direction"))
    d4 = _number(four_hour.get("rule_direction"))
    momentum4 = _cluster_score(four_hour, "momentum")
    order_flow4 = _cluster_score(four_hour, "order_flow")
    options4 = _cluster_score(four_hour, "options_positioning")
    volatility4 = _number(four_hour.get("volatility_risk"))
    ta_decision = _normalize_tradingagents_decision(tradingagents)
    ta_side = _decision_side(ta_decision)

    reasons: list[str] = []
    recommendation = "HOLD"

    contract_ok = tradingagents.get("contract_version") == TRADINGAGENTS_CONTRACT_VERSION
    decision_known = ta_decision in _KNOWN_DECISIONS
    symbol = str(tradingagents.get("canonical_symbol") or "").upper()
    symbol_ok = symbol in {"ETH-USD", "ETHUSD", "ETHUSDT"}
    phase_health_ok = _health_ok(one_hour, minimum_coverage=minimum_coverage) and _health_ok(
        four_hour, minimum_coverage=minimum_coverage
    )
    tradingagents_fresh = _is_fresh(
        tradingagents.get("generated_at"),
        now=current_time,
        max_age_hours=max_source_age_hours,
    )
    phase_fresh = _is_fresh(
        one_hour.get("timestamp"),
        now=current_time,
        max_age_hours=max_source_age_hours,
    ) and _is_fresh(
        four_hour.get("timestamp"),
        now=current_time,
        max_age_hours=max_source_age_hours,
    )

    strong_phase_conflict = d1 * d4 < 0 and abs(d1) >= 20 and abs(d4) >= 20
    cross_system_conflict = (ta_side > 0 and d4 <= -20) or (ta_side < 0 and d4 >= 20)
    extreme_risk = volatility4 >= 75

    if not contract_ok:
        recommendation = "AVOID"
        reasons.append("TRADINGAGENTS_CONTRACT_INVALID")
    if not decision_known:
        recommendation = "AVOID"
        reasons.append("TRADINGAGENTS_DECISION_UNKNOWN")
    if not symbol_ok:
        recommendation = "AVOID"
        reasons.append("ASSET_MISMATCH")
    if not tradingagents_fresh:
        recommendation = "AVOID"
        reasons.append("TRADINGAGENTS_STALE_OR_TIMESTAMP_INVALID")
    if not phase_health_ok:
        recommendation = "AVOID"
        reasons.append("PHASE_DATA_GATED")
    if not phase_fresh:
        recommendation = "AVOID"
        reasons.append("PHASE_DATA_STALE_OR_TIMESTAMP_INVALID")
    if extreme_risk:
        recommendation = "AVOID"
        reasons.append("EXTREME_VOLATILITY_RISK")
    if strong_phase_conflict:
        recommendation = "AVOID"
        reasons.append("1H_4H_STRONG_CONFLICT")
    if cross_system_conflict:
        recommendation = "AVOID"
        reasons.append("CROSS_SYSTEM_CONFLICT")

    gated = recommendation == "AVOID"

    if not gated:
        add_confirmed = (
            ta_side > 0
            and d4 >= 25
            and d1 >= 15
            and momentum4 >= 20
            and order_flow4 > 0
            and options4 >= -25
        )
        reduce_confirmed = (
            ta_side < 0
            and d4 <= -20
            and d1 <= -10
            and (momentum4 <= 0 or order_flow4 <= 0)
        )

        if add_confirmed:
            recommendation = "ADD"
            reasons.extend(
                [
                    "TRADINGAGENTS_BUY",
                    "4H_BULL_CONFIRMATION",
                    "1H_BULL_CONFIRMATION",
                    "MOMENTUM_CONFIRMED",
                    "ORDER_FLOW_CONFIRMED",
                    "OPTIONS_NOT_BLOCKING",
                ]
            )
        elif reduce_confirmed:
            recommendation = "REDUCE"
            reasons.extend(
                [
                    "TRADINGAGENTS_SELL",
                    "4H_BEAR_CONFIRMATION",
                    "1H_BEAR_CONFIRMATION",
                    "MOMENTUM_OR_FLOW_DETERIORATION",
                ]
            )
        else:
            recommendation = "HOLD"
            if ta_side == 0 and d4 > 0:
                reasons.append("CONSTRUCTIVE_BUT_UNCONFIRMED")
            elif ta_side == 0 and d4 < 0:
                reasons.append("BEARISH_BUT_UNCONFIRMED")
            elif ta_side > 0:
                reasons.append("BUY_SIGNAL_LACKS_MULTI_TIMEFRAME_CONFIRMATION")
            elif ta_side < 0:
                reasons.append("SELL_SIGNAL_LACKS_MULTI_TIMEFRAME_CONFIRMATION")
            else:
                reasons.append("NO_CROSS_SYSTEM_EDGE")

    if recommendation in {"ADD", "REDUCE"}:
        alignment = "HIGH"
    elif recommendation == "HOLD" and not cross_system_conflict and not strong_phase_conflict:
        alignment = "MEDIUM"
    else:
        alignment = "LOW"

    return {
        "contract_version": META_CONTRACT_VERSION,
        "generated_at": current_time.isoformat(),
        "asset": "ETH-USD",
        "recommendation": recommendation,
        "evidence_alignment": alignment,
        "reason_codes": reasons,
        "sources": {
            "tradingagents": {
                "contract_version": tradingagents.get("contract_version"),
                "analysis_date": tradingagents.get("analysis_date"),
                "generated_at": tradingagents.get("generated_at"),
                "fresh": tradingagents_fresh,
                "decision": ta_decision,
                "report_path": tradingagents.get("report_path"),
            },
            "phase_meter": {
                "fresh": phase_fresh,
                "1h": {
                    "timestamp": one_hour.get("timestamp"),
                    "direction": d1,
                    "coverage": _number(one_hour.get("coverage")),
                    "regime": (one_hour.get("regime") or {}).get("regime"),
                },
                "4h": {
                    "timestamp": four_hour.get("timestamp"),
                    "direction": d4,
                    "coverage": _number(four_hour.get("coverage")),
                    "regime": (four_hour.get("regime") or {}).get("regime"),
                    "momentum": momentum4,
                    "order_flow": order_flow4,
                    "options_positioning": options4,
                    "volatility_risk": volatility4,
                },
            },
        },
        "guardrails": {
            "forecast_probability_generated": False,
            "production_model_state_changed": False,
            "order_execution_allowed": False,
            "note": "Decision support only; Direction and evidence alignment are not probabilities.",
        },
    }
