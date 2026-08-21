"""GitHub Actions entrypoint for ETH Direction Model v2.1."""
from actions_scoring_patch import apply as apply_data_fixes
apply_data_fixes()

import eth_phase_meter as meter
import github_actions_runner as market_fallback
meter.fetch_binance_klines = market_fallback.fetch_market_klines
meter.fetch_binance_derivatives = market_fallback.fetch_derivatives

from actions_directional_v2 import apply as apply_directional_v2
apply_directional_v2()

from actions_directional_v2_runtimefix import apply as apply_runtime_fixes
apply_runtime_fixes()

from actions_directional_v21 import apply as apply_directional_v21
apply_directional_v21()

if __name__ == "__main__":
    meter.main()
