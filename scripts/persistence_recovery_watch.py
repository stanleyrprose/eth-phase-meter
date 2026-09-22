from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from scripts.database_preflight import DatabaseHealth, check_database


@dataclass(frozen=True)
class RecoveryDecision:
    checked_at: str
    transition: str
    recovered: bool
    previous_available: bool | None
    previous_reason: str | None
    health: DatabaseHealth

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked_at": self.checked_at,
            "transition": self.transition,
            "recovered": self.recovered,
            "previous_available": self.previous_available,
            "previous_reason": self.previous_reason,
            "health": asdict(self.health),
        }


def _read_previous(path: str | Path | None) -> tuple[bool | None, str | None]:
    if not path:
        return None, None
    target = Path(path)
    if not target.exists():
        return None, None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return None, None

    health = payload.get("health") if isinstance(payload, dict) else None
    if not isinstance(health, dict):
        return None, None

    available = health.get("available")
    if not isinstance(available, bool):
        return None, None
    reason = health.get("reason")
    return available, str(reason) if reason is not None else None


def evaluate_recovery(
    *,
    current: DatabaseHealth,
    previous_available: bool | None,
    previous_reason: str | None = None,
    now: datetime | None = None,
) -> RecoveryDecision:
    if previous_available is None:
        transition = "BASELINE"
    elif not previous_available and current.available:
        transition = "RECOVERED"
    elif previous_available and not current.available:
        transition = "DEGRADED"
    else:
        transition = "UNCHANGED"

    return RecoveryDecision(
        checked_at=(now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
        transition=transition,
        recovered=transition == "RECOVERED",
        previous_available=previous_available,
        previous_reason=previous_reason,
        health=current,
    )


def _append_github_output(path: str | None, decision: RecoveryDecision) -> None:
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"recovered={'true' if decision.recovered else 'false'}\n")
        handle.write(f"available={'true' if decision.health.available else 'false'}\n")
        handle.write(f"transition={decision.transition}\n")
        handle.write(f"reason={decision.health.reason}\n")
        handle.write(f"previous_reason={decision.previous_reason or ''}\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect PostgreSQL recovery without depending on PostgreSQL for watch state."
    )
    parser.add_argument("--previous-state")
    parser.add_argument("--state-output", default="postgres-recovery-state.json")
    parser.add_argument("--github-output", default=os.getenv("GITHUB_OUTPUT"))
    args = parser.parse_args()

    previous_available, previous_reason = _read_previous(args.previous_state)
    current = check_database(os.getenv("DATABASE_URL"))
    decision = evaluate_recovery(
        current=current,
        previous_available=previous_available,
        previous_reason=previous_reason,
    )

    target = Path(args.state_output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(decision.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _append_github_output(args.github_output, decision)
    print(json.dumps(decision.to_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
