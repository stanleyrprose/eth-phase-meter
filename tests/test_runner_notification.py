from types import SimpleNamespace

import eth_trend_v3.runner as runner


def test_send_tactical_1h_calls_telegram_and_records_compatibility_evidence(monkeypatch):
    result = SimpleNamespace(
        timestamp="2026-09-20 12:00 UTC",
        price=3200.0,
        final_direction=18,
        available_bias=24,
        coverage=75.0,
        confidence="Medium",
        regime="TRANSITION",
        crowding=42,
        volatility=37,
        state="NEUTRAL",
        factors=[
            SimpleNamespace(name="MA", active=True, contribution=8.0),
            SimpleNamespace(name="CVDTrend", active=True, contribution=-5.0),
        ],
        execution_gate="WAIT",
        execution_reason="4h方向证据不足 (+10)",
    )
    payload_1h = {}
    sent = []

    monkeypatch.setattr(
        runner.core,
        "send_tg_message",
        lambda message: sent.append(message) or {"status": "SENT", "http_status": 200},
    )

    status = runner._send_tactical_1h(result, payload_1h, triggers=["STATE: NEUTRAL→WEAK_BULL"])

    assert len(sent) == 1
    assert "ETH Tactical [1H]" in sent[0]
    assert "4H Confirmation: <b>WAIT</b>" in sent[0]
    assert status["status"] == "SENT"
    assert "Trigger: STATE: NEUTRAL→WEAK_BULL" in sent[0]
    assert payload_1h["notification"] == status
