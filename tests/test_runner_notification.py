from types import SimpleNamespace

import eth_trend_v3.runner as runner


def test_send_tactical_1h_calls_telegram_with_readable_change_summary(monkeypatch):
    result = SimpleNamespace(
        timestamp="2026-09-20 23:16 UTC",
        price=2635.42,
        final_direction=28,
        available_bias=28,
        coverage=98.0,
        confidence="High",
        regime="TRANSITION",
        crowding=18,
        volatility=22,
        state="WEAK_BULL",
        factors=[
            SimpleNamespace(name="OptionSkew", active=True, contribution=6.0),
            SimpleNamespace(name="Price×OI", active=True, contribution=-10.0),
        ],
        execution_gate="PASS",
        execution_reason="4h=+56",
    )
    payload_1h = {}
    sent = []

    monkeypatch.setattr(
        runner.core,
        "send_tg_message",
        lambda message: sent.append(message) or {"status": "SENT", "http_status": 200},
    )

    status = runner._send_tactical_1h(
        result,
        payload_1h,
        triggers=[
            "DIRECTION_WEAKENING: +48→+28 (-20)",
            "REGIME: TREND_UP→TRANSITION",
        ],
    )

    assert len(sent) == 1
    assert "ETH Tactical [1H]" in sent[0]
    assert "4H Confirmation: <b>PASS</b>" in sent[0]
    assert "Tactical Change" in sent[0]
    assert "Bullish momentum weakening" in sent[0]
    assert "Direction: <b>+48 → +28 (-20)</b>" in sent[0]
    assert "Regime: <b>TREND_UP→TRANSITION</b>" in sent[0]
    assert "DIRECTION_WEAKENING:" not in sent[0]
    assert status["status"] == "SENT"
    assert payload_1h["notification"] == status


def test_tactical_change_can_notify_when_4h_state_is_missing(monkeypatch):
    result = SimpleNamespace(
        timestamp="2026-09-22 02:15 UTC",
        price=2748.2,
        final_direction=40,
        available_bias=40,
        coverage=98.0,
        confidence="High",
        regime="TREND_UP",
        crowding=30,
        volatility=25,
        state="WEAK_BULL",
        factors=[],
        execution_gate="PASS",
        execution_reason="",
    )
    previous = {
        "rule_direction": 20,
        "coverage": 98,
        "tactical_state": "WEAK_BULL",
        "execution_gate": "PASS",
        "rule_regime": "TRANSITION",
    }
    sent = []

    monkeypatch.setattr(
        runner,
        "_send_tactical_1h",
        lambda result, payload, triggers=None: sent.append(list(triggers or [])) or {"status": "SENT", "http_status": 200},
    )

    decision = runner._process_tactical_1h(result, {}, {}, previous)

    assert result.execution_gate == "WAIT"
    assert decision["reason"] == "SIGNIFICANT_CHANGE"
    assert any(item.startswith("DIRECTION_STRENGTHENING:") for item in sent[0])
    assert "GATE: PASS→WAIT" in sent[0]
