from eth_trend_v3.hmm_ablation import evaluate_research_gate


def test_old_30d_report_must_fail_research_gate():
    baseline = {
        "brier": 0.5454081784964631,
        "log_loss": 2.082045947813338,
        "calibration_error": 0.6314026374457888,
        "oos_n": 998,
    }
    plus_hmm = {
        "brier": 0.5435618578353106,
        "log_loss": 2.8129756751961508,
        "calibration_error": 0.638294533784882,
        "oos_n": 998,
    }
    gate = evaluate_research_gate(baseline, plus_hmm)
    assert gate["passes"] is False
    assert gate["components"]["brier_ok"] is False
    assert gate["components"]["log_loss_ok"] is False
    assert "LOG_LOSS_WORSE" in gate["failed_reasons"]


def test_clear_multimetric_improvement_can_pass_gate():
    baseline = {
        "brier": 0.250,
        "log_loss": 0.700,
        "calibration_error": 0.080,
        "oos_n": 500,
    }
    plus_hmm = {
        "brier": 0.240,
        "log_loss": 0.680,
        "calibration_error": 0.075,
        "oos_n": 500,
    }
    gate = evaluate_research_gate(baseline, plus_hmm)
    assert gate["passes"] is True
    assert all(gate["components"].values())
