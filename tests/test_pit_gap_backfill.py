from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
from zipfile import ZipFile

import pytest

from scripts.backfill_pit_gap import (
    Candidate,
    canonical_digest,
    extract_pit_payloads,
    identity_for,
    observed_at_in_gap,
    plan_candidates,
    validate_candidate,
)


START = datetime(2026, 9, 21, 6, 24, 30, 823993, tzinfo=timezone.utc)
END = datetime(2026, 9, 22, 23, 58, 23, 190352, tzinfo=timezone.utc)


def payload(run_id=123, timeframe="1h", observed="2026-09-21T13:51:22+00:00"):
    return {
        "observed_at": observed,
        "event_time": "2026-09-21 13:51 UTC",
        "raw_payload_hash": "a" * 64,
        "metric_value": {"timeframe": timeframe, "price": 2700.0},
        "workflow_run_id": run_id,
        "workflow_name": "ETH Tactical 1H",
        "git_commit_sha": "b" * 40,
        "quality_flags": {"external_persisted": False},
    }


def candidate(value: dict, run_id=123) -> Candidate:
    tf, raw_hash, observed = validate_candidate(
        payload=value,
        run_id=run_id,
        run_head_sha="b" * 40,
        workflow="tactical-1h.yml",
        start=START,
        end=END,
    )
    return Candidate(
        run_id=run_id,
        workflow="tactical-1h.yml",
        run_created_at=observed.isoformat(),
        run_head_sha="b" * 40,
        artifact_id=1,
        artifact_name="eth-tactical-1h-test",
        artifact_path=f"pit/pit_{tf}_x.json",
        timeframe=tf,
        observed_at=observed.isoformat(),
        schedule_nominal_time=None,
        raw_payload_hash=raw_hash,
        payload_digest=canonical_digest(value),
        original_external_persisted=False,
        payload=value,
    )


def test_extracts_only_non_latest_pit_payloads():
    blob = BytesIO()
    with ZipFile(blob, "w") as archive:
        archive.writestr("bundle/pit/pit_1h_2026.json", json.dumps(payload()))
        archive.writestr("bundle/pit/pit_1h_latest.json", json.dumps(payload()))
        archive.writestr("bundle/v3_snapshot_1h.json", json.dumps(payload()))
    found = extract_pit_payloads(blob.getvalue())
    assert [name for name, _ in found] == ["bundle/pit/pit_1h_2026.json"]


def test_identity_uses_run_timeframe_and_normalized_observed_at():
    assert identity_for(payload()) == (
        "123",
        "1h",
        "2026-09-21T13:51:22+00:00",
    )


def test_validation_rejects_mismatched_run_id():
    with pytest.raises(ValueError, match="workflow_run_id"):
        validate_candidate(
            payload=payload(run_id=999),
            run_id=123,
            run_head_sha="b" * 40,
            workflow="tactical-1h.yml",
            start=START,
            end=END,
        )


def test_validation_rejects_outside_gap():
    with pytest.raises(ValueError, match="outside"):
        validate_candidate(
            payload=payload(observed="2026-09-23T00:00:00Z"),
            run_id=123,
            run_head_sha="b" * 40,
            workflow="tactical-1h.yml",
            start=START,
            end=END,
        )


def test_plan_is_idempotent_against_existing_identity():
    c = candidate(payload())
    insertable, existing, duplicates = plan_candidates(
        [c],
        existing_identities={c.identity},
        existing_digests=set(),
    )
    assert insertable == []
    assert len(existing) == 1
    assert duplicates == []


def test_plan_deduplicates_same_candidate_inside_artifacts():
    c = candidate(payload())
    insertable, existing, duplicates = plan_candidates(
        [c, c],
        existing_identities=set(),
        existing_digests=set(),
    )
    assert len(insertable) == 1
    assert existing == []
    assert len(duplicates) == 1


def test_identity_accepts_numeric_string_run_id():
    value = payload(run_id="123")
    assert identity_for(value)[0] == "123"


def test_gap_boundaries_are_ignored_not_validated():
    at_start = payload(observed="2026-09-21T06:24:30.823993Z")
    at_end = payload(observed="2026-09-22T23:58:23.190352Z")
    inside = payload(observed="2026-09-22T23:58:23.000000Z")

    assert observed_at_in_gap(at_start, start=START, end=END) is None
    assert observed_at_in_gap(at_end, start=START, end=END) is None
    assert observed_at_in_gap(inside, start=START, end=END) is not None
