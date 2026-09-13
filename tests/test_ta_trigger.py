import datetime as dt

from eth_trend_v3.ta_trigger import evaluate_tradingagents_trigger


NOW = dt.datetime(2026, 9, 13, 9, 0, tzinfo=dt.timezone.utc)


def _snapshot(direction, *, regime="Transition", momentum=30, order_flow=30, options=-10, volatility=25):
    return {
        "timestamp": "2026-09-13 08:00 UTC",
        "rule_direction": direction,
        "coverage": 98,
        "data_health": {"status": "NORMAL"},
        "model_health": {"status": "NORMAL"},
        "regime": {"regime": regime},
        "volatility_risk": volatility,
        "feature_clusters": {
            "momentum": {"score": momentum},
            "order_flow": {"score": order_flow},
            "options_positioning": {"score": options},
        },
    }


def _monitor(d1=5, d4=15, **kwargs):
    return {"1h": _snapshot(d1, **kwargs), "4h": _snapshot(d4, **kwargs)}


def _ta(generated_at="2026-09-13T08:30:00+00:00"):
    return {
        "contract_version": "tradingagents-decision-v1",
        "canonical_symbol": "ETH-USD",
        "generated_at": generated_at,
        "decision": "Hold",
        "decision_normalized": "HOLD",
    }


def _evaluate(current, previous=None, ta=None):
    return evaluate_tradingagents_trigger(
        current,
        previous_monitor=previous,
        tradingagents=ta,
        now=NOW,
    )


def test_missing_ta_contract_requires_run():
    result = _evaluate(_monitor(), previous=_monitor(), ta=None)
    assert result["action"] == "RUN"
    assert "TA_MISSING_INVALID_OR_STALE" in result["reason_codes"]


def test_stale_ta_contract_requires_run():
    result = _evaluate(_monitor(), previous=_monitor(), ta=_ta("2026-09-11T00:00:00+00:00"))
    assert result["action"] == "RUN"
    assert "TA_MISSING_INVALID_OR_STALE" in result["reason_codes"]


def test_first_local_baseline_runs_even_with_fresh_ta():
    result = _evaluate(_monitor(), previous=None, ta=_ta())
    assert result["action"] == "RUN"
    assert "NO_PREVIOUS_PHASE_BASELINE" in result["reason_codes"]


def test_stable_phase_reuses_fresh_ta_contract():
    previous = _monitor(d1=3, d4=14)
    current = _monitor(d1=5, d4=16)
    result = _evaluate(current, previous=previous, ta=_ta())
    assert result["action"] == "REUSE"
    assert result["reason_codes"] == ["NO_MATERIAL_PHASE_CHANGE"]


def test_four_hour_direction_crossing_triggers_run():
    previous = _monitor(d1=5, d4=18)
    current = _monitor(d1=8, d4=24)
    result = _evaluate(current, previous=previous, ta=_ta())
    assert result["action"] == "RUN"
    assert "4H_DIRECTION_THRESHOLD_CROSSED" in result["reason_codes"]


def test_options_block_threshold_crossing_triggers_run():
    previous = _monitor(options=-20)
    current = _monitor(options=-30)
    result = _evaluate(current, previous=previous, ta=_ta())
    assert result["action"] == "RUN"
    assert "OPTIONS_BLOCK_THRESHOLD_CROSSED" in result["reason_codes"]


def test_order_flow_sign_flip_triggers_run():
    previous = _monitor(order_flow=35)
    current = _monitor(order_flow=-40)
    result = _evaluate(current, previous=previous, ta=_ta())
    assert result["action"] == "RUN"
    assert "4H_ORDER_FLOW_SIGN_FLIP" in result["reason_codes"]


def test_bad_phase_data_defers_instead_of_spending_on_ta():
    current = _monitor()
    current["4h"]["coverage"] = 50
    result = _evaluate(current, previous=_monitor(), ta=_ta())
    assert result["action"] == "DEFER"
    assert result["reason_codes"] == ["PHASE_NOT_TRUSTWORTHY"]
