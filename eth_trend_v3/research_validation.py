from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import timedelta
from typing import Any, Iterable, Mapping

from .research_contract import parse_utc


class ResearchValidationError(ValueError):
    pass


@dataclass(frozen=True)
class FoldReport:
    fold: int
    test_start: str
    test_end: str
    train_before: int
    purged_count: int
    purged_ratio: float
    embargo_removed_count: int
    train_after: int
    test_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _times(row: Mapping[str, Any]):
    feature_time = parse_utc(row.get("feature_time", row.get("timestamp")))
    label_end = parse_utc(row.get("label_end_time", row.get("future_timestamp")))
    return feature_time, label_end


def purged_walk_forward(
    rows: Iterable[Mapping[str, Any]],
    *,
    min_train: int,
    test_size: int,
    embargo_hours: float = 0.0,
) -> list[dict[str, Any]]:
    if min_train <= 0 or test_size <= 0:
        raise ValueError("min_train and test_size must be positive")
    if embargo_hours < 0:
        raise ValueError("embargo_hours cannot be negative")

    ordered = [dict(r) for r in rows]
    ordered.sort(key=lambda r: _times(r)[0])
    folds: list[dict[str, Any]] = []

    for fold_no, start in enumerate(range(min_train, len(ordered), test_size), start=1):
        end = min(len(ordered), start + test_size)
        test = ordered[start:end]
        if not test:
            continue
        test_start = _times(test[0])[0]
        test_end = _times(test[-1])[0]
        train_before = ordered[:start]

        purged = [r for r in train_before if _times(r)[1] < test_start]
        purged_count = len(train_before) - len(purged)

        cutoff = test_start - timedelta(hours=embargo_hours)
        train = [r for r in purged if _times(r)[0] < cutoff]
        embargo_removed = len(purged) - len(train)

        if any(_times(r)[1] >= test_start for r in train):
            raise ResearchValidationError("purge invariant violated: training label overlaps test")
        if embargo_hours and any(_times(r)[0] >= cutoff for r in train):
            raise ResearchValidationError("embargo invariant violated")

        report = FoldReport(
            fold=fold_no,
            test_start=test_start.isoformat(),
            test_end=test_end.isoformat(),
            train_before=len(train_before),
            purged_count=purged_count,
            purged_ratio=(purged_count / len(train_before)) if train_before else 0.0,
            embargo_removed_count=embargo_removed,
            train_after=len(train),
            test_count=len(test),
        )
        folds.append({"train": train, "test": test, "report": report.to_dict()})
    return folds


def assert_no_label_overlap(train: Iterable[Mapping[str, Any]], test_start: Any) -> None:
    boundary = parse_utc(test_start)
    bad = [r for r in train if _times(r)[1] >= boundary]
    if bad:
        raise ResearchValidationError(f"{len(bad)} training labels overlap test boundary")
