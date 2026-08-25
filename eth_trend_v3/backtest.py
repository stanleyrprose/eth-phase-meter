from __future__ import annotations
import csv
import json
import os
from pathlib import Path
from .dataset import HORIZONS, load_pit_records, build_labeled_rows
from .forecast import expanding_walk_forward
from .ablation import run_ablation
from .correlation import correlation_audit
from .research_feature_groups import group_ablation


def run(output_dir="eth_reports/model_lab"):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    records = load_pit_records(os.getenv("DATABASE_URL"))
    report = {"record_count": len(records), "horizons": {}}
    cal_rows = []
    abl_rows = []

    for horizon, hours in HORIZONS.items():
        rows = build_labeled_rows(records, hours)
        wf = expanding_walk_forward(rows, ["trend"])
        corr = correlation_audit(rows)
        ablation = run_ablation(rows)
        registered_group_ablation = group_ablation(rows)
        report["horizons"][horizon] = {
            **wf,
            "correlation_audit": corr,
            "ablation": ablation,
            "registered_feature_group_ablation": registered_group_ablation,
        }
        for bucket in (wf.get("metrics") or {}).get("calibration", []):
            cal_rows.append({"horizon": horizon, **bucket})
        for item in ablation:
            abl_rows.append({"horizon": horizon, **item})

    (out / "metrics.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    if cal_rows:
        with (out / "calibration.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(cal_rows[0].keys()))
            writer.writeheader()
            writer.writerows(cal_rows)

    if abl_rows:
        fields = [
            "horizon",
            "model",
            "features",
            "available",
            "sample_size",
            "brier",
            "log_loss",
            "brier_lift_vs_base",
            "passes_baseline_gate",
            "incremental_brier",
        ]
        with (out / "ablation.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in abl_rows:
                normalized = dict(row)
                normalized["features"] = "|".join(normalized.get("features") or [])
                writer.writerow(normalized)

    lines = ["# Model Validation Report", "", f"PIT records: {len(records)}", ""]
    for horizon, result in report["horizons"].items():
        lines += [
            f"## {horizon}",
            f"- available: {result.get('available', False)}",
            f"- sample_size: {result.get('sample_size', 0)}",
            f"- reason: {result.get('reason', '')}",
            f"- metrics: `{json.dumps(result.get('metrics', {}), ensure_ascii=False)}`",
            f"- correlated pairs: `{json.dumps((result.get('correlation_audit') or {}).get('pairs', []), ensure_ascii=False)}`",
            f"- ablation: `{json.dumps(result.get('ablation', []), ensure_ascii=False)}`",
            "",
        ]
    (out / "validation_report.md").write_text("\n".join(lines), encoding="utf-8")
    return report
