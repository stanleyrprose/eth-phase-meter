from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import PurePosixPath, Path
import re
from typing import Any, Iterable
from zipfile import ZipFile

import requests


WORKFLOWS = {
    "scheduled-monitor.yml": "eth-monitor-",
    "tactical-1h.yml": "eth-tactical-1h-",
}
PIT_NAME = re.compile(r"^pit_(1h|4h)_.*\.json$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def parse_utc(value: str) -> datetime:
    text = str(value).strip().replace(" UTC", "+00:00")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def canonical_digest(payload: dict[str, Any]) -> str:
    body = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return sha256(body).hexdigest()


def observed_at_in_gap(
    payload: dict[str, Any],
    *,
    start: datetime,
    end: datetime,
) -> datetime | None:
    value = payload.get("observed_at")
    if not value:
        raise ValueError("observed_at is required")
    observed = parse_utc(str(value))
    return observed if start < observed < end else None


def identity_for(payload: dict[str, Any]) -> tuple[str, str, str]:
    run_id = payload.get("workflow_run_id")
    timeframe = (payload.get("metric_value") or {}).get("timeframe")
    observed_at = payload.get("observed_at")
    if isinstance(run_id, bool) or not (
        isinstance(run_id, int)
        or (isinstance(run_id, str) and run_id.isdigit())
    ):
        raise ValueError("workflow_run_id must be an integer or numeric string")
    if timeframe not in {"1h", "4h"}:
        raise ValueError("metric_value.timeframe must be 1h or 4h")
    if not observed_at:
        raise ValueError("observed_at is required")
    normalized = parse_utc(str(observed_at)).isoformat()
    return str(int(run_id)), str(timeframe), normalized


@dataclass(frozen=True)
class Candidate:
    run_id: int
    workflow: str
    run_created_at: str
    run_head_sha: str
    artifact_id: int
    artifact_name: str
    artifact_path: str
    timeframe: str
    observed_at: str
    schedule_nominal_time: str | None
    raw_payload_hash: str
    payload_digest: str
    original_external_persisted: bool | None
    payload: dict[str, Any]

    @property
    def identity(self) -> tuple[str, str, str]:
        return identity_for(self.payload)

    def report_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("payload", None)
        value["identity"] = list(self.identity)
        return value


def extract_pit_payloads(blob: bytes) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    with ZipFile(BytesIO(blob)) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            path = PurePosixPath(member.filename)
            if "pit" not in path.parts:
                continue
            name = path.name
            if name.endswith("_latest.json") or not PIT_NAME.match(name):
                continue
            payload = json.loads(archive.read(member).decode("utf-8"))
            if isinstance(payload, dict):
                out.append((member.filename, payload))
    return out


def validate_candidate(
    *,
    payload: dict[str, Any],
    run_id: int,
    run_head_sha: str,
    workflow: str,
    start: datetime,
    end: datetime,
) -> tuple[str, str, datetime]:
    identity = identity_for(payload)
    if int(identity[0]) != int(run_id):
        raise ValueError("artifact workflow_run_id does not match GitHub run id")
    observed = parse_utc(identity[2])
    if not (start < observed < end):
        raise ValueError("observed_at is outside the closed backfill gap")
    payload_sha = str(payload.get("git_commit_sha") or "")
    if payload_sha and payload_sha != run_head_sha:
        raise ValueError("artifact git_commit_sha does not match GitHub run head_sha")
    raw_hash = str(payload.get("raw_payload_hash") or "")
    if not HEX64.match(raw_hash):
        raise ValueError("raw_payload_hash is missing or invalid")
    expected_workflow_name = {
        "scheduled-monitor.yml": "ETH Scheduled Monitor",
        "tactical-1h.yml": "ETH Tactical 1H",
    }[workflow]
    if payload.get("workflow_name") not in {None, expected_workflow_name}:
        raise ValueError("artifact workflow_name does not match workflow")
    return identity[1], raw_hash, observed


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def list_successful_runs(
    session: requests.Session,
    *,
    repo: str,
    workflow: str,
    token: str,
    start: datetime,
    end: datetime,
    api_url: str = "https://api.github.com",
) -> list[dict[str, Any]]:
    headers = _headers(token)
    expanded_start = start - timedelta(minutes=15)
    expanded_end = end + timedelta(minutes=15)
    selected: list[dict[str, Any]] = []
    for page in range(1, 6):
        response = session.get(
            f"{api_url}/repos/{repo}/actions/workflows/{workflow}/runs",
            params={
                "branch": "main",
                "status": "success",
                "per_page": 100,
                "page": page,
            },
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        runs = response.json().get("workflow_runs", [])
        if not runs:
            break
        oldest: datetime | None = None
        for run in runs:
            created = parse_utc(run["created_at"])
            oldest = created if oldest is None or created < oldest else oldest
            if expanded_start < created < expanded_end:
                selected.append(run)
        if oldest is not None and oldest <= expanded_start:
            break
    return sorted(selected, key=lambda r: (r["created_at"], r["id"]))


def collect_candidates(
    session: requests.Session,
    *,
    repo: str,
    token: str,
    start: datetime,
    end: datetime,
    api_url: str = "https://api.github.com",
) -> tuple[list[Candidate], list[dict[str, Any]], dict[str, int]]:
    headers = _headers(token)
    candidates: list[Candidate] = []
    errors: list[dict[str, Any]] = []
    counters = {
        "successful_runs": 0,
        "artifacts_examined": 0,
        "pit_files_examined": 0,
        "pit_files_outside_window": 0,
    }

    for workflow, prefix in WORKFLOWS.items():
        runs = list_successful_runs(
            session,
            repo=repo,
            workflow=workflow,
            token=token,
            start=start,
            end=end,
            api_url=api_url,
        )
        counters["successful_runs"] += len(runs)
        for run in runs:
            run_id = int(run["id"])
            artifacts_response = session.get(
                f"{api_url}/repos/{repo}/actions/runs/{run_id}/artifacts",
                headers=headers,
                timeout=30,
            )
            artifacts_response.raise_for_status()
            artifacts = [
                item
                for item in artifacts_response.json().get("artifacts", [])
                if not item.get("expired")
                and str(item.get("name") or "").startswith(prefix)
            ]
            for artifact in artifacts:
                counters["artifacts_examined"] += 1
                download = session.get(
                    artifact["archive_download_url"],
                    headers=headers,
                    timeout=60,
                )
                download.raise_for_status()
                for artifact_path, payload in extract_pit_payloads(download.content):
                    counters["pit_files_examined"] += 1
                    try:
                        observed = observed_at_in_gap(payload, start=start, end=end)
                        if observed is None:
                            counters["pit_files_outside_window"] += 1
                            continue
                        timeframe, raw_hash, observed = validate_candidate(
                            payload=payload,
                            run_id=run_id,
                            run_head_sha=str(run.get("head_sha") or ""),
                            workflow=workflow,
                            start=start,
                            end=end,
                        )
                    except Exception as exc:
                        errors.append(
                            {
                                "run_id": run_id,
                                "workflow": workflow,
                                "artifact_id": artifact.get("id"),
                                "artifact_path": artifact_path,
                                "error": f"{type(exc).__name__}: {exc}",
                            }
                        )
                        continue
                    candidates.append(
                        Candidate(
                            run_id=run_id,
                            workflow=workflow,
                            run_created_at=parse_utc(run["created_at"]).isoformat(),
                            run_head_sha=str(run.get("head_sha") or ""),
                            artifact_id=int(artifact["id"]),
                            artifact_name=str(artifact["name"]),
                            artifact_path=artifact_path,
                            timeframe=timeframe,
                            observed_at=observed.isoformat(),
                            schedule_nominal_time=payload.get("schedule_nominal_time"),
                            raw_payload_hash=raw_hash,
                            payload_digest=canonical_digest(payload),
                            original_external_persisted=(payload.get("quality_flags") or {}).get(
                                "external_persisted"
                            ),
                            payload=payload,
                        )
                    )

    candidates.sort(key=lambda c: (c.observed_at, c.run_id, c.timeframe))
    return candidates, errors, counters


def existing_pit_state(conn) -> tuple[set[tuple[str, str, str]], set[str]]:
    identities: set[tuple[str, str, str]] = set()
    digests: set[str] = set()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT payload FROM eth_monitor_records "
            "WHERE record_type='pit_snapshot' ORDER BY created_at"
        )
        for (payload,) in cur.fetchall():
            if not isinstance(payload, dict):
                continue
            try:
                identities.add(identity_for(payload))
            except Exception:
                pass
            digests.add(canonical_digest(payload))
    return identities, digests


def plan_candidates(
    candidates: Iterable[Candidate],
    *,
    existing_identities: set[tuple[str, str, str]],
    existing_digests: set[str],
) -> tuple[list[Candidate], list[dict[str, Any]], list[dict[str, Any]]]:
    insertable: list[Candidate] = []
    existing: list[dict[str, Any]] = []
    duplicate_candidates: list[dict[str, Any]] = []
    seen_identities: set[tuple[str, str, str]] = set()
    seen_digests: set[str] = set()

    for candidate in candidates:
        identity = candidate.identity
        if identity in existing_identities or candidate.payload_digest in existing_digests:
            existing.append(candidate.report_dict())
            continue
        if identity in seen_identities or candidate.payload_digest in seen_digests:
            duplicate_candidates.append(candidate.report_dict())
            continue
        seen_identities.add(identity)
        seen_digests.add(candidate.payload_digest)
        insertable.append(candidate)
    return insertable, existing, duplicate_candidates


def backfill(
    *,
    dsn: str,
    candidates: list[Candidate],
    apply: bool,
) -> tuple[list[Candidate], list[dict[str, Any]], list[dict[str, Any]], list[int]]:
    import psycopg

    with psycopg.connect(dsn) as conn:
        existing_identities, existing_digests = existing_pit_state(conn)
        insertable, existing, duplicate_candidates = plan_candidates(
            candidates,
            existing_identities=existing_identities,
            existing_digests=existing_digests,
        )
        if not apply:
            return insertable, existing, duplicate_candidates, []

        inserted_ids: list[int] = []
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext('eth-pit-gap-backfill'))")
            # Re-read under the backfill advisory lock so repeated apply runs stay idempotent.
            existing_identities, existing_digests = existing_pit_state(conn)
            insertable, existing, duplicate_candidates = plan_candidates(
                candidates,
                existing_identities=existing_identities,
                existing_digests=existing_digests,
            )
            for candidate in insertable:
                cur.execute(
                    "INSERT INTO eth_monitor_records(record_type, created_at, payload) "
                    "VALUES ('pit_snapshot', %s, %s::jsonb) RETURNING id",
                    (
                        parse_utc(candidate.observed_at),
                        json.dumps(candidate.payload, ensure_ascii=False, default=str),
                    ),
                )
                inserted_ids.append(int(cur.fetchone()[0]))
        conn.commit()
        return insertable, existing, duplicate_candidates, inserted_ids


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill a closed PIT gap from immutable GitHub Actions artifacts."
    )
    parser.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY", "stanleyrprose/eth-phase-meter"))
    parser.add_argument("--token", default=os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN"))
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", default="eth_reports/governance/pit_gap_backfill.json")
    args = parser.parse_args()

    if not args.token:
        raise SystemExit("GitHub token is required")
    if not args.database_url:
        raise SystemExit("DATABASE_URL is required")

    start = parse_utc(args.start)
    end = parse_utc(args.end)
    if not start < end:
        raise SystemExit("start must be earlier than end")

    session = requests.Session()
    candidates, errors, counters = collect_candidates(
        session,
        repo=args.repo,
        token=args.token,
        start=start,
        end=end,
    )
    if errors:
        report = {
            "status": "FAIL_CLOSED",
            "apply": args.apply,
            "window": {"start_exclusive": start.isoformat(), "end_exclusive": end.isoformat()},
            "counters": counters,
            "validation_errors": errors,
        }
        target = Path(args.report)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True))
        return 2

    insertable, existing, duplicate_candidates, inserted_ids = backfill(
        dsn=args.database_url,
        candidates=candidates,
        apply=args.apply,
    )
    report = {
        "status": "APPLIED" if args.apply else "DRY_RUN",
        "apply": args.apply,
        "record_type": "pit_snapshot",
        "created_at_policy": "artifact observed_at",
        "payload_policy": "artifact payload preserved byte-semantically; no field rewriting",
        "window": {"start_exclusive": start.isoformat(), "end_exclusive": end.isoformat()},
        "counters": {
            **counters,
            "valid_candidates": len(candidates),
            "already_present": len(existing),
            "duplicate_candidates": len(duplicate_candidates),
            "would_insert": len(insertable),
            "inserted": len(inserted_ids),
        },
        "inserted_ids": inserted_ids,
        "rollback_ids": inserted_ids,
        "candidates_to_insert": [c.report_dict() for c in insertable],
        "already_present_candidates": existing,
        "duplicate_candidates": duplicate_candidates,
        "validation_errors": [],
    }
    target = Path(args.report)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
