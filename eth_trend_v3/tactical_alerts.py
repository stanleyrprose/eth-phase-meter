from __future__ import annotations

import re


DIRECTION_THRESHOLD = 20
MATERIAL_DIRECTION_DELTA = 15


def _direction_band(direction: int) -> str:
    if direction >= DIRECTION_THRESHOLD:
        return "BULL"
    if direction <= -DIRECTION_THRESHOLD:
        return "BEAR"
    return "NEUTRAL"


def _direction_change_kind(previous: int, current: int) -> str:
    old_band = _direction_band(previous)
    new_band = _direction_band(current)

    if {old_band, new_band} == {"BULL", "BEAR"}:
        return "REVERSAL"
    if old_band == "NEUTRAL" and new_band in {"BULL", "BEAR"}:
        return "STRENGTHENING"
    if old_band in {"BULL", "BEAR"} and new_band == "NEUTRAL":
        return "WEAKENING"
    if previous * current < 0:
        return "REVERSAL"
    if abs(current) > abs(previous):
        return "STRENGTHENING"
    return "WEAKENING"


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
        if (
            abs(result.final_direction) >= DIRECTION_THRESHOLD
            and abs(result.final_direction - previous_direction) >= MATERIAL_DIRECTION_DELTA
        ):
            kind = _direction_change_kind(previous_direction, result.final_direction)
            delta = result.final_direction - previous_direction
            reasons.append(
                f"DIRECTION_{kind}: {previous_direction:+d}→{result.final_direction:+d} ({delta:+d})"
            )

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


_DIRECTION_RE = re.compile(
    r"^DIRECTION_(STRENGTHENING|WEAKENING|REVERSAL): ([+-]\d+)→([+-]\d+) \(([+-]\d+)\)$"
)


def render_notification_reasons(reasons: list[str]) -> str:
    lines = ["🔔 <b>Tactical Change</b>"]

    for reason in reasons:
        match = _DIRECTION_RE.match(reason)
        if match:
            kind, old_text, new_text, delta_text = match.groups()
            new_value = int(new_text)
            side = "Bullish" if new_value > 0 else "Bearish" if new_value < 0 else "Directional"
            if kind == "STRENGTHENING":
                lines.append(f"🚀 <b>{side} momentum strengthening</b>")
            elif kind == "WEAKENING":
                lines.append(f"⚠️ <b>{side} momentum weakening</b>")
            else:
                lines.append("🔄 <b>Directional reversal</b>")
            lines.append(f"Direction: <b>{old_text} → {new_text} ({delta_text})</b>")
            continue

        if reason.startswith("REGIME: "):
            lines.append(f"🧭 Regime: <b>{reason.removeprefix('REGIME: ')}</b>")
        elif reason.startswith("GATE: "):
            lines.append(f"🚦 Gate: <b>{reason.removeprefix('GATE: ')}</b>")
        elif reason.startswith("STATE: "):
            lines.append(f"⭐ State: <b>{reason.removeprefix('STATE: ')}</b>")
        elif reason.startswith("DIRECTION_BAND: "):
            lines.append(f"🎯 Direction band: <b>{reason.removeprefix('DIRECTION_BAND: ')}</b>")
        else:
            lines.append(f"• {reason}")

    return "\n".join(lines)
