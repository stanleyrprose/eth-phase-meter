import datetime as dt
import json
import subprocess
import sys


def test_direct_meta_decision_cli_executes_from_repo_root(tmp_path):
    now = dt.datetime.now(dt.timezone.utc)
    phase_timestamp = now.strftime("%Y-%m-%d %H:%M UTC")
    monitor = {
        "1h": {
            "timestamp": phase_timestamp,
            "rule_direction": 1,
            "coverage": 98,
            "feature_clusters": {},
            "data_health": {"status": "NORMAL"},
            "model_health": {"status": "NORMAL"},
            "volatility_risk": 20,
            "regime": {"regime": "Range"},
        },
        "4h": {
            "timestamp": phase_timestamp,
            "rule_direction": 22,
            "coverage": 98,
            "feature_clusters": {
                "momentum": {"score": 55.2},
                "order_flow": {"score": 59.4},
                "options_positioning": {"score": -21.0},
            },
            "data_health": {"status": "NORMAL"},
            "model_health": {"status": "NORMAL"},
            "volatility_risk": 25,
            "regime": {"regime": "Transition"},
        },
    }
    tradingagents = {
        "contract_version": "tradingagents-decision-v1",
        "canonical_symbol": "ETH-USD",
        "analysis_date": now.date().isoformat(),
        "generated_at": now.isoformat(),
        "decision": "Hold",
        "decision_normalized": "HOLD",
        "report_path": "/tmp/complete_report.md",
    }
    monitor_path = tmp_path / "latest_monitor.json"
    ta_path = tmp_path / "decision.json"
    output_path = tmp_path / "meta_decision.json"
    monitor_path.write_text(json.dumps(monitor), encoding="utf-8")
    ta_path.write_text(json.dumps(tradingagents), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_meta_decision.py",
            "--monitor",
            str(monitor_path),
            "--tradingagents",
            str(ta_path),
            "--output",
            str(output_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert result["recommendation"] == "HOLD"
    assert "CONSTRUCTIVE_BUT_UNCONFIRMED" in result["reason_codes"]
