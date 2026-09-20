from types import SimpleNamespace

from eth_trend_v3.tactical_alerts import notification_reasons, render_notification_reasons


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


def test_material_bearish_move_is_classified_as_strengthening():
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

    assert "DIRECTION_STRENGTHENING: -22→-40 (-18)" in reasons
    assert "REGIME: TRANSITION→TREND_DOWN" in reasons


def test_material_bullish_fade_is_classified_as_weakening():
    previous = {
        "rule_direction": 48,
        "coverage": 98,
        "tactical_state": "WEAK_BULL",
        "execution_gate": "PASS",
        "rule_regime": "TREND_UP",
    }

    reasons = notification_reasons(
        result(direction=28, state="WEAK_BULL", gate="PASS", regime="TRANSITION"),
        previous,
    )

    assert "DIRECTION_WEAKENING: +48→+28 (-20)" in reasons
    assert "REGIME: TREND_UP→TRANSITION" in reasons


def test_material_cross_side_move_is_classified_as_reversal():
    previous = {
        "rule_direction": 25,
        "coverage": 98,
        "tactical_state": "WEAK_BULL",
        "execution_gate": "PASS",
        "rule_regime": "TRANSITION",
    }

    reasons = notification_reasons(result(direction=-25), previous)

    assert "DIRECTION_BAND: BULL→BEAR" in reasons
    assert "DIRECTION_REVERSAL: +25→-25 (-50)" in reasons


def test_trigger_renderer_turns_codes_into_readable_tactical_change():
    text = render_notification_reasons(
        [
            "DIRECTION_WEAKENING: +48→+28 (-20)",
            "REGIME: TREND_UP→TRANSITION",
        ]
    )

    assert "Tactical Change" in text
    assert "Bullish momentum weakening" in text
    assert "Direction: <b>+48 → +28 (-20)</b>" in text
    assert "Regime: <b>TREND_UP→TRANSITION</b>" in text
