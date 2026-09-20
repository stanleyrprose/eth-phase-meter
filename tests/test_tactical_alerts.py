from types import SimpleNamespace

from eth_trend_v3.tactical_alerts import notification_reasons


def result(direction=-22, state="WEAK_BEAR", gate="WAIT", regime="TRANSITION"):
    return SimpleNamespace(
        final_direction=direction,
        state=state,
        execution_gate=gate,
        regime=regime,
    )


def test_crossing_direction_threshold_triggers_alert():
    previous = {
        "rule_direction": -18,
        "coverage": 98,
        "tactical_state": "NEUTRAL",
        "execution_gate": "PASS",
        "rule_regime": "TRANSITION",
    }

    reasons = notification_reasons(result(), previous)

    assert "DIRECTION_BAND: NEUTRAL→BEAR" in reasons
    assert "STATE: NEUTRAL→WEAK_BEAR" in reasons
    assert "GATE: PASS→WAIT" in reasons


def test_small_move_inside_same_state_is_silent():
    previous = {
        "rule_direction": -22,
        "coverage": 98,
        "tactical_state": "WEAK_BEAR",
        "execution_gate": "WAIT",
        "rule_regime": "TRANSITION",
    }

    assert notification_reasons(result(direction=-25), previous) == []


def test_material_direction_move_or_regime_change_triggers_alert():
    previous = {
        "rule_direction": -22,
        "coverage": 98,
        "tactical_state": "WEAK_BEAR",
        "execution_gate": "WAIT",
        "rule_regime": "TRANSITION",
    }

    reasons = notification_reasons(
        result(direction=-40, state="WEAK_BEAR", gate="WAIT", regime="TREND_DOWN"),
        previous,
    )

    assert "DIRECTION_DELTA: -22→-40" in reasons
    assert "REGIME: TRANSITION→TREND_DOWN" in reasons
