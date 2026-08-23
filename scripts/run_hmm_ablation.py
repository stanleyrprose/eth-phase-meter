from eth_trend_v3.hmm_ablation import run

if __name__ == "__main__":
    report = run(days=365)
    for h, r in report.get("horizons", {}).items():
        if r.get("available"):
            print(f"HMM_ABLATION {h} improvement={r['brier_improvement']:+.6f} gate={r['passes_research_gate']}")
        else:
            print(f"HMM_ABLATION {h} unavailable={r.get('reason')}")
