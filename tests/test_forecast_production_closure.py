from datetime import datetime, timedelta, timezone

from eth_trend_v3.production_validation import shadow_overlap_diagnostics, validate_production_summary


UTC = timezone.utc


def _summary(forecast):
    return {
        "4h": {
            "timestamp": "2026-08-25 08:00 UTC",
            "data_health": {"status": "NORMAL"},
            "forecasts": {"3d": dict(forecast), "7d": dict(forecast), "30d": dict(forecast)},
        }
    }


def test_post_run_validation_accepts_explicit_fail_closed_forecasts():
    report = validate_production_summary(
        _summary({"probability_up": None, "status": "UNAVAILABLE", "reason": "NO_PRODUCTION_APPROVAL"}),
        now=datetime(2026, 8, 25, 9, tzinfo=UTC),
        notification_configured=True,
    )
    assert report["ok"] is True


def test_post_run_validation_rejects_unapproved_published_probability():
    report = validate_production_summary(
        _summary({"probability_up": 0.61, "status": "CALIBRATED", "metrics": {"base_rate": 0.52}}),
        now=datetime(2026, 8, 25, 9, tzinfo=UTC),
    )
    assert report["ok"] is False
    assert any("PUBLISHED_PROBABILITY_NOT_PRODUCTION" in item for item in report["errors"])
    assert any("MISSING_PRODUCTION_APPROVAL" in item for item in report["errors"])


def test_shadow_diagnostics_expose_span_overlap_and_regime_coverage_without_promoting():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    records = []
    for i in range(20):
        records.append(
            {
                "settled": True,
                "data_health": "NORMAL",
                "horizon": "3d",
                "forecast_time": (start + timedelta(hours=4 * i)).isoformat(),
                "regime": "bull" if i < 10 else "bear",
            }
        )
    report = shadow_overlap_diagnostics(records, horizon="3d")
    assert report["kind"] == "DIAGNOSTIC"
    assert report["temporal_span_hours"] == 76.0
    assert report["overlap_factor_estimate"] == 18.0
    assert report["conservative_nonoverlap_opportunities"] == 2
    assert report["regime_count"] == 2
