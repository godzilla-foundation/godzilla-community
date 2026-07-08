#!/usr/bin/env python3
import argparse
import csv
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
        return sorted(v for v in (to_int(row.get(metric)) for row in rows) if v is not None)


def write_cdf(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["latency_ns", "latency_us", "cdf"])
        writer.writeheader()
        total = len(values)
        for index, value in enumerate(values, start=1):
            writer.writerow({"latency_ns": value, "latency_us": value / 1000.0, "cdf": index / total if total else 0})


def maybe_png(out_path, values, metric):
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    if not values:
        return None
    png_path = out_path.with_suffix(".png")
    plt.figure(figsize=(8, 5))
    plt.plot([value / 1000.0 for value in values], [i / len(values) for i in range(1, len(values) + 1)])
    plt.xlabel("Latency (us)")
    plt.ylabel("CDF")
    plt.title(f"CDF: {metric}")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(png_path)
    plt.close()
    return png_path


def main():
    parser = argparse.ArgumentParser(description="Generate CDF CSV for a joined latency metric")
    parser.add_argument("--joined", type=Path, default=DEFAULT_JOINED)
    parser.add_argument("--metric", default="total_tick_to_trade_ns")
    parser.add_argument("--out", type=Path, default=Path("analysis/output/cdf_total_tick_to_trade.csv"))
    parser.add_argument("--png", action="store_true")
    args = parser.parse_args()
    values = read_values(args.joined, args.metric)
    write_cdf(args.out, values)
    print(f"rows: {len(values)}")
    print(f"cdf_csv: {args.out}")
    if args.png:
        png = maybe_png(args.out, values, args.metric)
        print(f"cdf_png: {png}" if png else "cdf_png: skipped")


if __name__ == "__main__":
    main()
