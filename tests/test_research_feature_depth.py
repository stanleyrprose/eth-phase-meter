from datetime import datetime, timedelta, timezone

import eth_phase_meter as core
from eth_trend_v3.dataset import feature_row, pit_history_depth
from eth_trend_v3.horizon_features import external_feature_contracts, validate_feature_contract

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
