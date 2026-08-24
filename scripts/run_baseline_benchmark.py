from eth_trend_v3.baseline_benchmark import run

if __name__ == "__main__":
    report = run()
    print("baseline_benchmark_complete", {h: r.get("winner") for h, r in report["horizons"].items()})
