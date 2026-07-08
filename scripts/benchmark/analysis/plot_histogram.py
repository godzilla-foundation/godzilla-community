#!/usr/bin/env python3
import argparse
import csv
import math
from pathlib import Path

DEFAULT_JOINED = Path("analysis/output/joined_latency.csv")


def to_int(value):
    if value in (None, ""):
        return None
    try:
        return int(float(str(value)))
    except ValueError:
        return None


def read_values(path, metric):
    with path.open(newline="", encoding="utf-8") as f:
        rows = csv.DictReader(f)
        return [v for v in (to_int(row.get(metric)) for row in rows) if v is not None]


def bins_for(values, bins):
    if not values:
        return []
    low = min(values)
    high = max(values)
    if low == high:
        return [(low, high, len(values))]
    width = max(1, math.ceil((high - low + 1) / bins))
    counts = [0] * bins
    for value in values:
        counts[min((value - low) // width, bins - 1)] += 1
    rows = []
    for idx, count in enumerate(counts):
        start = low + idx * width
        end = min(start + width - 1, high)
        rows.append((start, end, count))
    return rows


def write_histogram(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    total = sum(count for _, _, count in rows)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["bucket_start_ns", "bucket_end_ns", "bucket_start_us", "bucket_end_us", "count", "fraction"])
        writer.writeheader()
        for start, end, count in rows:
            writer.writerow({"bucket_start_ns": start, "bucket_end_ns": end, "bucket_start_us": start / 1000.0, "bucket_end_us": end / 1000.0, "count": count, "fraction": count / total if total else 0})


def maybe_png(out_path, rows, metric):
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    if not rows:
        return None
    png_path = out_path.with_suffix(".png")
    centers = [((start + end) / 2) / 1000.0 for start, end, _ in rows]
    widths = [max((end - start + 1) / 1000.0, 0.001) for start, end, _ in rows]
    counts = [count for _, _, count in rows]
    plt.figure(figsize=(8, 5))
    plt.bar(centers, counts, width=widths)
    plt.xlabel("Latency (us)")
    plt.ylabel("Count")
    plt.title(f"Histogram: {metric}")
    plt.grid(True, axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(png_path)
    plt.close()
    return png_path


def main():
    parser = argparse.ArgumentParser(description="Generate histogram CSV for a joined latency metric")
    parser.add_argument("--joined", type=Path, default=DEFAULT_JOINED)
    parser.add_argument("--metric", default="total_tick_to_trade_ns")
    parser.add_argument("--bins", type=int, default=50)
    parser.add_argument("--out", type=Path, default=Path("analysis/output/histogram_total_tick_to_trade.csv"))
    parser.add_argument("--png", action="store_true")
    args = parser.parse_args()
    values = read_values(args.joined, args.metric)
    rows = bins_for(values, args.bins)
    write_histogram(args.out, rows)
    print(f"rows: {len(values)}")
    print(f"histogram_csv: {args.out}")
    if args.png:
        png = maybe_png(args.out, rows, args.metric)
        print(f"histogram_png: {png}" if png else "histogram_png: skipped")


if __name__ == "__main__":
    main()
