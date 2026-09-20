from __future__ import annotations


DIRECTION_THRESHOLD = 20
MATERIAL_DIRECTION_DELTA = 15


def _direction_band(direction: int) -> str:
    if direction >= DIRECTION_THRESHOLD:
        return "BULL"
    if direction <= -DIRECTION_THRESHOLD:
        return "BEAR"
    return "NEUTRAL"


def _state_from_payload(payload: dict) -> str | None:
    explicit = payload.get("tactical_state")
    if explicit:
        return str(explicit)
    direction = payload.get("rule_direction")
    coverage = payload.get("coverage")
    if direction is None or coverage is None:
        return None
    try:
        direction = int(direction)
        coverage = float(coverage)
    except (TypeError, ValueError):
        return None
    if coverage < 50:
        return "DATA_INSUFFICIENT"
    if direction >= 60:
        return "STRONG_BULL"
    if direction >= 20:
        return "WEAK_BULL"
    if direction <= -60:
        return "STRONG_BEAR"
    if direction <= -20:
        return "WEAK_BEAR"
    return "NEUTRAL"


def _rule_regime_from_payload(payload: dict) -> str | None:
    explicit = payload.get("rule_regime")
    if explicit:
        return str(explicit)
    regime = payload.get("regime")
    if isinstance(regime, dict):
        value = regime.get("regime")
        return str(value) if value else None
    return None


def notification_reasons(result, previous: dict) -> list[str]:
    if not previous:
        return []

    reasons: list[str] = []
    previous_direction = previous.get("rule_direction")
    try:
        previous_direction = int(previous_direction) if previous_direction is not None else None
    except (TypeError, ValueError):
        previous_direction = None

    if previous_direction is not None:
        old_band = _direction_band(previous_direction)
        new_band = _direction_band(result.final_direction)
        if old_band != new_band:
            reasons.append(f"DIRECTION_BAND: {old_band}→{new_band}")
        if abs(result.final_direction) >= DIRECTION_THRESHOLD and abs(result.final_direction - previous_direction) >= MATERIAL_DIRECTION_DELTA:
            reasons.append(f"DIRECTION_DELTA: {previous_direction:+d}→{result.final_direction:+d}")

    previous_state = _state_from_payload(previous)
    if previous_state and previous_state != result.state:
        reasons.append(f"STATE: {previous_state}→{result.state}")

    previous_gate = previous.get("execution_gate")
    if previous_gate and previous_gate != result.execution_gate:
        reasons.append(f"GATE: {previous_gate}→{result.execution_gate}")

    previous_regime = _rule_regime_from_payload(previous)
    if previous_regime and previous_regime != result.regime:
        reasons.append(f"REGIME: {previous_regime}→{result.regime}")

    return reasons
