import datetime as dt

from eth_trend_v3.kronos_evidence import compare_kronos_to_phase, validate_kronos_evidence


NOW = dt.datetime(2026, 9, 19, 6, 0, tzinfo=dt.timezone.utc)


def _payload(score4=35.0, score1=20.0, generated_at="2026-09-19T05:00:00+00:00"):
    return {
        "contract_version": "kronos-evidence-v1",
        "generated_at": generated_at,
        "asset": "ETH-USD",
        "mode": "SHADOW",
        "horizons": {
            "1h": {
                "direction_score": score1,
                "median_terminal_return_pct": 1.2,
                "sample_count": 3,
                "terminal_return_std_pct": 0.5,
                "sample_directional_agreement_pct": 66.667,
                "pred_len": 12,
                "lookback": 160,
            },
            "4h": {
                "direction_score": score4,
                "median_terminal_return_pct": 2.5,
                "sample_count": 3,
                "terminal_return_std_pct": 1.0,
                "sample_directional_agreement_pct": 66.667,
                "pred_len": 18,
                "lookback": 120,
            },
        },
    }


def test_valid_shadow_contract_is_usable_but_not_promoted():
    result = validate_kronos_evidence(_payload(), now=NOW)
    assert result["usable"] is True
    assert result["shadow_only"] is True
    assert result["bias"] == "BULLISH"
    assert result["preferred_direction_score"] == 35.0


def test_stale_contract_fails_closed():
    result = validate_kronos_evidence(
        _payload(generated_at="2026-09-17T00:00:00+00:00"),
        now=NOW,
    )
    assert result["usable"] is False
    assert "KRONOS_STALE_OR_TIMESTAMP_INVALID" in result["reason_codes"]


def test_missing_horizons_are_not_zero_imputed():
    payload = _payload()
    payload["horizons"] = {}
    result = validate_kronos_evidence(payload, now=NOW)
    assert result["usable"] is False
    assert result["preferred_direction_score"] is None
    assert "KRONOS_NO_VALID_HORIZONS" in result["reason_codes"]


def test_phase_alignment_is_descriptive_only():
    monitor = {"4h": {"rule_direction": 38}}
    validated = validate_kronos_evidence(_payload(score4=30), now=NOW)
    assert compare_kronos_to_phase(monitor, validated) == "SUPPORTS"

    validated = validate_kronos_evidence(_payload(score4=-30), now=NOW)
    assert compare_kronos_to_phase(monitor, validated) == "CONFLICTS"
