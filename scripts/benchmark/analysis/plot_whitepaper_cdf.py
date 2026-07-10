#!/usr/bin/env python3
"""Figure 2 for WHITEPAPER.md: per-run tick-to-trade latency CDFs (5 runs)."""
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, NullFormatter, ScalarFormatter

BASE = Path("/home/kunxue/dev/godzilla-community/scripts/benchmark/analysis/spin_100000_confirm")
OUT_DIR = Path("/home/kunxue/dev/godzilla-community/figures")
METRIC = "total_tick_to_trade_ns"

SERIES = ["#2a78d6", "#1baf7a", "#eda100", "#008300", "#4a3aa7"]
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"


def load_run(run_dir):
    with (run_dir / "joined_latency_journal.csv").open(newline="", encoding="utf-8") as f:
        values = sorted(int(row[METRIC]) / 1000.0 for row in csv.DictReader(f))
    return values


def main():
    runs = {p.name: load_run(p) for p in sorted(BASE.glob("run_00[1-5]"))}

    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.size": 9,
            "text.color": INK,
            "axes.edgecolor": BASELINE,
            "axes.labelcolor": INK_SECONDARY,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
        }
    )

    fig, ax = plt.subplots(figsize=(6.0, 3.6), dpi=300)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    for (name, values), color in zip(runs.items(), SERIES):
        n = len(values)
        cdf = [i / n for i in range(1, n + 1)]
        label = f"Run {int(name.split('_')[1])}  (n={n})"
        ax.plot(values, cdf, color=color, linewidth=1.4, label=label)

    ax.set_xscale("log")
    ticks = [50, 100, 200, 500, 1000, 2000]
    ax.xaxis.set_major_locator(FixedLocator(ticks))
    ax.xaxis.set_major_formatter(ScalarFormatter())
    ax.xaxis.set_minor_formatter(NullFormatter())
    xmin = min(v[0] for v in runs.values()) * 0.9
    ax.set_xlim(xmin, 2000)
    ax.set_ylim(0, 1.02)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 0.9, 0.99])
    ax.set_yticklabels(["0", "0.25", "0.50", "0.75", "0.90", "0.99"])

    for q in (0.5, 0.9, 0.99):
        ax.axhline(q, color=GRID, linewidth=0.7, zorder=0)
    ax.grid(axis="x", color=GRID, linewidth=0.7, zorder=0)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    ax.set_xlabel("Tick-to-trade latency (μs, log scale)")
    ax.set_ylabel("Empirical CDF")
    ax.legend(loc="lower right", frameon=False, fontsize=8, labelcolor=INK_SECONDARY)

    OUT_DIR.mkdir(exist_ok=True)
    for ext in ("png", "pdf"):
        fig.savefig(OUT_DIR / f"fig2_tick_to_trade_cdf.{ext}", bbox_inches="tight", facecolor=SURFACE)
    print("wrote", OUT_DIR / "fig2_tick_to_trade_cdf.png")


if __name__ == "__main__":
    main()
