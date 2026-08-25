from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

STATES = {
    "EXPERIMENTAL", "CANDIDATE", "SHADOW", "PRODUCTION", "DEGRADED", "RETIRED",
    "DESCRIPTIVE_PRODUCTION",
}

ALLOWED_TRANSITIONS = {
    "EXPERIMENTAL": {"CANDIDATE", "RETIRED", "DESCRIPTIVE_PRODUCTION"},
    "CANDIDATE": {"SHADOW", "RETIRED", "EXPERIMENTAL"},
    "SHADOW": {"PRODUCTION", "CANDIDATE", "RETIRED"},
    "PRODUCTION": {"DEGRADED", "SHADOW", "RETIRED"},
    "DEGRADED": {"SHADOW", "CANDIDATE", "RETIRED"},
    "DESCRIPTIVE_PRODUCTION": {"RETIRED", "EXPERIMENTAL"},
    "RETIRED": set(),
}


class InvalidLifecycleTransition(ValueError):
    pass


@dataclass(frozen=True)
class Transition:
    from_state: str
    to_state: str
    reason: str
    trigger: str
    operator_or_system: str
    timestamp: str
    gate_version: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def transition(
    from_state: str,
    to_state: str,
    *,
    reason: str,
    trigger: str = "manual",
    operator_or_system: str = "system",
    gate_version: str = "v1",
) -> Transition:
    if from_state not in STATES or to_state not in STATES:
        raise InvalidLifecycleTransition("unknown lifecycle state")
    if to_state not in ALLOWED_TRANSITIONS[from_state]:
        raise InvalidLifecycleTransition(f"illegal transition: {from_state} -> {to_state}")
    if not reason:
        raise InvalidLifecycleTransition("transition reason is required")
    return Transition(
        from_state=from_state,
        to_state=to_state,
        reason=reason,
        trigger=trigger,
        operator_or_system=operator_or_system,
        timestamp=datetime.now(timezone.utc).isoformat(),
        gate_version=gate_version,
    )
