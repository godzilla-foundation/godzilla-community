#!/usr/bin/env python3
import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

METRICS = ["md_to_order_input_ns", "order_report_ns", "total_tick_to_trade_ns"]
DEFAULT_METRIC = "total_tick_to_trade_ns"


def to_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def percentile(values: List[float], pct: float) -> Optional[float]:
    if not values:
        return None
    values = sorted(values)
    if len(values) == 1:
        return values[0]
    pos = (len(values) - 1) * pct / 100.0
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return values[lo]
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def run_joined_paths(runs_dir: Path) -> List[Tuple[str, Path]]:
    return [(path.parent.name, path) for path in sorted(runs_dir.glob("run_*/joined_latency_journal.csv"))]


def read_rows(joined: Optional[Path], runs_dir: Optional[Path]) -> List[Dict[str, Any]]:
    paths: List[Tuple[str, Path]] = []
    if runs_dir is not None:
        paths = run_joined_paths(runs_dir)
    elif joined is not None:
        paths = [(joined.parent.name or "run", joined)]
    rows: List[Dict[str, Any]] = []
    for run_id, path in paths:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                row = dict(row)
                row["source_run_id"] = run_id
                row["source_path"] = str(path)
                rows.append(row)
    return rows


def numeric_values(rows: List[Dict[str, Any]], metric: str) -> List[float]:
    return [value for value in (to_float(row.get(metric)) for row in rows) if value is not None]


def stage_dominance(row: Dict[str, Any]) -> str:
    md = to_float(row.get("md_to_order_input_ns")) or 0.0
    order = to_float(row.get("order_report_ns")) or 0.0
    if md >= order:
        return "md_to_order_input_ns"
    return "order_report_ns"


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: List[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def summarize_tail(rows: List[Dict[str, Any]], metric: str, thresholds: Dict[str, float]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}
    for label, threshold in thresholds.items():
        tail = [row for row in rows if (to_float(row.get(metric)) or -math.inf) >= threshold]
        dominant_counts: Dict[str, int] = {}
        join_depth_counts: Dict[str, int] = {}
        join_order_counts: Dict[str, int] = {}
        runs: Dict[str, int] = {}
        stage_means: Dict[str, Optional[float]] = {}
        for row in tail:
            dominant = stage_dominance(row)
            dominant_counts[dominant] = dominant_counts.get(dominant, 0) + 1
            depth_method = str(row.get("join_depth_method", ""))
            order_method = str(row.get("join_order_method", ""))
            run_id = str(row.get("source_run_id", ""))
            join_depth_counts[depth_method] = join_depth_counts.get(depth_method, 0) + 1
            join_order_counts[order_method] = join_order_counts.get(order_method, 0) + 1
            runs[run_id] = runs.get(run_id, 0) + 1
        for stage_metric in METRICS:
            values = numeric_values(tail, stage_metric)
            stage_means[stage_metric] = None if not values else sum(values) / len(values)
        summary[label] = {
            "threshold_ns": threshold,
            "threshold_us": threshold / 1000.0,
            "row_count": len(tail),
            "dominant_stage_counts": dominant_counts,
            "join_depth_counts": join_depth_counts,
            "join_order_counts": join_order_counts,
            "run_counts": runs,
            "stage_mean_ns": stage_means,
        }
    return summary


def parse_percentiles(value: str) -> List[float]:
    return [float(item.strip()) for item in value.split(",") if item.strip()]


def pct_label(pct: float) -> str:
    return f"p{str(pct).rstrip('0').rstrip('.')}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Export and summarize tail latency rows from joined benchmark CSVs")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--joined", type=Path, help="Single joined_latency_journal.csv")
    source.add_argument("--runs-dir", type=Path, help="Directory containing run_*/joined_latency_journal.csv")
    parser.add_argument("--metric", default=DEFAULT_METRIC)
    parser.add_argument("--percentiles", default="99,99.9", help="Comma-separated tail percentiles")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--top", type=int, default=50, help="Number of slowest rows to export")
    args = parser.parse_args()

    rows = read_rows(args.joined, args.runs_dir)
    values = numeric_values(rows, args.metric)
    if not rows:
        raise SystemExit("no joined rows found")
    if not values:
        raise SystemExit(f"no numeric values found for metric {args.metric}")

    out_dir = args.out_dir or ((args.runs_dir or args.joined.parent) / "tail")
    out_dir.mkdir(parents=True, exist_ok=True)
    thresholds = {pct_label(pct): percentile(values, pct) for pct in parse_percentiles(args.percentiles)}
    thresholds = {key: value for key, value in thresholds.items() if value is not None}

    summary = summarize_tail(rows, args.metric, thresholds)
    for label, threshold in thresholds.items():
        tail_rows = [row for row in rows if (to_float(row.get(args.metric)) or -math.inf) >= threshold]
        tail_rows.sort(key=lambda row: to_float(row.get(args.metric)) or -math.inf, reverse=True)
        for row in tail_rows:
            row["tail_metric"] = args.metric
            row["tail_threshold"] = label
            row["dominant_stage"] = stage_dominance(row)
        write_csv(out_dir / f"{args.metric}_{label}_rows.csv", tail_rows)

    top_rows = sorted(rows, key=lambda row: to_float(row.get(args.metric)) or -math.inf, reverse=True)[: args.top]
    for row in top_rows:
        row["tail_metric"] = args.metric
        row["dominant_stage"] = stage_dominance(row)
    write_csv(out_dir / f"{args.metric}_top{args.top}.csv", top_rows)

    summary_path = out_dir / f"{args.metric}_tail_summary.json"
    payload = {"metric": args.metric, "row_count": len(rows), "summary": summary}
    summary_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"rows: {len(rows)}")
    print(f"metric: {args.metric}")
    for label, threshold in thresholds.items():
        print(f"{label}: threshold={threshold}ns rows={summary[label]['row_count']}")
    print(f"summary_json: {summary_path}")
    print(f"top_csv: {out_dir / f'{args.metric}_top{args.top}.csv'}")


if __name__ == "__main__":
    main()
