from pathlib import Path

from eth_trend_v3.hmm_ablation import run

if __name__ == "__main__":
    bootstrap_features = Path("eth_reports/hmm_bootstrap/features.csv")
    report = run(
        days=365,
        features_path=str(bootstrap_features) if bootstrap_features.exists() else None,
    )
    for h, r in report.get("horizons", {}).items():
        if r.get("available"):
            print(f"HMM_ABLATION {h} improvement={r['brier_improvement']:+.6f} gate={r['passes_research_gate']}")
        else:
            print(f"HMM_ABLATION {h} unavailable={r.get('reason')}")
