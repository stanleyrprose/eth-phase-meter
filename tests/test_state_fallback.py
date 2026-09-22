from datetime import datetime, timezone
import json

import eth_trend_v3.state_fallback as state_fallback


def test_load_fallback_uses_tactical_and_strategic_artifacts(tmp_path):
    tactical = tmp_path / "tactical"
    strategic = tmp_path / "strategic"
    tactical.mkdir()
    strategic.mkdir()

    (tactical / "latest_tactical_1h.json").write_text(
        json.dumps({"timestamp": "2026-09-22 01:15 UTC", "rule_direction": 20}),
        encoding="utf-8",
    )
    (strategic / "latest_monitor.json").write_text(
        json.dumps({"4h": {"timestamp": "2026-09-21 20:15 UTC", "rule_direction": 55}}),
        encoding="utf-8",
    )

    one, one_source = state_fallback.load_fallback_record("monitor_state_1h", state_root=tmp_path)
    four, four_source = state_fallback.load_fallback_record("monitor_state_4h", state_root=tmp_path)

    assert one["rule_direction"] == 20
    assert one_source == "ARTIFACT_TACTICAL"
    assert four["rule_direction"] == 55
    assert four_source == "ARTIFACT_STRATEGIC"


def test_load_state_prefers_postgres(monkeypatch, tmp_path):
    monkeypatch.setattr(
        state_fallback,
        "load_latest_record",
        lambda record_type: {"timestamp": "2026-09-22 01:15 UTC", "rule_direction": 30},
    )
    value, source = state_fallback.load_state_record("monitor_state_1h", state_root=tmp_path)
    assert value["rule_direction"] == 30
    assert source == "POSTGRES"


def test_state_age_hours():
    age = state_fallback.state_age_hours(
        {"timestamp": "2026-09-22 00:15 UTC"},
        now=datetime(2026, 9, 22, 5, 15, tzinfo=timezone.utc),
    )
    assert age == 5.0
