from eth_trend_v3.hmm_ablation import evaluate_research_gate


def test_old_30d_report_must_fail_research_gate():
    base_rate = {"brier": 0.250, "log_loss": 0.693, "calibration_error": 0.02, "oos_n": 998}
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
    gate = evaluate_research_gate(
        baseline,
        plus_hmm,
        mbase=base_rate,
        hmm_ci={"low": -0.003, "median": 0.0018, "high": 0.006},
        fold_win_rate=0.55,
    )
    assert gate["passes"] is False
    assert gate["components"]["baseline_beats_base_rate"] is False
    assert gate["components"]["brier_ok"] is False
    assert gate["components"]["brier_ci_ok"] is False
    assert gate["components"]["fold_win_rate_ok"] is False
    assert gate["components"]["log_loss_ok"] is False
    assert "LOG_LOSS_WORSE" in gate["failed_reasons"]


def test_clear_statistically_supported_improvement_can_pass_gate():
    base_rate = {"brier": 0.265, "log_loss": 0.710, "calibration_error": 0.090, "oos_n": 500}
    baseline = {"brier": 0.250, "log_loss": 0.700, "calibration_error": 0.080, "oos_n": 500}
    plus_hmm = {"brier": 0.240, "log_loss": 0.680, "calibration_error": 0.075, "oos_n": 500}
    gate = evaluate_research_gate(
        baseline,
        plus_hmm,
        mbase=base_rate,
        hmm_ci={"low": 0.003, "median": 0.010, "high": 0.017},
        fold_win_rate=0.70,
    )
    assert gate["passes"] is True
    assert all(gate["components"].values())
