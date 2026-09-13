import datetime as dt
import json
import subprocess
import sys
from pathlib import Path


def _monitor():
    now = dt.datetime.now(dt.timezone.utc)
    timestamp = now.strftime("%Y-%m-%d %H:%M UTC")
    base = {
        "timestamp": timestamp,
        "coverage": 98,
        "data_health": {"status": "NORMAL"},
        "model_health": {"status": "NORMAL"},
        "regime": {"regime": "Transition"},
        "volatility_risk": 25,
        "feature_clusters": {
            "momentum": {"score": 55},
            "order_flow": {"score": 59},
            "options_positioning": {"score": -21},
        },
    }
    return {
        "1h": {**base, "rule_direction": 1},
        "4h": {**base, "rule_direction": 22},
    }


def _decision():
    now = dt.datetime.now(dt.timezone.utc)
    return {
        "contract_version": "tradingagents-decision-v1",
        "generated_at": now.isoformat(),
        "analysis_date": now.date().isoformat(),
        "canonical_symbol": "ETH-USD",
        "decision": "Hold",
        "decision_normalized": "HOLD",
        "report_path": "/tmp/report.md",
    }


def test_local_pipeline_reuses_fresh_decision_when_phase_is_stable(tmp_path):
    monitor_path = tmp_path / "incoming_monitor.json"
    state_dir = tmp_path / "state"
    monitor_path.write_text(json.dumps(_monitor()), encoding="utf-8")
    state_dir.mkdir()
    (state_dir / "latest_monitor.json").write_text(json.dumps(_monitor()), encoding="utf-8")
    (state_dir / "tradingagents_decision.json").write_text(json.dumps(_decision()), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_local_meta_pipeline.py",
            "--monitor-file",
            str(monitor_path),
            "--state-dir",
            str(state_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    trigger = json.loads((state_dir / "tradingagents_trigger.json").read_text(encoding="utf-8"))
    meta = json.loads((state_dir / "meta_decision.json").read_text(encoding="utf-8"))
    assert trigger["action"] == "REUSE"
    assert meta["recommendation"] == "HOLD"
    assert meta["pipeline"]["ta_trigger_action"] == "REUSE"


def test_local_pipeline_defers_when_phase_is_untrustworthy(tmp_path):
    monitor = _monitor()
    monitor["4h"]["coverage"] = 40
    monitor_path = tmp_path / "incoming_monitor.json"
    state_dir = tmp_path / "state"
    monitor_path.write_text(json.dumps(monitor), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_local_meta_pipeline.py",
            "--monitor-file",
            str(monitor_path),
            "--state-dir",
            str(state_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    trigger = json.loads((state_dir / "tradingagents_trigger.json").read_text(encoding="utf-8"))
    assert trigger["action"] == "DEFER"
    assert not (state_dir / "meta_decision.json").exists()
