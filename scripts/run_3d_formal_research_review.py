from __future__ import annotations

import json
import os
from pathlib import Path

from eth_trend_v3.dataset import load_pit_records
from eth_trend_v3.formal_3d_review import run_formal_3d_review


def _summary_markdown(report: dict) -> str:
    lines = [
        "# ETH 3D Formal Research Review",
        "",
        f"- Status: **{report['status']}**",
        f"- Next action: **{report['next_action']}**",
        f"- Canonical 4h PIT: {report['data']['canonical_4h_records']}",
        f"- Labeled 3D rows: {report['data']['labeled_3d_rows']}",
        f"- Purged OOS rows: {report['folds']['oos_n']}",
        f"- Conservative non-overlap diagnostic: {report['folds']['effective_sample_diagnostic']['conservative_nonoverlap_n']}",
        f"- Dynamic baseline: {report['selected_dynamic_baseline']}",
        f"- Passing candidates: {', '.join(report['passing_candidates']) if report['passing_candidates'] else 'none'}",
        "",
        "## Purge / leakage evidence",
        "",
    ]
    for item in report["folds"]["reports"]:
        lines.append(
            f"- Fold {item['fold']}: train {item['train_before']} -> {item['train_after']}, "
            f"purged {item['purged_count']} ({item['purged_ratio']:.1%}), test {item['test_count']}"
        )

    lines += ["", "## Candidate summary", ""]
    baseline = report["selected_dynamic_baseline"]
    for name, result in report["candidates"].items():
        metrics = result.get("metrics") or {}
        lines.append(
            f"- {name}: available={result.get('available', False)}, "
            f"Brier={metrics.get('brier')}, BSS={metrics.get('brier_skill')}, "
            f"OOS={metrics.get('oos_n')}, pass={result.get('passes_incremental_gate', False)}"
        )

    lines += [
        "",
        "## Governance",
        "",
        "- Production eligible: false",
        "- Shadow activation: false",
        "- Paper/live execution: false",
        "",
        "This artifact uses Purged Walk-Forward + 4h embargo and 3D=18-bar moving-block sensitivity.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    records = load_pit_records(os.getenv("DATABASE_URL"))
    if not records:
        raise SystemExit("No durable PIT records available")

    report = run_formal_3d_review(records)
    root = Path("eth_reports/forecast-research/3d-formal-review")
    root.mkdir(parents=True, exist_ok=True)
    (root / "review.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    (root / "review.md").write_text(_summary_markdown(report), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
