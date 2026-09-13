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


def _run_pipeline(*args):
    return subprocess.run(
        [sys.executable, "scripts/run_local_meta_pipeline.py", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_local_pipeline_reuses_fresh_decision_when_phase_is_stable(tmp_path):
    monitor_path = tmp_path / "incoming_monitor.json"
    state_dir = tmp_path / "state"
    monitor_path.write_text(json.dumps(_monitor()), encoding="utf-8")
    state_dir.mkdir()
    (state_dir / "latest_monitor.json").write_text(json.dumps(_monitor()), encoding="utf-8")
    (state_dir / "tradingagents_decision.json").write_text(json.dumps(_decision()), encoding="utf-8")

    completed = _run_pipeline(
        "--monitor-file",
        str(monitor_path),
        "--state-dir",
        str(state_dir),
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

    completed = _run_pipeline(
        "--monitor-file",
        str(monitor_path),
        "--state-dir",
        str(state_dir),
    )
    assert completed.returncode == 0, completed.stderr
    trigger = json.loads((state_dir / "tradingagents_trigger.json").read_text(encoding="utf-8"))
    assert trigger["action"] == "DEFER"
    assert not (state_dir / "meta_decision.json").exists()


def test_local_pipeline_runs_tradingagents_when_contract_is_missing(tmp_path):
    monitor_path = tmp_path / "incoming_monitor.json"
    state_dir = tmp_path / "state"
    ta_repo = tmp_path / "TradingAgents"
    scripts = ta_repo / "scripts"
    scripts.mkdir(parents=True)
    monitor_path.write_text(json.dumps(_monitor()), encoding="utf-8")

    fake_runner = scripts / "run_tradingagents.py"
    fake_runner.write_text(
        """
import argparse
import datetime as dt
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("symbol")
parser.add_argument("--date", required=True)
parser.add_argument("--decision-json", required=True)
args = parser.parse_args()
now = dt.datetime.now(dt.timezone.utc)
payload = {
    "contract_version": "tradingagents-decision-v1",
    "generated_at": now.isoformat(),
    "analysis_date": args.date,
    "canonical_symbol": "ETH-USD",
    "decision": "Hold",
    "decision_normalized": "HOLD",
    "report_path": "/tmp/fake-report.md",
}
Path(args.decision_json).parent.mkdir(parents=True, exist_ok=True)
Path(args.decision_json).write_text(json.dumps(payload), encoding="utf-8")
""".strip(),
        encoding="utf-8",
    )

    completed = _run_pipeline(
        "--monitor-file",
        str(monitor_path),
        "--state-dir",
        str(state_dir),
        "--tradingagents-repo",
        str(ta_repo),
        "--tradingagents-python",
        sys.executable,
    )
    assert completed.returncode == 0, completed.stderr
    trigger = json.loads((state_dir / "tradingagents_trigger.json").read_text(encoding="utf-8"))
    decision = json.loads((state_dir / "tradingagents_decision.json").read_text(encoding="utf-8"))
    meta = json.loads((state_dir / "meta_decision.json").read_text(encoding="utf-8"))
    assert trigger["action"] == "RUN"
    assert "TA_MISSING_INVALID_OR_STALE" in trigger["reason_codes"]
    assert decision["contract_version"] == "tradingagents-decision-v1"
    assert meta["recommendation"] == "HOLD"
    assert meta["pipeline"]["ta_trigger_action"] == "RUN"
