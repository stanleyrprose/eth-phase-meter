from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_tactical_workflow_applies_migrations_before_monitor():
    text = (ROOT / ".github" / "workflows" / "tactical-1h.yml").read_text(encoding="utf-8")
    assert "Apply versioned migrations" in text
    assert text.index("Apply versioned migrations") < text.index("Run 1H tactical monitor")


def test_r2_is_wired_into_both_1h_runtime_paths():
    runner = (ROOT / "eth_trend_v3" / "runner.py").read_text(encoding="utf-8")
    tactical = (ROOT / "scripts" / "run_tactical_1h.py").read_text(encoding="utf-8")
    assert "safe_run_tactical_outcome_cycle" in runner
    assert "safe_run_tactical_outcome_cycle" in tactical


def test_r2_does_not_change_tactical_threshold_constants():
    text = (ROOT / "eth_trend_v3" / "tactical_alerts.py").read_text(encoding="utf-8")
    assert "DIRECTION_THRESHOLD = 20" in text
    assert "MATERIAL_DIRECTION_DELTA = 15" in text
