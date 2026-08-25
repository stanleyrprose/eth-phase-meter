from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .dataset import HORIZONS, build_labeled_rows, canonicalize_pit_records, pit_history_depth

MIN_WALK_FORWARD_ROWS = 144  # 120 train + 24 first OOS block; research only.


def assess_research_readiness(records: list[dict]) -> dict[str, Any]:
    canonical = canonicalize_pit_records(records, timeframe="4h")
    horizons = {}
    ready = []
    for horizon, hours in HORIZONS.items():
        labeled = build_labeled_rows(canonical, hours, timeframe="4h")
        row_count = len(labeled)
        is_ready = row_count >= MIN_WALK_FORWARD_ROWS
        horizons[horizon] = {
            "canonical_pit_n": len(canonical),
            "labeled_row_n": row_count,
            "minimum_walk_forward_rows": MIN_WALK_FORWARD_ROWS,
            "research_ready": is_ready,
            "production_eligible": False,
        }
        if is_ready:
            ready.append(horizon)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "READY_FOR_RESEARCH" if ready else "WAIT_FOR_MORE_PIT",
        "ready_horizons": ready,
        "run_research_benchmark": bool(ready),
        "automatic_shadow_allowed": False,
        "automatic_production_allowed": False,
        "pit_history_depth": pit_history_depth(records),
        "horizons": horizons,
    }
