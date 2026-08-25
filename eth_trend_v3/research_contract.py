from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Mapping


def parse_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace(" UTC", "+00:00").replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class ResearchSample:
    feature_time: datetime
    available_at: datetime
    label_start_time: datetime
    label_end_time: datetime
    horizon: str
    feature_snapshot_id: str | None = None
    dataset_version: str | None = None

    def __post_init__(self) -> None:
        for name in ("feature_time", "available_at", "label_start_time", "label_end_time"):
            object.__setattr__(self, name, parse_utc(getattr(self, name)))
        if not self.horizon:
            raise ValueError("horizon is required")
        if self.available_at < self.feature_time:
            raise ValueError("available_at cannot precede feature_time")
        if self.label_start_time < self.available_at:
            raise ValueError("label_start_time must be at or after available_at")
        if self.label_end_time <= self.label_start_time:
            raise ValueError("label_end_time must be after label_start_time")

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "ResearchSample":
        return cls(
            feature_time=row["feature_time"],
            available_at=row.get("available_at", row["feature_time"]),
            label_start_time=row.get("label_start_time", row.get("feature_time")),
            label_end_time=row["label_end_time"],
            horizon=str(row["horizon"]),
            feature_snapshot_id=row.get("feature_snapshot_id"),
            dataset_version=row.get("dataset_version"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("feature_time", "available_at", "label_start_time", "label_end_time"):
            data[key] = data[key].isoformat()
        return data


def validate_research_row(row: Mapping[str, Any]) -> ResearchSample:
    return ResearchSample.from_mapping(row)
