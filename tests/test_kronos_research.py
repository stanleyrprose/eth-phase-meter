from datetime import datetime, timezone

import pandas as pd

from eth_trend_v3.kronos_research import (
    append_kronos_pit,
    build_kronos_pit_record,
    evaluate_kronos_pit,
    load_kronos_pit,
    resolve_kronos_outcomes,
)


def _inputs():
    monitor = {
        "1h": {"rule_direction": 30, "regime": {"regime": "Transition"}},
        "4h": {"rule_direction": 60, "regime": {"regime": "Low-Vol Bull"}},
    }
    tradingagents = {"decision_normalized": "HOLD", "generated_at": "2026-09-19T12:00:00+00:00"}
    kronos = {
        "asset": "ETH-USD",
        "generated_at": "2026-09-19T16:00:00+00:00",
        "model": {"name": "Kronos-small", "repo_sha": "abc"},
        "horizons": {
            "1h": {
                "source_last_timestamp": "2026-09-19T15:00:00+00:00",
                "source_last_close": 100.0,
                "forecast_end_timestamp": "2026-09-20T03:00:00+00:00",
                "pred_len": 12,
                "lookback": 160,
                "sample_count": 3,
                "median_terminal_return_pct": -2.0,
                "median_terminal_close": 98.0,
                "direction_score": -50.0,
                "sample_directional_agreement_pct": 66.7,
                "terminal_return_std_pct": 0.5,
                "trailing_momentum_return_pct": 1.0,
            },
            "4h": {
                "source_last_timestamp": "2026-09-19T12:00:00+00:00",
                "source_last_close": 100.0,
                "forecast_end_timestamp": "2026-09-22T12:00:00+00:00",
                "pred_len": 18,
                "lookback": 120,
                "sample_count": 3,
                "median_terminal_return_pct": -5.0,
                "median_terminal_close": 95.0,
                "direction_score": -70.0,
                "sample_directional_agreement_pct": 100.0,
                "terminal_return_std_pct": 1.2,
                "trailing_momentum_return_pct": 2.0,
            },
        },
    }
    meta = {
        "recommendation": "HOLD",
        "evidence_alignment": "MEDIUM",
        "shadow_evidence": {"kronos_alignment": "CONFLICTS"},
    }
    return monitor, tradingagents, kronos, meta


def test_append_is_idempotent(tmp_path):
    monitor, ta, kronos, meta = _inputs()
    record = build_kronos_pit_record(
        monitor=monitor,
        tradingagents=ta,
        kronos=kronos,
        meta=meta,
        monitor_run_id=123,
        monitor_git_sha="sha",
    )
    path = tmp_path / "kronos_pit.jsonl"
    assert append_kronos_pit(path, record) is True
    assert append_kronos_pit(path, record) is False
    rows = load_kronos_pit(path)
    assert len(rows) == 1
    assert rows[0]["horizons"]["4h"]["phase_direction"] == 60.0


def test_outcome_resolution_and_conflict_metrics(tmp_path):
    monitor, ta, kronos, meta = _inputs()
    record = build_kronos_pit_record(
        monitor=monitor,
        tradingagents=ta,
        kronos=kronos,
        meta=meta,
        monitor_run_id=123,
        monitor_git_sha="sha",
    )
    path = tmp_path / "kronos_pit.jsonl"
    append_kronos_pit(path, record)

    candles = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2026-09-20T03:00:00Z", "2026-09-22T12:00:00Z"], utc=True
            ),
            "close": [97.0, 94.0],
        }
    )
    resolved = resolve_kronos_outcomes(
        path,
        candles_by_timeframe={"1h": candles.iloc[[0]], "4h": candles.iloc[[1]]},
        observed_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
    )
    assert resolved == 2

    rows = load_kronos_pit(path)
    report = evaluate_kronos_pit(rows)
    one_hour = report["horizons"]["1h"]
    four_hour = report["horizons"]["4h"]
    assert one_hour["kronos_direction_hit_rate"] == 1.0
    assert one_hour["momentum_direction_hit_rate"] == 0.0
    assert four_hour["kronos_direction_hit_rate"] == 1.0
    assert four_hour["phase_direction_hit_rate"] == 0.0
    assert four_hour["raw_matured_n"] == 1
    assert four_hour["effective_nonoverlap_n"] == 1
    assert four_hour["effective_conflict_n"] == 1
    assert four_hour["conflict_kronos_hit_rate"] == 1.0
    assert four_hour["conflict_phase_hit_rate"] == 0.0
    assert report["promotion_assessment"]["eligible"] is False


