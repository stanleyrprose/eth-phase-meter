import datetime as dt

from eth_trend_v3.meta_decision import evaluate_meta_decision


_NOW = dt.datetime(2026, 9, 13, 2, 0, tzinfo=dt.timezone.utc)


def _snapshot(
    direction,
    *,
    momentum=0,
    order_flow=0,
    options=0,
    coverage=98,
    health="NORMAL",
    model_health="NORMAL",
    volatility=20,
    timestamp="2026-09-13 01:00 UTC",
):
    return {
        "timestamp": timestamp,
        "rule_direction": direction,
        "coverage": coverage,
        "feature_clusters": {
            "momentum": {"score": momentum},
            "order_flow": {"score": order_flow},
            "options_positioning": {"score": options},
        },
        "data_health": {"status": health},
        "model_health": {"status": model_health},
        "volatility_risk": volatility,
        "regime": {"regime": "Transition"},
    }


def _ta(decision="HOLD", symbol="ETH-USD", generated_at="2026-09-13T01:00:00+00:00"):
    return {
        "contract_version": "tradingagents-decision-v1",
        "canonical_symbol": symbol,
        "analysis_date": "2026-09-13",
        "generated_at": generated_at,
        "decision": decision,
        "decision_normalized": decision.upper(),
        "report_path": "/tmp/complete_report.md",
    }


def _kronos(score4=30.0):
    return {
        "contract_version": "kronos-evidence-v1",
        "generated_at": "2026-09-13T01:00:00+00:00",
        "asset": "ETH-USD",
        "mode": "SHADOW",
        "model": {"name": "Kronos-small"},
        "horizons": {
            "1h": {
                "direction_score": 20.0,
                "median_terminal_return_pct": 1.0,
                "sample_count": 3,
                "pred_len": 12,
                "lookback": 160,
            },
            "4h": {
                "direction_score": score4,
                "median_terminal_return_pct": 2.0 if score4 >= 0 else -2.0,
                "sample_count": 3,
                "pred_len": 18,
                "lookback": 120,
            },
        },
    }


def _evaluate(monitor, tradingagents, kronos=None):
    return evaluate_meta_decision(monitor, tradingagents, kronos, now=_NOW)


def test_current_like_state_stays_hold_without_inventing_probability():
    monitor = {
        "1h": _snapshot(1, momentum=-2.4, order_flow=-1.2, options=-21),
        "4h": _snapshot(22, momentum=55.2, order_flow=59.4, options=-21, volatility=25),
    }
    result = _evaluate(monitor, _ta("HOLD"))
    assert result["recommendation"] == "HOLD"
    assert result["evidence_alignment"] == "MEDIUM"
    assert "CONSTRUCTIVE_BUT_UNCONFIRMED" in result["reason_codes"]
    assert result["guardrails"]["forecast_probability_generated"] is False
    assert "probability_up" not in result


def test_add_requires_cross_system_and_multitimeframe_confirmation():
    monitor = {
        "1h": _snapshot(22, momentum=35, order_flow=20, options=-10),
        "4h": _snapshot(35, momentum=60, order_flow=45, options=-10),
    }
    result = _evaluate(monitor, _ta("BUY"))
    assert result["recommendation"] == "ADD"
    assert result["evidence_alignment"] == "HIGH"
    assert "4H_BULL_CONFIRMATION" in result["reason_codes"]
    assert "1H_BULL_CONFIRMATION" in result["reason_codes"]


def test_reduce_requires_confirmed_bearish_deterioration():
    monitor = {
        "1h": _snapshot(-18, momentum=-20, order_flow=-10, options=15),
        "4h": _snapshot(-32, momentum=-30, order_flow=-25, options=20),
    }
    result = _evaluate(monitor, _ta("SELL"))
    assert result["recommendation"] == "REDUCE"
    assert result["evidence_alignment"] == "HIGH"
    assert "MOMENTUM_OR_FLOW_DETERIORATION" in result["reason_codes"]


def test_cross_system_conflict_fails_closed_to_avoid():
    monitor = {
        "1h": _snapshot(-25, momentum=-30, order_flow=-20),
        "4h": _snapshot(-30, momentum=-40, order_flow=-30),
    }
    result = _evaluate(monitor, _ta("BUY"))
    assert result["recommendation"] == "AVOID"
    assert result["evidence_alignment"] == "LOW"
    assert "CROSS_SYSTEM_CONFLICT" in result["reason_codes"]


def test_bad_phase_data_fails_closed_to_avoid():
    monitor = {
        "1h": _snapshot(20, coverage=60),
        "4h": _snapshot(30),
    }
    result = _evaluate(monitor, _ta("BUY"))
    assert result["recommendation"] == "AVOID"
    assert "PHASE_DATA_GATED" in result["reason_codes"]


def test_asset_mismatch_fails_closed_to_avoid():
    monitor = {
        "1h": _snapshot(20),
        "4h": _snapshot(30),
    }
    result = _evaluate(monitor, _ta("BUY", symbol="BTC-USD"))
    assert result["recommendation"] == "AVOID"
    assert "ASSET_MISMATCH" in result["reason_codes"]


def test_stale_tradingagents_contract_fails_closed_to_avoid():
    monitor = {
        "1h": _snapshot(20),
        "4h": _snapshot(30),
    }
    result = _evaluate(monitor, _ta("BUY", generated_at="2026-09-11T00:00:00+00:00"))
    assert result["recommendation"] == "AVOID"
    assert "TRADINGAGENTS_STALE_OR_TIMESTAMP_INVALID" in result["reason_codes"]


def test_unknown_tradingagents_decision_fails_closed_to_avoid():
    monitor = {
        "1h": _snapshot(20),
        "4h": _snapshot(30),
    }
    result = _evaluate(monitor, _ta("WATCH"))
    assert result["recommendation"] == "AVOID"
    assert "TRADINGAGENTS_DECISION_UNKNOWN" in result["reason_codes"]


def test_kronos_shadow_support_is_visible_but_does_not_promote_hold():
    monitor = {
        "1h": _snapshot(25, momentum=35, order_flow=25),
        "4h": _snapshot(38, momentum=45, order_flow=50),
    }
    result = _evaluate(monitor, _ta("HOLD"), _kronos(score4=40))
    assert result["recommendation"] == "HOLD"
    assert result["shadow_evidence"]["kronos_alignment"] == "SUPPORTS"
    assert result["shadow_evidence"]["kronos_decision_active"] is False
    assert "KRONOS_SHADOW_SUPPORTS_PHASE" in result["reason_codes"]
    assert result["sources"]["kronos"]["usable"] is True
    assert result["guardrails"]["kronos_decision_active"] is False


def test_kronos_shadow_conflict_is_visible_but_does_not_override_meta_decision():
    monitor = {
        "1h": _snapshot(25, momentum=35, order_flow=25),
        "4h": _snapshot(38, momentum=45, order_flow=50),
    }
    result = _evaluate(monitor, _ta("HOLD"), _kronos(score4=-40))
    assert result["recommendation"] == "HOLD"
    assert result["shadow_evidence"]["kronos_alignment"] == "CONFLICTS"
    assert "KRONOS_SHADOW_CONFLICTS_WITH_PHASE" in result["reason_codes"]
