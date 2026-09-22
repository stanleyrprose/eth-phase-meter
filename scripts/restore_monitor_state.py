from __future__ import annotations

import argparse
from io import BytesIO
import json
import os
from pathlib import Path
from zipfile import ZipFile

import requests


WORKFLOWS = {
    "strategic": ("scheduled-monitor.yml", "eth-monitor-"),
    "tactical": ("tactical-1h.yml", "eth-tactical-1h-"),
}
ALLOWED_FILES = {
    "strategic": {"latest_monitor.json", "v3_snapshot_4h.json", "v3_snapshot_1h.json"},
    "tactical": {"latest_tactical_1h.json", "v3_snapshot_1h.json"},
}


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _extract_jsons(blob: bytes, destination: Path, allowed: set[str]) -> list[str]:
    destination.mkdir(parents=True, exist_ok=True)
    restored: list[str] = []
    with ZipFile(BytesIO(blob)) as archive:
        for member in archive.infolist():
            name = Path(member.filename).name
            if not name or name not in allowed:
                continue
            target = destination / name
            target.write_bytes(archive.read(member))
            restored.append(name)
    return sorted(set(restored))


def restore_kind(
    session: requests.Session,
    *,
    repo: str,
    kind: str,
    token: str,
    output_dir: Path,
    api_url: str = "https://api.github.com",
) -> dict:
    workflow, artifact_prefix = WORKFLOWS[kind]
    headers = _headers(token)
    runs_url = f"{api_url}/repos/{repo}/actions/workflows/{workflow}/runs"
    response = session.get(
        runs_url,
        params={"branch": "main", "status": "success", "per_page": 10},
        headers=headers,
        timeout=20,
    )
    response.raise_for_status()

    for run in response.json().get("workflow_runs", []):
        run_id = run.get("id")
        if not run_id:
            continue
        artifacts_url = f"{api_url}/repos/{repo}/actions/runs/{run_id}/artifacts"
        artifacts_response = session.get(artifacts_url, headers=headers, timeout=20)
        artifacts_response.raise_for_status()
        artifacts = [
            item
            for item in artifacts_response.json().get("artifacts", [])
            if not item.get("expired") and str(item.get("name") or "").startswith(artifact_prefix)
        ]
        if not artifacts:
            continue

        artifact = artifacts[0]
        download = session.get(artifact["archive_download_url"], headers=headers, timeout=30)
        download.raise_for_status()
        restored = _extract_jsons(download.content, output_dir / kind, ALLOWED_FILES[kind])
        if restored:
            return {
                "status": "RESTORED",
                "kind": kind,
                "run_id": run_id,
                "artifact_id": artifact.get("id"),
                "files": restored,
            }

    return {"status": "NOT_FOUND", "kind": kind, "files": []}


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore latest successful monitor state from GitHub artifacts.")
    parser.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY"))
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN"))
    parser.add_argument("--output-dir", default=".state")
    args = parser.parse_args()

    if not args.repo or not args.token:
        print(json.dumps({"status": "SKIPPED", "reason": "GITHUB_CONTEXT_MISSING"}))
        return 0

    session = requests.Session()
    reports = [
        restore_kind(
            session,
            repo=args.repo,
            kind=kind,
            token=args.token,
            output_dir=Path(args.output_dir),
        )
        for kind in ("strategic", "tactical")
    ]
    print(json.dumps({"status": "OK", "reports": reports}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
