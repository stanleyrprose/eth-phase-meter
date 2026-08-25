from datetime import datetime, timedelta, timezone

import eth_phase_meter as core
from eth_trend_v3.dataset import build_labeled_rows, canonicalize_pit_records, feature_row, pit_history_depth
from eth_trend_v3.horizon_features import external_feature_contracts, validate_feature_contract
from eth_trend_v3.research_feature_groups import group_ablation
from eth_trend_v3.research_readiness import assess_research_readiness

UTC = timezone.utc


def _pit(i: int, *, derivatives_source: str = "Deribit") -> dict:
    ts = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=4 * i)
    return {
        "observed_at": ts.isoformat(),
        "metric_value": {"price": 2000.0 + i, "timeframe": "4h"},
        "coverage": 95.0,
        "market_state_vector": {"dimensions": {}},
        "raw_payload": {
            "derivatives": {"funding_rate": 0.0001, "OI": 300_000_000, "_data_source": derivatives_source},
            "options": {
                "put_call_oi_ratio": 0.7,
                "atm_iv_near": 60.0,
                "atm_iv_next": 57.0,
                "iv_skew_25d_proxy_near": 2.5,
            },
            "macro": {
                "dxy_chg": -0.001,
                "dxy_src": "FRED",
                "us10y_change_bps": 3.0,
                "us2y_change_bps": 2.0,
                "real10y_change_bps": 1.0,
                "yield_curve_10y2y_pp": 0.5,
                "btc_change_24h": 1.2,
                "ethbtc_change": -0.4,
            },
        },
    }


def test_pit_feature_row_exposes_registered_research_candidates_without_model_promotion():
    row = feature_row(_pit(0))
    assert row["funding_rate"] == 0.0001
    assert row["open_interest"] == 300_000_000
    assert row["derivatives_source"] == "Deribit"
    assert row["put_call_oi_ratio"] == 0.7
    assert row["iv_term_structure_near_next"] == 3.0
    assert row["real10y_change_bps"] == 1.0
    assert row["yield_curve_10y2y_pp"] == 0.5
    assert "probability_up" not in row


def test_registered_feature_depth_has_explicit_contracts_and_no_silent_zero_fill():
    contracts = {item.feature_name: item for item in external_feature_contracts()}
    expected = {
        "funding_rate", "open_interest", "put_call_oi_ratio", "atm_iv_near",
        "iv_skew_25d_proxy_near", "iv_term_structure_near_next", "dxy_return",
        "us10y_change_bps", "us2y_change_bps", "real10y_change_bps",
        "yield_curve_10y2y_pp", "btc_return_24h_pct", "ethbtc_return_24h_pct",
    }
    assert expected.issubset(contracts)
    for name in expected:
        validate_feature_contract(contracts[name])
        assert contracts[name].missing_policy == "mark_missing"


def test_pit_history_depth_is_diagnostic_not_promotion_evidence():
    report = pit_history_depth([_pit(i) for i in range(190)])
    assert report["raw_n"] == 190
    assert report["span_days"] > 30
    assert report["kind"] == "DIAGNOSTIC"
    assert report["horizons"]["3d"]["conservative_nonoverlap_n"] == 10
    assert report["horizons"]["7d"]["conservative_nonoverlap_n"] == 4
    assert report["horizons"]["30d"]["conservative_nonoverlap_n"] == 1
    assert all(not item["effective_evidence_confirmed"] for item in report["horizons"].values())



def test_pit_history_depth_cannot_be_inflated_by_dense_manual_runs():
    records = []
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(40):
        record = _pit(0)
        record["observed_at"] = (start + timedelta(minutes=10 * i)).isoformat()
        records.append(record)
    report = pit_history_depth(records)
    assert report["source_raw_n"] == 40
    assert report["raw_n"] == 3
    assert report["duplicates_removed"] == 37
    assert report["horizons"]["3d"]["span_complete_windows"] == 0
    assert report["horizons"]["3d"]["conservative_nonoverlap_n"] == 0


def test_canonical_pit_prefers_scheduled_and_labeled_rows_do_not_duplicate_manual_runs():
    scheduled=_pit(0); scheduled["observed_at"]="2026-01-01T00:20:00+00:00"; scheduled["github_event"]="schedule"
    manual=_pit(0); manual["observed_at"]="2026-01-01T00:30:00+00:00"; manual["github_event"]="workflow_dispatch"; manual["metric_value"]["price"]=9999.0
    future=_pit(18); future["observed_at"]="2026-01-04T00:20:00+00:00"; future["github_event"]="schedule"
    canonical=canonicalize_pit_records([manual,scheduled,future])
    assert len(canonical)==2
    assert canonical[0]["metric_value"]["price"] != 9999.0
    rows=build_labeled_rows([manual,scheduled,future],72,tolerance_hours=1)
    assert len(rows)==1
    assert rows[0]["price"] != 9999.0

def test_fred_details_preserve_observation_date_and_absolute_rate_change(monkeypatch):
    core.fred_latest_details.cache_clear()
    monkeypatch.setattr(
        core,
        "fetch_fred_series",
        lambda series_id, limit=5: [
            {"date": "2026-08-24", "value": "2.40", "realtime_start": "2026-08-25", "realtime_end": "2026-08-25"},
            {"date": "2026-08-21", "value": "2.35", "realtime_start": "2026-08-25", "realtime_end": "2026-08-25"},
        ],
    )
    details = core.fred_latest_details("DFII10")
    assert details["value"] == 2.40
    assert round(details["change_abs"] * 100, 8) == 5.0
    assert details["observation_date"] == "2026-08-24"
    core.fred_latest_details.cache_clear()


def test_research_readiness_waits_without_auto_shadow_or_production():
    report=assess_research_readiness([_pit(i) for i in range(40)])
    assert report["status"] == "WAIT_FOR_MORE_PIT"
    assert report["run_research_benchmark"] is False
    assert report["automatic_shadow_allowed"] is False
    assert report["automatic_production_allowed"] is False
    assert all(not h["production_eligible"] for h in report["horizons"].values())


def test_registered_group_ablation_is_research_only_when_data_insufficient():
    rows=[]
    for i in range(20):
        row=feature_row(_pit(i))
        row["target_up"]=i%2
        rows.append(row)
    report=group_ablation(rows)
    assert report["research_only"] is True
    assert report["promotion_allowed"] is False
    assert set(report["groups"]) == {"derivatives","options","macro_rates","crypto_beta"}
    assert all(not item["production_eligible"] for item in report["groups"].values())


def test_group_ablation_marks_mixed_oi_provider_regime():
    rows=[]
    for i in range(20):
        row=feature_row(_pit(i, derivatives_source="Deribit" if i < 15 else "Binance"))
        row["target_up"]=i%2
        rows.append(row)
    report=group_ablation(rows)
    assert report["provider_provenance"]["mixed_provider_regime"] is True
    assert report["provider_provenance"]["dominant_derivatives_source"] == "Deribit"
