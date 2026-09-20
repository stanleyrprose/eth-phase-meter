from types import SimpleNamespace

from eth_trend_v3.notify import prd_summary, tactical_summary


def test_market_state_summary_shows_dimension_coverage():
    payload = {
        "price": 2500.0,
        "regime": {"regime": "Low-Vol Sideways"},
        "forecasts": {},
        "market_state": {
            "dimensions": {
                "trend": {"score": 26.0, "coverage": 100.0},
                "valuation": {"score": 56.0, "coverage": 33.333},
                "capital_flow": {"score": 98.0, "coverage": 25.0},
                "crowding": {"score": 25.0, "coverage": 100.0},
                "structural_supply": {"score": -4.0, "coverage": 50.0},
                "volatility_risk": {"score": 39.0, "coverage": 100.0},
            }
        },
        "data_health": {"status": "NORMAL", "coverage": 73.0},
    }

    text = prd_summary(payload)
    assert "Valuation        +56 (33% cov)" in text
    assert "Capital Flow     +98 (25% cov)" in text
    assert "Structural       -4 (50% cov)" in text


def test_tactical_summary_includes_1h_signal_and_execution_gate():
    factors = [
        SimpleNamespace(name="MA", active=True, contribution=8.0),
        SimpleNamespace(name="CVDTrend", active=True, contribution=-5.0),
        SimpleNamespace(name="RSI", active=False, contribution=0.0),
    ]
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
        factors=factors,
        execution_gate="WAIT",
        execution_reason="4h方向证据不足 (+10)",
    )

    text = tactical_summary(result)

    assert "ETH Tactical [1H]" in text
    assert "Direction: <b>+18</b>/100" in text
    assert "MA +8.0" in text
    assert "CVDTrend -5.0" in text
    assert "4H Confirmation: <b>WAIT</b>" in text
    assert "4h方向证据不足 (+10)" in text
    assert "3D/7D/30D预测仍以4H为主" in text
