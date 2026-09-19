#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import faulthandler
import json
import os
import signal
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterator


GH_LIST_TIMEOUT_SECONDS = 30
GH_DOWNLOAD_TIMEOUT_SECONDS = 120
TRADINGAGENTS_TIMEOUT_SECONDS = 3600
KRONOS_TIMEOUT_SECONDS = 1800
DEFAULT_WATCHDOG_SECONDS = 5400
TRACEBACK_DELAY_SECONDS = 60
PROCESS_TERMINATION_GRACE_SECONDS = 2
PROGRESS_FILENAME = "progress.jsonl"


class PipelineWatchdogTimeout(TimeoutError):
    pass


class ProgressLogger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def emit(self, stage: str, **details: object) -> None:
        payload = {
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            "stage": stage,
            **details,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
            handle.flush()
        print(f"Meta Pipeline progress: {stage}", flush=True)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_components():
    root = _repo_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from eth_trend_v3.meta_decision import evaluate_meta_decision
    from eth_trend_v3.meta_notification import process_meta_notification
    from eth_trend_v3.ta_trigger import evaluate_tradingagents_trigger

    return evaluate_meta_decision, evaluate_tradingagents_trigger, process_meta_notification


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _json_is_recent(payload: dict, *, max_age_hours: float) -> bool:
    value = payload.get("generated_at")
    if not value:
        return False
    try:
        stamp = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=dt.timezone.utc)
    age = (dt.datetime.now(dt.timezone.utc) - stamp.astimezone(dt.timezone.utc)).total_seconds()
    return -300 <= age <= max_age_hours * 3600


def _signal_process_tree(process: subprocess.Popen[str], sig: signal.Signals) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, sig)
        elif sig == signal.SIGTERM:
            process.terminate()
        else:
            process.kill()
    except ProcessLookupError:
        pass


def _stop_process_tree(process: subprocess.Popen[str]) -> None:
    _signal_process_tree(process, signal.SIGTERM)
    try:
        process.communicate(timeout=PROCESS_TERMINATION_GRACE_SECONDS)
        return
    except subprocess.TimeoutExpired:
        _signal_process_tree(process, signal.SIGKILL)
    process.communicate()


