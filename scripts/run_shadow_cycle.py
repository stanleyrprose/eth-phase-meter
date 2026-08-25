import json
from eth_trend_v3.shadow_runtime import run_shadow_cycle

if __name__ == "__main__":
    print(json.dumps(run_shadow_cycle(), indent=2, default=str))
