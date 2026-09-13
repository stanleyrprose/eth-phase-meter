#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path


DEFAULT_LABEL = "com.stanley.eth-meta-pipeline"
DEFAULT_INTERVAL_SECONDS = 900


def _require_executable(explicit: str | None, name: str) -> str:
    candidate = explicit or shutil.which(name)
    if not candidate:
        raise RuntimeError(f"{name.upper()}_NOT_FOUND")
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        discovered = shutil.which(str(path))
        if not discovered:
            raise RuntimeError(f"{name.upper()}_NOT_FOUND")
        path = Path(discovered)
    if not path.exists():
        raise RuntimeError(f"{name.upper()}_NOT_FOUND: {path}")
    return str(path)


def build_plist(
    *,
    repo_root: Path,
    tradingagents_repo: Path,
    python: str,
    gh: str,
    codex: str,
    telegram_secret_file: Path,
    label: str = DEFAULT_LABEL,
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
) -> dict:
    state_dir = Path.home() / ".eth-meta-pipeline"
    path_entries = [
        str(Path(python).parent),
        str(Path(gh).parent),
        str(Path(codex).parent),
        "/opt/homebrew/bin",
        "/opt/anaconda3/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]
    deduped_path = ":".join(dict.fromkeys(path_entries))
    return {
        "Label": label,
        "ProgramArguments": [
            python,
            str(repo_root / "scripts" / "run_local_meta_pipeline.py"),
            "--tradingagents-repo",
            str(tradingagents_repo),
            "--gh",
            gh,
            "--telegram-secret-file",
            str(telegram_secret_file),
        ],
        "WorkingDirectory": str(repo_root),
        "StartInterval": int(interval_seconds),
        "RunAtLoad": False,
        "ProcessType": "Background",
        "EnvironmentVariables": {
            "HOME": str(Path.home()),
            "PATH": deduped_path,
        },
        "StandardOutPath": str(state_dir / "launchd.stdout.log"),
        "StandardErrorPath": str(state_dir / "launchd.stderr.log"),
    }


def _launchctl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["launchctl", *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if check and completed.returncode != 0:
        raise RuntimeError(f"LAUNCHCTL_FAILED: {' '.join(args)}: {completed.stderr.strip()}")
    return completed


def install(plist: dict, *, label: str, plist_path: Path, kickstart: bool) -> None:
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    Path.home().joinpath(".eth-meta-pipeline").mkdir(parents=True, exist_ok=True)
    plist_path.write_bytes(plistlib.dumps(plist, sort_keys=False))

    domain = f"gui/{os.getuid()}"
    _launchctl("bootout", domain, str(plist_path), check=False)
    _launchctl("bootstrap", domain, str(plist_path))
    _launchctl("enable", f"{domain}/{label}", check=False)
    if kickstart:
        _launchctl("kickstart", "-k", f"{domain}/{label}")


def uninstall(*, label: str, plist_path: Path) -> None:
    domain = f"gui/{os.getuid()}"
    _launchctl("bootout", domain, str(plist_path), check=False)
    if plist_path.exists():
        plist_path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description="Install the local ETH Meta Pipeline as a macOS LaunchAgent.")
    parser.add_argument(
        "--tradingagents-repo",
        default=str(Path.home() / "Documents/mcpx-projects/TradingAgents-codex-oauth"),
    )
    parser.add_argument("--python", help="Python executable used to run the local bridge")
    parser.add_argument("--gh", help="GitHub CLI path")
    parser.add_argument("--codex", help="Codex CLI path; used to construct launchd PATH")
    parser.add_argument(
        "--telegram-secret-file",
        default=str(Path.home() / ".eth-meta-pipeline" / "telegram.json"),
        help="path only; secret contents are never copied into the plist",
    )
    parser.add_argument("--label", default=DEFAULT_LABEL)
    parser.add_argument("--interval-seconds", type=int, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--kickstart", action="store_true", help="run immediately after installation")
    parser.add_argument("--print-plist", action="store_true", help="print plist XML and do not install")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    tradingagents_repo = Path(args.tradingagents_repo).expanduser().resolve()
    telegram_secret_file = Path(args.telegram_secret_file).expanduser().resolve()
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{args.label}.plist"

    if args.uninstall:
        uninstall(label=args.label, plist_path=plist_path)
        print(f"Uninstalled {args.label}")
        return 0

    python = _require_executable(args.python or sys.executable, "python")
    gh = _require_executable(args.gh, "gh")
    codex = _require_executable(args.codex, "codex")
    runner = tradingagents_repo / "scripts" / "run_tradingagents.py"
    if not runner.exists():
        raise RuntimeError(f"TRADINGAGENTS_RUNNER_MISSING: {runner}")
    if not (repo_root / "scripts" / "run_local_meta_pipeline.py").exists():
        raise RuntimeError("META_PIPELINE_RUNNER_MISSING")
    if args.interval_seconds < 300:
        raise RuntimeError("INTERVAL_TOO_SHORT: minimum is 300 seconds")

    plist = build_plist(
        repo_root=repo_root,
        tradingagents_repo=tradingagents_repo,
        python=python,
        gh=gh,
        codex=codex,
        telegram_secret_file=telegram_secret_file,
        label=args.label,
        interval_seconds=args.interval_seconds,
    )
    if args.print_plist:
        sys.stdout.buffer.write(plistlib.dumps(plist, sort_keys=False))
        return 0

    install(plist, label=args.label, plist_path=plist_path, kickstart=args.kickstart)
    print(f"Installed {args.label} -> {plist_path}")
    print(f"Interval: {args.interval_seconds}s | kickstart={args.kickstart}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"LaunchAgent ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
