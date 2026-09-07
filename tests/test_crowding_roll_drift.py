from datetime import datetime
from types import SimpleNamespace

import eth_phase_meter as core
from eth_trend_v3.engine import crowding as crowding_score
from eth_trend_v3.market_state import build_market_state


def test_short_dated_option_expiries_are_excluded_from_crowding_skew():
    now = datetime(2026, 9, 7, 14, 0)
    expiries = [
        (datetime(2026, 9, 8, 0, 0), "8SEP26"),
        (datetime(2026, 9, 9, 0, 0), "9SEP26"),
        (datetime(2026, 9, 10, 0, 0), "10SEP26"),
        (datetime(2026, 9, 11, 0, 0), "11SEP26"),
    ]

    stable = core._select_stable_option_expiries(expiries, now)

    assert [expiry for _, expiry in stable] == ["10SEP26", "11SEP26"]
    assert stable[0][0] == datetime(2026, 9, 10, 8, 0)


def test_crowding_uses_stable_skew_not_legacy_nearest_expiry_skew():
    raw = {
        "candles": None,
        "derivatives": {},
        "options": {
            "put_call_oi_ratio": 0.8,
            "iv_skew_25d_proxy_near": -14.71,
            "crowding_iv_skew_proxy": -0.04,
        },
        "sentiment": {},
    }

    assert crowding_score(raw) == 0


def test_crowding_coverage_reflects_partial_derivatives_fallback():
    raw = {
        "candles": None,
        "derivatives": {"funding_rate": 4e-6},
        "options": {"put_call_oi_ratio": 0.55, "crowding_iv_skew_proxy": -0.04},
        "sentiment": {"fng_value": 71},
        "valuation": {},
        "capital_flow": {},
        "structural": {},
    }
    result = SimpleNamespace(
        quality={"families": {"Technical": {"nominal": 40, "active": 0, "coverage": 0, "contribution": 0}}},
        crowding=5,
        volatility=22,
    )

    state = build_market_state(raw, result)
    crowding = state["dimensions"]["crowding"]

    assert crowding["coverage"] == 60.0
    assert state["dimension_versions"]["crowding"] == "crowding-v2-dte48"