def test_evaluator_reports_no_matured_samples(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    report = evaluate_kronos_pit(load_kronos_pit(path))
    assert report["horizons"]["1h"]["available"] is False
    assert report["horizons"]["4h"]["reason"] == "NO_MATURED_PIT_OUTCOMES"


def test_overlapping_72h_windows_do_not_inflate_effective_sample_size():
    def record(source, end, actual_return):
        return {
            "horizons": {
                "4h": {
                    "source_last_timestamp": source,
                    "forecast_end_timestamp": end,
                    "predicted_terminal_return_pct": 2.0,
                    "direction_score": 30.0,
                    "phase_direction": 20.0,
                    "outcome": {
                        "actual_return_pct": actual_return,
                        "kronos_direction_hit": actual_return > 0,
                        "momentum_direction_hit": actual_return > 0,
                        "phase_direction_hit": actual_return > 0,
                        "kronos_abs_price_error_pct": 1.0,
                        "persistence_abs_price_error_pct": 2.0,
                        "momentum_abs_price_error_pct": 2.5,
                    },
                }
            }
        }

    records = [
        record("2026-09-01T00:00:00Z", "2026-09-04T00:00:00Z", 3.0),
        record("2026-09-01T04:00:00Z", "2026-09-04T04:00:00Z", -1.0),
        record("2026-09-04T00:00:00Z", "2026-09-07T00:00:00Z", 2.0),
    ]
    report = evaluate_kronos_pit(records)
    four_hour = report["horizons"]["4h"]
    assert four_hour["raw_matured_n"] == 3
    assert four_hour["effective_nonoverlap_n"] == 2
    assert four_hour["overlap_discarded_n"] == 1
    assert four_hour["kronos_direction_hit_rate"] == 1.0


def test_promotion_gate_can_only_become_eligible_on_independent_strong_evidence():
    records = []
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    for index in range(100):
        source = start + pd.Timedelta(days=3 * index)
        end = source + pd.Timedelta(days=3)
        predicted = 1.0 + index / 100.0
        actual = predicted + 0.5
        records.append(
            {
                "horizons": {
                    "4h": {
                        "source_last_timestamp": source.isoformat(),
                        "forecast_end_timestamp": end.isoformat(),
                        "predicted_terminal_return_pct": predicted,
                        "direction_score": 30.0,
                        "phase_direction": -20.0 if index < 30 else 20.0,
                        "outcome": {
                            "actual_return_pct": actual,
                            "kronos_direction_hit": True,
                            "momentum_direction_hit": False,
                            "phase_direction_hit": index >= 30,
                            "kronos_abs_price_error_pct": 1.0,
                            "persistence_abs_price_error_pct": 2.0,
                            "momentum_abs_price_error_pct": 2.5,
                        },
                    }
                }
            }
        )
    report = evaluate_kronos_pit(records)
    assessment = report["promotion_assessment"]
    assert report["horizons"]["4h"]["effective_nonoverlap_n"] == 100
    assert report["horizons"]["4h"]["effective_conflict_n"] == 30
    assert assessment["eligible"] is True
    assert assessment["requires_human_approval"] is True
    assert assessment["automatic_production_change_allowed"] is False
