from __future__ import annotations

from datetime import datetime, timedelta, timezone

from eth_trend_v3.dataset import canonicalize_pit_records, feature_row
from eth_trend_v3.drift import detect_feature_drift

UTC = timezone.utc
STRUCTURAL_V1 = "structural-supply-v1"
STRUCTURAL_V2 = "structural-supply-v2-staking-queue"


def _row(value: float, version: str) -> dict:
    return {
        "structural_supply": value,
        "_dimension_versions": {"structural_supply": version},
    }


def _pit(stamp: datetime, *, timeframe: str = "4h", event: str = "schedule", queue: bool = True) -> dict:
    components = {"net_issuance_eth": 3000.0, "exchange_balance_change_pct": -0.1}
    if queue:
        components["staking_queue_imbalance_pct"] = 80.0
    return {
        "observed_at": stamp.isoformat(),
        "schedule_nominal_time": stamp.replace(minute=15, second=0, microsecond=0).isoformat(),
        "github_event": event,
        "metric_value": {"timeframe": timeframe, "price": 2500.0},
        "market_state_vector": {
            "dimensions": {
                "structural_supply": {"score": 10.0, "components": components},
            }
        },
        "coverage": 73.0,
        "regime": {"regime": "Low-Vol Sideways"},
    }


def test_feature_drift_does_not_mix_old_schema_into_new_baseline():
    history = [_row(0.0, STRUCTURAL_V1) for _ in range(60)]
    history += [_row(8.0, STRUCTURAL_V2) for _ in range(12)]

    report = detect_feature_drift(
        history,
        {"structural_supply": 30.0},
        keys=["structural_supply"],
        current_versions={"structural_supply": STRUCTURAL_V2},
    )

    assert report == {"status": "NORMAL", "flags": []}


def test_feature_drift_still_fires_after_same_version_has_enough_history():
    history = [_row(0.0, STRUCTURAL_V2) for _ in range(40)]

    report = detect_feature_drift(
        history,
        {"structural_supply": 10.0},
        keys=["structural_supply"],
        current_versions={"structural_supply": STRUCTURAL_V2},
    )

    assert report["status"] == "MODEL_DEGRADED"
    flag = report["flags"][0]
    assert flag["feature"] == "structural_supply"
    assert flag["feature_version"] == STRUCTURAL_V2
    assert flag["baseline_n"] == 40
    assert flag["robust_z"] > 4


def test_legacy_pit_infers_structural_v2_from_staking_queue_component():
    record = _pit(datetime(2026, 8, 28, 8, 15, tzinfo=UTC), queue=True)
    row = feature_row(record)

    assert row is not None
    assert row["_dimension_versions"]["structural_supply"] == STRUCTURAL_V2


def test_canonical_same_timeframe_history_prevents_manual_and_1h_pseudo_depth():
    start = datetime(2026, 8, 20, 0, 15, tzinfo=UTC)
    records = []
    for i in range(12):
        stamp = start + timedelta(hours=4 * i)
        records.append(_pit(stamp, timeframe="4h", event="schedule"))
        records.append(_pit(stamp + timedelta(minutes=5), timeframe="4h", event="workflow_dispatch"))
        records.append(_pit(stamp, timeframe="1h", event="schedule"))

    canonical = canonicalize_pit_records(records, timeframe="4h")
    rows = [feature_row(record) for record in canonical]
    rows = [row for row in rows if row]

    assert len(canonical) == 12
    assert all(row["timeframe"] == "4h" for row in rows)
    report = detect_feature_drift(
        rows,
        {"structural_supply": 50.0},
        keys=["structural_supply"],
        current_versions={"structural_supply": STRUCTURAL_V2},
    )
    assert report["status"] == "NORMAL"
