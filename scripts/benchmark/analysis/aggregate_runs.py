#!/usr/bin/env python3
import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

METRICS = ["md_to_order_input_ns", "order_report_ns", "total_tick_to_trade_ns"]
STAT_FIELDS = ["count", "min_ns", "max_ns", "mean_ns", "p50_ns", "p90_ns", "p99_ns", "p99_9_ns"]


def read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def summarize_values(values: List[float]) -> Dict[str, Optional[float]]:
    if not values:
        return {"min": None, "mean": None, "max": None}
    return {
        "min": min(values),
        "mean": sum(values) / len(values),
        "max": max(values),
    }


def run_id_from_path(path: Path) -> str:
    parent = path.parent.name
    return parent if parent else path.stem


def flatten_run(path: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    metadata = data.get("metadata", {})
    row: Dict[str, Any] = {
        "run_id": run_id_from_path(path),
        "summary_path": str(path),
        "joined_rows": metadata.get("joined_rows"),
        "joined_rows_raw": metadata.get("joined_rows_raw"),
        "skip_first": metadata.get("skip_first"),
        "depth_rows": metadata.get("input_rows", {}).get("depth"),
        "order_input_rows": metadata.get("input_rows", {}).get("order_input"),
        "order_rows": metadata.get("input_rows", {}).get("order"),
        "depth_price_side": metadata.get("join_counts", {}).get("depth_price_side"),
        "depth_time": metadata.get("join_counts", {}).get("depth_time"),
        "depth_unmatched": metadata.get("join_counts", {}).get("depth_unmatched"),
        "order_order_id": metadata.get("join_counts", {}).get("order_order_id"),
        "order_time": metadata.get("join_counts", {}).get("order_time"),
        "order_unmatched": metadata.get("join_counts", {}).get("order_unmatched"),
    }
    metrics = data.get("metrics", {})
    for metric_name in METRICS:
        metric = metrics.get(metric_name, {})
        for field in STAT_FIELDS:
            row[f"{metric_name}.{field}"] = metric.get(field)
    return row


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
        for row in rows:
            writer.writerow(row)


def aggregate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    metric_summary: Dict[str, Any] = {}
    for metric_name in METRICS:
        metric_summary[metric_name] = {}
        for field in ["p50_ns", "p90_ns", "p99_ns", "p99_9_ns", "mean_ns", "max_ns"]:
            key = f"{metric_name}.{field}"
            values = [v for v in (to_float(row.get(key)) for row in rows) if v is not None]
            metric_summary[metric_name][field] = summarize_values(values)
    total_p99_key = "total_tick_to_trade_ns.p99_ns"
    ranked = [row for row in rows if to_float(row.get(total_p99_key)) is not None]
    ranked.sort(key=lambda row: to_float(row.get(total_p99_key)) or math.inf)
    return {
        "run_count": len(rows),
        "metrics": metric_summary,
        "best_run_by_total_p99": ranked[0]["run_id"] if ranked else None,
        "worst_run_by_total_p99": ranked[-1]["run_id"] if ranked else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate benchmark run summary_journal.json files")
    parser.add_argument("--runs-dir", type=Path, default=Path("analysis/output"))
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()

    runs_dir = args.runs_dir
    out_dir = args.out_dir or runs_dir
    paths = sorted(runs_dir.glob("run_*/summary_journal.json"))
    if not paths:
        raise SystemExit(f"no run summaries found under {runs_dir}/run_*/summary_journal.json")

    rows = [flatten_run(path, read_json(path)) for path in paths]
    summary = aggregate(rows)

    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "runs_summary.csv"
    json_path = out_dir / "runs_summary.json"
    write_csv(csv_path, rows)
    json_path.write_text(json.dumps({"summary": summary, "runs": rows}, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    total = summary["metrics"]["total_tick_to_trade_ns"]
    print(f"runs_dir: {runs_dir}")
    print(f"run_count: {summary['run_count']}")
    print(f"runs_csv: {csv_path}")
    print(f"runs_json: {json_path}")
    print(f"best_run_by_total_p99: {summary['best_run_by_total_p99']}")
    print(f"worst_run_by_total_p99: {summary['worst_run_by_total_p99']}")
    for field in ["p50_ns", "p90_ns", "p99_ns", "p99_9_ns"]:
        stats = total[field]
        print(f"total_tick_to_trade_ns.{field}: min={stats['min']}ns mean={stats['mean']}ns max={stats['max']}ns")


if __name__ == "__main__":
    main()