def _run(
    command: list[str],
    *,
    cwd: Path | None = None,
    timeout: float | None = None,
    timeout_code: str = "SUBPROCESS_TIMEOUT",
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=os.name == "posix",
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _stop_process_tree(process)
        raise RuntimeError(timeout_code) from None
    except BaseException:
        _stop_process_tree(process)
        raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


@contextlib.contextmanager
def _pipeline_watchdog(seconds: float) -> Iterator[None]:
    if seconds <= 0 or os.name != "posix":
        yield
        return

    def _timeout(_signum: int, _frame: object) -> None:
        raise PipelineWatchdogTimeout("PIPELINE_WATCHDOG_TIMEOUT")

    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


@contextlib.contextmanager
def _delayed_traceback_diagnostics(delay_seconds: float = TRACEBACK_DELAY_SECONDS) -> Iterator[None]:
    try:
        faulthandler.dump_traceback_later(delay_seconds, repeat=True)
    except (OSError, ValueError):
        yield
        return
    try:
        yield
    finally:
        faulthandler.cancel_dump_traceback_later()


def _latest_monitor_run(gh: str, repo: str, workflow: str) -> dict:
    completed = _run(
        [
            gh,
            "run",
            "list",
            "--repo",
            repo,
            "--workflow",
            workflow,
            "--status",
            "success",
            "--limit",
            "1",
            "--json",
            "databaseId,headSha,createdAt",
        ],
        timeout=GH_LIST_TIMEOUT_SECONDS,
        timeout_code="GH_RUN_LIST_TIMEOUT",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"GH_RUN_LIST_FAILED: {completed.stderr.strip()}")
    rows = json.loads(completed.stdout or "[]")
    if not rows:
        raise RuntimeError("NO_SUCCESSFUL_MONITOR_RUN")
    return rows[0]


def _download_monitor(gh: str, repo: str, run_id: int, destination: Path) -> Path:
    completed = _run(
        [
            gh,
            "run",
            "download",
            str(run_id),
            "--repo",
            repo,
            "--pattern",
            "eth-monitor-*",
            "--dir",
            str(destination),
        ],
        timeout=GH_DOWNLOAD_TIMEOUT_SECONDS,
        timeout_code="GH_RUN_DOWNLOAD_TIMEOUT",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"GH_RUN_DOWNLOAD_FAILED: {completed.stderr.strip()}")
    matches = list(destination.rglob("latest_monitor.json"))
    if len(matches) != 1:
        raise RuntimeError(f"MONITOR_ARTIFACT_AMBIGUOUS: count={len(matches)}")
    return matches[0]


def _monitor_date(monitor: dict) -> str:
    value = str(((monitor.get("4h") or {}).get("timestamp")) or "")
    if value.endswith(" UTC"):
        try:
            return dt.datetime.strptime(value, "%Y-%m-%d %H:%M UTC").date().isoformat()
        except ValueError:
            pass
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


def _tradingagents_python(repo: Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    venv_python = repo / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def _run_tradingagents(repo: Path, python: str, analysis_date: str, decision_path: Path) -> None:
    runner = repo / "scripts" / "run_tradingagents.py"
    if not runner.exists():
        raise RuntimeError(f"TRADINGAGENTS_RUNNER_MISSING: {runner}")
    completed = _run(
        [
            python,
            str(runner),
            "ETH-USD",
            "--date",
            analysis_date,
            "--decision-json",
            str(decision_path),
        ],
        cwd=repo,
        timeout=TRADINGAGENTS_TIMEOUT_SECONDS,
        timeout_code="TRADINGAGENTS_TIMEOUT",
    )
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout or "")[-2000:]
        raise RuntimeError(f"TRADINGAGENTS_RUN_FAILED: {tail.strip()}")
    if not decision_path.exists():
        raise RuntimeError("TRADINGAGENTS_DECISION_NOT_WRITTEN")


def _kronos_python(repo: Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    venv_python = repo / ".venv" / "bin" / "python"
    if not venv_python.exists():
        raise RuntimeError(f"KRONOS_PYTHON_MISSING: {venv_python}")
    return str(venv_python)


def _prepare_kronos_inputs(state_dir: Path) -> tuple[Path, Path]:
    import pandas as pd
    import github_actions_runner as market

    now = dt.datetime.now(dt.timezone.utc)
    outputs: list[Path] = []
    for timeframe, seconds in (("1h", 3600), ("4h", 4 * 3600)):
        candles = market.fetch_market_klines(interval=timeframe, limit=220)
        if candles is None or len(candles) < 50:
            raise RuntimeError(f"KRONOS_CANDLES_UNAVAILABLE: timeframe={timeframe}")
        frame = candles.copy()
        stamps = frame["open_time"]
        if getattr(stamps.dtype, "kind", "") in {"i", "u", "f"}:
            timestamps = pd.to_datetime(stamps, unit="ms", utc=True)
        else:
            timestamps = pd.to_datetime(stamps, utc=True)
        cutoff_seconds = (int(now.timestamp()) // seconds) * seconds
        cutoff = pd.Timestamp(cutoff_seconds, unit="s", tz="UTC")
        frame = frame.assign(timestamps=timestamps)
        frame = frame[frame["timestamps"] < cutoff].copy()
        if len(frame) < 50:
            raise RuntimeError(f"KRONOS_CLOSED_CANDLES_TOO_SHORT: timeframe={timeframe} rows={len(frame)}")
        if "quote_vol" in frame:
            amount = frame["quote_vol"].astype(float)
        else:
            amount = frame["volume"].astype(float) * frame["close"].astype(float)
        export = frame.assign(amount=amount)[
            ["timestamps", "open", "high", "low", "close", "volume", "amount"]
        ].tail(220)
        output = state_dir / f"kronos_input_{timeframe}.csv"
        export.to_csv(output, index=False)
        outputs.append(output)
    return outputs[0], outputs[1]


def _run_kronos_shadow(
    *,
    repo_root: Path,
    kronos_repo: Path,
    python: str,
    state_dir: Path,
    evidence_path: Path,
    model: str,
    sample_count: int,
) -> None:
    runner = repo_root / "scripts" / "run_kronos_shadow.py"
    if not runner.exists():
        raise RuntimeError(f"KRONOS_RUNNER_MISSING: {runner}")
    input_1h, input_4h = _prepare_kronos_inputs(state_dir)
    completed = _run(
        [
            python,
            str(runner),
            "--kronos-repo",
            str(kronos_repo),
            "--input-1h",
            str(input_1h),
            "--input-4h",
            str(input_4h),
            "--output",
            str(evidence_path),
            "--model",
            model,
            "--sample-count",
            str(sample_count),
        ],
        cwd=repo_root,
        timeout=KRONOS_TIMEOUT_SECONDS,
        timeout_code="KRONOS_TIMEOUT",
    )
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout or "")[-2000:]
        raise RuntimeError(f"KRONOS_RUN_FAILED: {tail.strip()}")
    if not evidence_path.exists():
        raise RuntimeError("KRONOS_EVIDENCE_NOT_WRITTEN")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Event-triggered local bridge from the latest GitHub ETH monitor artifact to TradingAgents."
    )
    parser.add_argument("--repo", default="stanleyrprose/eth-phase-meter")
    parser.add_argument("--workflow", default="scheduled-monitor.yml")
    parser.add_argument(
        "--state-dir",
        default=str(Path.home() / ".eth-meta-pipeline"),
        help="durable local state; contains the latest source contracts and meta decision",
    )
    parser.add_argument(
        "--tradingagents-repo",
        default=str(Path.home() / "Documents/mcpx-projects/TradingAgents-codex-oauth"),
    )
    parser.add_argument("--tradingagents-python")
    parser.add_argument("--enable-kronos", action="store_true", help="enable research-only Kronos shadow evidence")
    parser.add_argument(
        "--kronos-repo",
        default=str(Path.home() / ".openclaw/workspace/tools/eth-meta-runtime/Kronos"),
    )
    parser.add_argument("--kronos-python")
    parser.add_argument("--kronos-model", choices=("mini", "small", "base"), default="small")
    parser.add_argument("--kronos-sample-count", type=int, default=3)
    parser.add_argument("--gh", help="path to GitHub CLI; auto-detected when omitted")
    parser.add_argument(
        "--monitor-file",
        help="use a local latest_monitor.json instead of downloading the latest successful GitHub artifact",
    )
    parser.add_argument("--force-ta", action="store_true", help="force a TradingAgents refresh after phase gates pass")
    parser.add_argument(
        "--watchdog-seconds",
        type=float,
        default=DEFAULT_WATCHDOG_SECONDS,
        help="whole-pipeline POSIX watchdog in seconds; use 0 to disable (default: 5400)",
    )
    parser.add_argument(
        "--telegram-secret-file",
        default=str(Path.home() / ".eth-meta-pipeline" / "telegram.json"),
        help="local Telegram credential JSON; TG_BOT_TOKEN/TG_CHAT_ID take precedence",
    )
    args = parser.parse_args(argv)
    if args.watchdog_seconds < 0:
        parser.error("--watchdog-seconds must be non-negative")
    if args.kronos_sample_count < 1:
        parser.error("--kronos-sample-count must be >= 1")
    return args


def _execute_pipeline(args: argparse.Namespace, progress: ProgressLogger) -> int:
    evaluate_meta_decision, evaluate_trigger, process_notification = _load_components()
    progress.emit("components_loaded")
    state_dir = Path(args.state_dir).expanduser().resolve()
    kronos_repo_path = Path(args.kronos_repo).expanduser().resolve()
    default_state_dir = (Path.home() / ".eth-meta-pipeline").resolve()
    kronos_enabled = bool(
        args.enable_kronos or (state_dir == default_state_dir and kronos_repo_path.exists())
    )
    state_path = state_dir / "state.json"
    previous_monitor_path = state_dir / "latest_monitor.json"
    decision_path = state_dir / "tradingagents_decision.json"
    trigger_path = state_dir / "tradingagents_trigger.json"
    kronos_path = state_dir / "kronos_evidence.json"
    meta_path = state_dir / "meta_decision.json"
    state = _read_json(state_path)

    run_id: int | str
    run_sha: str | None = None
    if args.monitor_file:
        progress.emit("monitor_load_started", source="local")
        monitor_path = Path(args.monitor_file).expanduser().resolve()
        monitor = _read_json(monitor_path)
        run_id = f"local:{(monitor.get('4h') or {}).get('timestamp') or monitor_path.stat().st_mtime_ns}"
        progress.emit("monitor_loaded", source="local", run_id=run_id)
    else:
        gh = args.gh or shutil.which("gh")
        if not gh:
            raise RuntimeError("GH_CLI_NOT_FOUND")
        progress.emit("gh_run_list_started")
        latest = _latest_monitor_run(gh, args.repo, args.workflow)
        run_id = int(latest["databaseId"])
        run_sha = latest.get("headSha")
        progress.emit("gh_run_list_completed", run_id=run_id)
        if state.get("last_processed_run_id") == run_id:
            progress.emit("pipeline_completed", status="NO_NEW_MONITOR_RUN", run_id=run_id)
            print(f"NO_NEW_MONITOR_RUN run_id={run_id}")
            return 0
        with tempfile.TemporaryDirectory(prefix="eth-meta-") as tmp:
            progress.emit("gh_run_download_started", run_id=run_id)
            monitor_path = _download_monitor(gh, args.repo, run_id, Path(tmp))
            progress.emit("gh_run_download_completed", run_id=run_id)
            monitor = _read_json(monitor_path)
            progress.emit("monitor_loaded", source="github", run_id=run_id)

    previous_monitor = _read_json(previous_monitor_path)
    existing_decision = _read_json(decision_path)
    trigger = evaluate_trigger(
        monitor,
        previous_monitor=previous_monitor or None,
        tradingagents=existing_decision or None,
    )
    if args.force_ta and trigger["action"] != "DEFER":
        trigger["action"] = "RUN"
        trigger["reason_codes"] = ["FORCED_REFRESH"] + trigger["reason_codes"]
    trigger["monitor_run_id"] = run_id
    trigger["monitor_git_sha"] = run_sha
    _write_json(trigger_path, trigger)
    progress.emit("trigger_evaluated", action=trigger["action"], run_id=run_id)

    if trigger["action"] == "DEFER":
        _write_json(previous_monitor_path, monitor)
        state.update(
            {
                "last_processed_run_id": run_id,
                "last_monitor_git_sha": run_sha,
                "last_pipeline_status": "DEFER",
                "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
        )
        _write_json(state_path, state)
        progress.emit("state_written", status="DEFER", run_id=run_id)
        progress.emit("pipeline_completed", status="DEFER", run_id=run_id)
        print(f"Meta Pipeline: DEFER | reasons={','.join(trigger['reason_codes'])}")
        return 0

    kronos_evidence = _read_json(kronos_path)
    if kronos_enabled:
        refresh_kronos = trigger["action"] == "RUN" or not _json_is_recent(
            kronos_evidence, max_age_hours=12.0
        )
        if refresh_kronos:
            progress.emit("kronos_started", run_id=run_id, model=args.kronos_model)
            try:
                kronos_repo = Path(args.kronos_repo).expanduser().resolve()
                kronos_python = _kronos_python(kronos_repo, args.kronos_python)
                _run_kronos_shadow(
                    repo_root=_repo_root(),
                    kronos_repo=kronos_repo,
                    python=kronos_python,
                    state_dir=state_dir,
                    evidence_path=kronos_path,
                    model=args.kronos_model,
                    sample_count=args.kronos_sample_count,
                )
                kronos_evidence = _read_json(kronos_path)
                progress.emit("kronos_completed", run_id=run_id, model=args.kronos_model)
            except Exception as exc:
                kronos_evidence = {
                    "contract_version": "kronos-evidence-v1",
                    "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "asset": "ETH-USD",
                    "mode": "SHADOW",
                    "horizons": {},
                    "error": str(exc).splitlines()[-1][:500],
                    "guardrails": {
                        "decision_active": False,
                        "probability_generated": False,
                        "order_execution_allowed": False,
                    },
                }
                _write_json(kronos_path, kronos_evidence)
                progress.emit(
                    "kronos_failed_open",
                    run_id=run_id,
                    error_code=str(exc).split(":", 1)[0] or type(exc).__name__,
                )
        else:
            progress.emit("kronos_reused", run_id=run_id)

    if trigger["action"] == "RUN":
        ta_repo = Path(args.tradingagents_repo).expanduser().resolve()
        ta_python = _tradingagents_python(ta_repo, args.tradingagents_python)
        progress.emit("tradingagents_started", run_id=run_id)
        _run_tradingagents(ta_repo, ta_python, _monitor_date(monitor), decision_path)
        progress.emit("tradingagents_completed", run_id=run_id)

    decision = _read_json(decision_path)
    meta = evaluate_meta_decision(monitor, decision, kronos_evidence if kronos_enabled else None)
    progress.emit("meta_decision_completed", recommendation=meta["recommendation"], run_id=run_id)
    meta["pipeline"] = {
        "monitor_run_id": run_id,
        "monitor_git_sha": run_sha,
        "ta_trigger_action": trigger["action"],
        "ta_trigger_reasons": trigger["reason_codes"],
        "kronos_enabled": kronos_enabled,
        "kronos_mode": "SHADOW" if kronos_enabled else "DISABLED",
        "kronos_model": args.kronos_model if kronos_enabled else None,
    }
    notification, last_notified = process_notification(
        meta,
        state,
        secret_file=Path(args.telegram_secret_file).expanduser().resolve(),
    )
    meta["pipeline"]["notification"] = notification
    progress.emit("notification_completed", status=notification["status"], run_id=run_id)
    _write_json(meta_path, meta)
    _write_json(previous_monitor_path, monitor)
    state.update(
        {
            "last_processed_run_id": run_id,
            "last_monitor_git_sha": run_sha,
            "last_pipeline_status": "OK",
            "last_meta_recommendation": meta["recommendation"],
            "last_notified_recommendation": last_notified,
            "last_notification": notification,
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
    )
    _write_json(state_path, state)
    progress.emit("state_written", status="OK", run_id=run_id)
    progress.emit("pipeline_completed", status="OK", run_id=run_id)

    print(
        f"Meta Pipeline: {meta['recommendation']} | alignment={meta['evidence_alignment']} | "
        f"ta={trigger['action']} | reasons={','.join(meta['reason_codes'])}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    state_dir = Path(args.state_dir).expanduser().resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    progress = ProgressLogger(state_dir / PROGRESS_FILENAME)
    progress.emit("pipeline_started", watchdog_seconds=args.watchdog_seconds)
    try:
        with _delayed_traceback_diagnostics(), _pipeline_watchdog(args.watchdog_seconds):
            return _execute_pipeline(args, progress)
    except BaseException as exc:
        progress.emit(
            "pipeline_failed",
            error_code=str(exc).split(":", 1)[0] or type(exc).__name__,
            error_type=type(exc).__name__,
        )
        raise


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Meta Pipeline ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
