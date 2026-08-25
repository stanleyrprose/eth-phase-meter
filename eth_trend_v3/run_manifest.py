from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4


def dependency_hash(requirements_path: str = "requirements.lock") -> str:
    path = Path(requirements_path)
    if not path.exists() and requirements_path == "requirements.lock":
        path = Path("requirements.txt")
    if not path.exists():
        return "MISSING"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_sha() -> str:
    env_sha = os.getenv("GITHUB_SHA")
    if env_sha:
        return env_sha
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "UNKNOWN"


def build_run_manifest(
    *,
    workflow_name: str,
    dataset_hash: str,
    experiment_ids: Sequence[str] = (),
    artifacts: Sequence[str] = (),
    result: str = "UNKNOWN",
    started_at: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "run_id": os.getenv("GITHUB_RUN_ID") or f"local-{uuid4().hex[:12]}",
        "workflow_name": workflow_name,
        "git_sha": git_sha(),
        "started_at": started_at or now,
        "completed_at": now,
        "python_version": platform.python_version(),
        "dependency_hash": dependency_hash(),
        "dataset_hash": dataset_hash,
        "experiment_ids": list(experiment_ids),
        "artifacts": list(artifacts),
        "result": result,
    }


def write_manifest(manifest: dict[str, Any], path: str) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    return str(target)
