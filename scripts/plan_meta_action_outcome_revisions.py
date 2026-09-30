#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os
from pathlib import Path
from eth_trend_v3.meta_action_outcomes import (
    build_due_meta_action_outcomes,
    load_meta_action_events,
    load_meta_action_outcomes,
)
from eth_trend_v3.tactical_outcomes import load_tactical_price_records

CORRECTION_REASON = "PATH_CADENCE_4H_CONTRACT"

def plan_revisions(events, base_outcomes, pit_records, *, source_git_sha):
    recomputed = build_due_meta_action_outcomes(events, pit_records, existing_keys=set())
    by_key = {(str(x["event_id"]), int(x["horizon_hours"])): x for x in recomputed}
    candidates, skipped = [], []
    for base in base_outcomes:
        key = (str(base.get("event_id")), int(base.get("horizon_hours") or 0))
        corrected = by_key.get(key)
        if corrected is None:
            skipped.append({
                "event_id": key[0], "horizon_hours": key[1],
                "reason_code": "MISSING_SOURCE_PIT",
            })
            continue
        changed = {
            field: {"base": base.get(field), "corrected": corrected.get(field)}
            for field in ("path_complete", "path_bars", "expected_path_bars", "mae", "mfe")
            if base.get(field) != corrected.get(field)
        }
        if not changed:
            continue
        if not corrected.get("path_complete"):
            skipped.append({
                "event_id": key[0], "horizon_hours": key[1],
                "reason_code": "INCOMPLETE_CANONICAL_PATH",
                "missing_path_nominal_times": corrected.get("missing_path_nominal_times") or [],
            })
            continue
        candidates.append({
            "event_id": key[0],
            "horizon_hours": key[1],
            "correction_reason": CORRECTION_REASON,
            "source_git_sha": source_git_sha,
            "changes": changed,
            "payload": corrected,
        })
    return {
        "status": "DRY_RUN",
        "research_only": True,
        "apply": False,
        "correction_reason": CORRECTION_REASON,
        "source_git_sha": source_git_sha,
        "base_outcome_count": len(base_outcomes),
        "candidate_count": len(candidates),
        "skipped_count": len(skipped),
        "candidates": candidates,
        "skipped": skipped,
        "guardrails": {
            "base_outcomes_mutated": False,
            "interpolation_allowed": False,
            "nearest_value_substitution_allowed": False,
            "incomplete_path_revision_allowed": False,
        },
    }

def main():
    p=argparse.ArgumentParser(description="Plan append-only Meta Action outcome revisions.")
    p.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    p.add_argument("--source-git-sha", default=os.getenv("GITHUB_SHA"))
    p.add_argument("--report", default="eth_reports/governance/meta_action_outcome_revision_plan.json")
    a=p.parse_args()
    if not a.database_url: raise SystemExit("DATABASE_URL is required")
    if not a.source_git_sha: raise SystemExit("--source-git-sha or GITHUB_SHA is required")
    report=plan_revisions(
        load_meta_action_events(a.database_url),
        load_meta_action_outcomes(a.database_url),
        load_tactical_price_records(a.database_url),
        source_git_sha=a.source_git_sha,
    )
    target=Path(a.report); target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps(report,indent=2,sort_keys=True))
if __name__=="__main__": main()
