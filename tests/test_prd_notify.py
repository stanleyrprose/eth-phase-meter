from eth_trend_v3.notify import prd_summary


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
