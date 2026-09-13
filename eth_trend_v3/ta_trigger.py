from __future__ import annotations

import datetime as dt
from typing import Any


TRIGGER_CONTRACT_VERSION = "eth-tradingagents-trigger-v1"
TRADINGAGENTS_CONTRACT_VERSION = "tradingagents-decision-v1"


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _cluster(snapshot: dict[str, Any], name: str) -> float:
    return _number(((snapshot.get("feature_clusters") or {}).get(name) or {}).get("score"))


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


def _fresh(value: Any, *, now: dt.datetime, max_age_hours: float) -> bool:
    timestamp = _parse_timestamp(value)
    if timestamp is None:
        return False
    age = (now - timestamp).total_seconds()
    return -300 <= age <= max_age_hours * 3600


def _phase_usable(
    monitor: dict[str, Any],
    *,
    now: dt.datetime,
    minimum_coverage: float,
    max_age_hours: float,
) -> bool:
    for timeframe in ("1h", "4h"):
        snapshot = monitor.get(timeframe) or {}
        health = snapshot.get("data_health") or {}
        model_health = snapshot.get("model_health") or {}
        if _number(snapshot.get("coverage")) < minimum_coverage:
            return False
        if str(health.get("status") or "UNKNOWN").upper() != "NORMAL":
            return False
        if str(model_health.get("status") or "NORMAL").upper() == "MODEL_UNRELIABLE":
            return False
        if not _fresh(snapshot.get("timestamp"), now=now, max_age_hours=max_age_hours):
            return False
    return True


def _ta_fresh(contract: dict[str, Any] | None, *, now: dt.datetime, max_age_hours: float) -> bool:
    contract = contract or {}
    if contract.get("contract_version") != TRADINGAGENTS_CONTRACT_VERSION:
        return False
    if str(contract.get("canonical_symbol") or "").upper() not in {"ETH-USD", "ETHUSD", "ETHUSDT"}:
        return False
    return _fresh(contract.get("generated_at"), now=now, max_age_hours=max_age_hours)


def _crossed(value: float, previous: float, threshold: float) -> bool:
    return (previous < threshold <= value) or (previous > threshold >= value)


def evaluate_tradingagents_trigger(
    monitor: dict[str, Any],
    *,
    previous_monitor: dict[str, Any] | None = None,
    tradingagents: dict[str, Any] | None = None,
    now: dt.datetime | None = None,
    minimum_coverage: float = 80.0,
    phase_max_age_hours: float = 8.0,
    ta_max_age_hours: float = 24.0,
) -> dict[str, Any]:
    """Decide whether a costly TradingAgents run is justified by new Phase Meter evidence.

    RUN means execute TradingAgents now. REUSE means keep the latest still-fresh
    TradingAgents contract. DEFER means Phase Meter itself is not trustworthy enough
    to justify a new multi-agent run.
    """
    current_time = now or dt.datetime.now(dt.timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=dt.timezone.utc)
    current_time = current_time.astimezone(dt.timezone.utc)

    one = monitor.get("1h") or {}
    four = monitor.get("4h") or {}
    phase_usable = _phase_usable(
        monitor,
        now=current_time,
        minimum_coverage=minimum_coverage,
        max_age_hours=phase_max_age_hours,
    )

    reasons: list[str] = []
    action = "REUSE"

    if not phase_usable:
        action = "DEFER"
        reasons.append("PHASE_NOT_TRUSTWORTHY")
    elif not _ta_fresh(tradingagents, now=current_time, max_age_hours=ta_max_age_hours):
        action = "RUN"
        reasons.append("TA_MISSING_INVALID_OR_STALE")
    elif not previous_monitor:
        action = "RUN"
        reasons.append("NO_PREVIOUS_PHASE_BASELINE")
    else:
        previous_one = previous_monitor.get("1h") or {}
        previous_four = previous_monitor.get("4h") or {}

        d1 = _number(one.get("rule_direction"))
        d4 = _number(four.get("rule_direction"))
        prev_d1 = _number(previous_one.get("rule_direction"))
        prev_d4 = _number(previous_four.get("rule_direction"))
        momentum = _cluster(four, "momentum")
        prev_momentum = _cluster(previous_four, "momentum")
        order_flow = _cluster(four, "order_flow")
        prev_order_flow = _cluster(previous_four, "order_flow")
        options = _cluster(four, "options_positioning")
        prev_options = _cluster(previous_four, "options_positioning")
        volatility = _number(four.get("volatility_risk"))
        prev_volatility = _number(previous_four.get("volatility_risk"))
        regime = str((four.get("regime") or {}).get("regime") or "UNKNOWN")
        prev_regime = str((previous_four.get("regime") or {}).get("regime") or "UNKNOWN")

        if regime != prev_regime:
            reasons.append("4H_REGIME_CHANGED")
        if _crossed(d4, prev_d4, 20) or _crossed(d4, prev_d4, -20):
            reasons.append("4H_DIRECTION_THRESHOLD_CROSSED")
        if abs(d4 - prev_d4) >= 15:
            reasons.append("4H_DIRECTION_MOVED_15")
        if _crossed(d1, prev_d1, 15) or _crossed(d1, prev_d1, -15):
            reasons.append("1H_CONFIRMATION_THRESHOLD_CROSSED")
        if momentum * prev_momentum < 0 and abs(momentum) >= 20:
            reasons.append("4H_MOMENTUM_SIGN_FLIP")
        if order_flow * prev_order_flow < 0 and abs(order_flow) >= 25:
            reasons.append("4H_ORDER_FLOW_SIGN_FLIP")
        if _crossed(options, prev_options, -25):
            reasons.append("OPTIONS_BLOCK_THRESHOLD_CROSSED")
        if _crossed(volatility, prev_volatility, 60) or abs(volatility - prev_volatility) >= 20:
            reasons.append("VOLATILITY_STATE_CHANGED")

        if reasons:
            action = "RUN"
        else:
            action = "REUSE"
            reasons.append("NO_MATERIAL_PHASE_CHANGE")

    return {
        "contract_version": TRIGGER_CONTRACT_VERSION,
        "generated_at": current_time.isoformat(),
        "asset": "ETH-USD",
        "action": action,
        "reason_codes": reasons,
        "source": {
            "phase_usable": phase_usable,
            "phase_1h_timestamp": one.get("timestamp"),
            "phase_4h_timestamp": four.get("timestamp"),
            "phase_1h_direction": _number(one.get("rule_direction")),
            "phase_4h_direction": _number(four.get("rule_direction")),
            "phase_4h_regime": (four.get("regime") or {}).get("regime"),
            "ta_contract_fresh": _ta_fresh(tradingagents, now=current_time, max_age_hours=ta_max_age_hours),
            "ta_generated_at": (tradingagents or {}).get("generated_at"),
        },
        "guardrails": {
            "runs_tradingagents_only": action == "RUN",
            "places_orders": False,
            "changes_forecast_model_state": False,
        },
    }
