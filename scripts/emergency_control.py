from __future__ import annotations

import argparse
import json

from eth_trend_v3.promotion import emergency_override


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", required=True, choices=["FREEZE", "DEMOTE", "DISABLE_PUBLICATION", "ANNOTATE", "CLEAR"])
    parser.add_argument("--horizon", default="ALL", choices=["ALL", "3d", "7d", "30d"])
    parser.add_argument("--operator", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    event = emergency_override(args.action, operator=args.operator, reason=args.reason, horizon=args.horizon)
    print(json.dumps(event, indent=2, default=str))


if __name__ == "__main__":
    main()
