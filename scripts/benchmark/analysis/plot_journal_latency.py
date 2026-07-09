#!/usr/bin/env python3
import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

DEFAULT_METRIC = "total_tick_to_trade_ns"
STAGE_METRICS = ["md_to_order_input_ns", "order_report_ns"]
PLOT_METRICS = ["total_tick_to_trade_ns", "md_to_order_input_ns", "order_report_ns"]
TAIL_PERCENTILES = [50, 90, 99, 99.9]


def require_matplotlib():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def to_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def percentile(values: List[int], pct: float) -> Optional[float]:
    if not values:
        return None
    values = sorted(values)
    if len(values) == 1:
        return float(values[0])
    pos = (len(values) - 1) * pct / 100.0
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return float(values[lo])
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def read_joined_values(path: Path, metric: str) -> List[int]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [v for v in (to_int(row.get(metric)) for row in reader) if v is not None]


def read_joined_rows(path: Path) -> List[Dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def run_joined_paths(runs_dir: Path) -> List[Tuple[str, Path]]:
    paths = []
    for path in sorted(runs_dir.glob("run_*/joined_latency_journal.csv")):
        paths.append((path.parent.name, path))
    return paths


def collect_values(joined: Optional[Path], runs_dir: Optional[Path], metric: str) -> Tuple[List[int], List[Tuple[str, List[int]]]]:
    by_run: List[Tuple[str, List[int]]] = []
    if runs_dir is not None:
        for run_id, path in run_joined_paths(runs_dir):
            values = read_joined_values(path, metric)
            if values:
                by_run.append((run_id, values))
    elif joined is not None:
        values = read_joined_values(joined, metric)
        by_run.append((joined.parent.name or "run", values))
    values_all: List[int] = []
    for _run_id, values in by_run:
        values_all.extend(values)
    return values_all, by_run


def ensure_out_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def plot_histogram(values: List[int], metric: str, out_dir: Path, bins: int) -> Optional[Path]:
    if not values:
        return None
    plt = require_matplotlib()
    path = out_dir / f"{metric}_histogram.png"
    plt.figure(figsize=(9, 5))
    plt.hist([v / 1000.0 for v in values], bins=bins, color="#2563eb", edgecolor="white")
    plt.xlabel("Latency (us)")
    plt.ylabel("Count")
    plt.title(f"Latency Histogram: {metric}")
    plt.grid(True, axis="y", alpha=0.25)
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()
    return path


def plot_cdf(values: List[int], metric: str, out_dir: Path) -> Optional[Path]:
    if not values:
        return None
    plt = require_matplotlib()
    path = out_dir / f"{metric}_cdf.png"
    sorted_values = sorted(values)
    cdf = [idx / len(sorted_values) for idx in range(1, len(sorted_values) + 1)]
    plt.figure(figsize=(9, 5))
    plt.plot([v / 1000.0 for v in sorted_values], cdf, color="#0f766e", linewidth=2)
    plt.xlabel("Latency (us)")
    plt.ylabel("CDF")
    plt.title(f"Latency CDF: {metric}")
    plt.ylim(0, 1.01)
    plt.grid(True, alpha=0.25)
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()
    return path


def plot_tail_by_run(by_run: List[Tuple[str, List[int]]], metric: str, out_dir: Path) -> Optional[Path]:
    if not by_run:
        return None
    plt = require_matplotlib()
    path = out_dir / f"{metric}_tail_by_run.png"
    run_ids = [run_id for run_id, _values in by_run]
    x = list(range(len(run_ids)))
    plt.figure(figsize=(max(9, len(run_ids) * 0.8), 5))
    colors = ["#2563eb", "#0f766e", "#f59e0b", "#dc2626"]
    for pct, color in zip(TAIL_PERCENTILES, colors):
        ys = [(percentile(values, pct) or 0) / 1000.0 for _run_id, values in by_run]
        plt.plot(x, ys, marker="o", linewidth=2, label=f"p{pct}", color=color)
    plt.xticks(x, run_ids, rotation=30, ha="right")
    plt.xlabel("Run")
    plt.ylabel("Latency (us)")
    plt.title(f"Tail Latency by Run: {metric}")
    plt.grid(True, axis="y", alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()
    return path


def collect_stage_values(joined: Optional[Path], runs_dir: Optional[Path]) -> Dict[str, List[int]]:
    paths: List[Path] = []
    if runs_dir is not None:
        paths = [path for _run_id, path in run_joined_paths(runs_dir)]
    elif joined is not None:
        paths = [joined]
    values: Dict[str, List[int]] = {metric: [] for metric in STAGE_METRICS}
    for path in paths:
        rows = read_joined_rows(path)
        for row in rows:
            for metric in STAGE_METRICS:
                value = to_int(row.get(metric))
                if value is not None:
                    values[metric].append(value)
    return values


def plot_stage_breakdown(stage_values: Dict[str, List[int]], out_dir: Path) -> Optional[Path]:
    if not any(stage_values.values()):
        return None
    plt = require_matplotlib()
    path = out_dir / "stage_breakdown.png"
    labels = ["p50", "p90", "p99", "p99.9"]
    pcts = [50, 90, 99, 99.9]
    md = [(percentile(stage_values.get("md_to_order_input_ns", []), pct) or 0) / 1000.0 for pct in pcts]
    order = [(percentile(stage_values.get("order_report_ns", []), pct) or 0) / 1000.0 for pct in pcts]
    x = list(range(len(labels)))
    plt.figure(figsize=(9, 5))
    plt.bar(x, md, label="MD to OrderInput", color="#2563eb")
    plt.bar(x, order, bottom=md, label="OrderInput to Order", color="#f59e0b")
    plt.xticks(x, labels)
    plt.xlabel("Percentile")
    plt.ylabel("Latency (us)")
    plt.title("Stage Latency Breakdown")
    plt.grid(True, axis="y", alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()
    return path


def write_percentiles_csv(values: List[int], metric: str, out_dir: Path) -> Optional[Path]:
    if not values:
        return None
    path = out_dir / f"{metric}_percentiles.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["metric", "percentile", "latency_ns", "latency_us"])
        writer.writeheader()
        for pct in TAIL_PERCENTILES:
            value = percentile(values, pct)
            writer.writerow({"metric": metric, "percentile": pct, "latency_ns": value, "latency_us": None if value is None else value / 1000.0})
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot journal latency charts from joined benchmark CSVs")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--joined", type=Path, help="Single joined_latency_journal.csv")
    source.add_argument("--runs-dir", type=Path, help="Directory containing run_*/joined_latency_journal.csv")
    parser.add_argument("--metric", default=DEFAULT_METRIC)
    parser.add_argument("--all-metrics", action="store_true", help="Plot total and per-stage latency metrics")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--bins", type=int, default=60)
    args = parser.parse_args()

    out_dir = ensure_out_dir(args.out_dir or ((args.runs_dir or args.joined.parent) / "charts"))
    metrics = PLOT_METRICS if args.all_metrics else [args.metric]
    stage_values = collect_stage_values(args.joined, args.runs_dir)

    outputs = []
    total_rows = 0
    total_runs = 0
    for metric in metrics:
        values, by_run = collect_values(args.joined, args.runs_dir, metric)
        total_rows = max(total_rows, len(values))
        total_runs = max(total_runs, len(by_run))
        for path in [
            plot_histogram(values, metric, out_dir, args.bins),
            plot_cdf(values, metric, out_dir),
            plot_tail_by_run(by_run, metric, out_dir),
            write_percentiles_csv(values, metric, out_dir),
        ]:
            if path is not None:
                outputs.append(path)
    for path in [plot_stage_breakdown(stage_values, out_dir)]:
        if path is not None:
            outputs.append(path)

    print(f"rows: {total_rows}")
    print(f"runs: {total_runs}")
    print(f"metrics: {','.join(metrics)}")
    for path in outputs:
        print(f"output: {path}")


if __name__ == "__main__":
    main()
