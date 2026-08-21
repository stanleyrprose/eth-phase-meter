from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional

@dataclass
class Metric:
    value: Optional[float]
    source: str
    observed_at: datetime
    status: str = 'GOOD'
    max_age_seconds: int = 3600
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def age_seconds(self) -> float:
        return max(0.0, (datetime.now(timezone.utc) - self.observed_at).total_seconds())

    @property
    def usable(self) -> bool:
        return self.value is not None and self.status in {'GOOD', 'FALLBACK'} and self.age_seconds <= self.max_age_seconds

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d['observed_at'] = self.observed_at.isoformat()
        d['age_seconds'] = round(self.age_seconds, 1)
        d['usable'] = self.usable
        return d

@dataclass
class Factor:
    family: str
    name: str
    weight: float
    value: Optional[float]
    contribution: float
    source: str = ''
    status: str = 'GOOD'

    @property
    def active(self) -> bool:
        return self.value is not None and self.status in {'GOOD', 'FALLBACK'}

@dataclass
class SnapshotResult:
    timeframe: str
    timestamp: str
    price: float
    final_direction: int
    available_bias: int
    coverage: float
    confidence: str
    crowding: int
    volatility: int
    regime: str
    state: str
    state_explanation: str
    factors: list[Factor]
    quality: dict[str, Any]
    execution_gate: str = 'N/A'
    execution_reason: str = ''

    def to_dict(self) -> dict[str, Any]:
        return {
            **{k: v for k, v in asdict(self).items() if k != 'factors'},
            'factors': [asdict(f) for f in self.factors],
        }
