#!/usr/bin/env python3
import argparse
import csv
import json
import math
from pathlib import Path

DEFAULT_RAW_DIRS = [
    Path("core/extensions/mock/traces/raw"),
    Path("../../core/extensions/mock/traces/raw"),
]
DEFAULT_OUT_DIR = Path("analysis/output")
JOINED_FIELDS = ["run_id", "system", "event_id", "client_order_id", "symbol", "side", "t_exchange_emit_ns", "t_msg_received_ns", "t_strategy_visible_ns", "t_strategy_triggered_ns", "t_order_constructed_ns", "t_order_socket_write_ns", "t_order_received_ns", "t_ack_ns", "md_ingest_ns", "decision_ns", "order_egress_ns", "total_tick_to_trade_ns"]
METRICS = ["md_ingest_ns", "decision_ns", "order_egress_ns", "total_tick_to_trade_ns"]


def pick_raw_dir(raw_dir):
    if raw_dir:
        return raw_dir
    for path in DEFAULT_RAW_DIRS:
        if path.exists():
            return path
    return DEFAULT_RAW_DIRS[0]


def read_csv(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def cell(row, key, default=""):
    value = row.get(key, default)
    return default if value is None else value


def to_int(value):
    if value in (None, ""):
        return None
    try:
        return int(float(str(value)))
    except ValueError:
        return None


def index_first(rows, keys):
    out = {}
    for row in rows:
        key = tuple(cell(row, k) for k in keys)
        if all(key) and key not in out:
            out[key] = row
    return out


def find(row, indexes):
    for name, index, keys in indexes:
        key = tuple(cell(row, k) for k in keys)
        if all(key) and key in index:
            return name, index[key]
    return "unmatched", {}


def derive(row, target, left, right):
    lhs = to_int(row.get(left))
    rhs = to_int(row.get(right))
    row[target] = "" if lhs is None or rhs is None else lhs - rhs


def join(raw_dir):
    md = read_csv(raw_dir / "mock_md.csv")
    strategy = read_csv(raw_dir / "simple_benchmark_strategy.csv")
    td = read_csv(raw_dir / "mock_td.csv")
    exch = read_csv(raw_dir / "mock_exchange_orders.csv")

    md_by_event = index_first(md, ["event_id"])
    td_indexes = [("client_order_id", index_first(td, ["client_order_id"]), ["client_order_id"]), ("event_id_side", index_first(td, ["event_id", "side"]), ["event_id", "side"]), ("event_id", index_first(td, ["event_id"]), ["event_id"])]
    exch_indexes = [("client_order_id", index_first(exch, ["client_order_id"]), ["client_order_id"]), ("event_id_side", index_first(exch, ["event_id", "side"]), ["event_id", "side"]), ("event_id", index_first(exch, ["event_id"]), ["event_id"])]
    counts = {"td_client_order_id": 0, "td_event_id_side": 0, "td_event_id": 0, "td_unmatched": 0, "exchange_client_order_id": 0, "exchange_event_id_side": 0, "exchange_event_id": 0, "exchange_unmatched": 0}
    rows = []

    for s in strategy:
        event_id = cell(s, "event_id")
        md_row = md_by_event.get((event_id,), {})
        td_mode, td_row = find(s, td_indexes)
        ex_mode, ex_row = find(s, exch_indexes)
        counts[f"td_{td_mode}"] += 1
        counts[f"exchange_{ex_mode}"] += 1
        row = {
            "run_id": cell(s, "run_id", "local"),
            "system": cell(s, "system", "godzilla"),
            "event_id": event_id,
            "client_order_id": cell(s, "client_order_id") or cell(td_row, "client_order_id") or cell(ex_row, "client_order_id"),
            "symbol": cell(s, "symbol") or cell(md_row, "symbol") or cell(td_row, "symbol") or cell(ex_row, "symbol"),
            "side": cell(s, "side") or cell(td_row, "side") or cell(ex_row, "side"),
            "t_exchange_emit_ns": cell(s, "t_exchange_emit_ns") or cell(md_row, "t_exchange_emit_ns"),
            "t_msg_received_ns": cell(s, "t_msg_received_ns") or cell(md_row, "t_msg_received_ns"),
            "t_strategy_visible_ns": cell(s, "t_strategy_visible_ns") or cell(md_row, "t_strategy_visible_ns"),
            "t_strategy_triggered_ns": cell(s, "t_strategy_triggered_ns"),
            "t_order_constructed_ns": cell(s, "t_order_constructed_ns") or cell(td_row, "t_order_constructed_ns"),
            "t_order_socket_write_ns": cell(td_row, "t_order_socket_write_ns") or cell(ex_row, "t_order_socket_write_ns"),
            "t_order_received_ns": cell(ex_row, "t_order_received_ns"),
            "t_ack_ns": cell(ex_row, "t_ack_ns"),
        }
        derive(row, "md_ingest_ns", "t_strategy_visible_ns", "t_msg_received_ns")
        derive(row, "decision_ns", "t_order_constructed_ns", "t_strategy_triggered_ns")
        derive(row, "order_egress_ns", "t_order_socket_write_ns", "t_order_constructed_ns")
        derive(row, "total_tick_to_trade_ns", "t_order_socket_write_ns", "t_msg_received_ns")
        rows.append(row)
    meta = {"raw_dir": str(raw_dir), "input_rows": {"md": len(md), "strategy": len(strategy), "td": len(td), "exchange_orders": len(exch)}, "join_counts": counts, "joined_rows": len(rows)}
    return rows, meta


def percentile(values, pct):
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


def summarize(rows, meta):
    metrics = {}
    for field in METRICS:
        values = [v for v in (to_int(r.get(field)) for r in rows) if v is not None]
        metrics[field] = {"count": len(values), "min_ns": min(values) if values else None, "max_ns": max(values) if values else None, "mean_ns": sum(values) / len(values) if values else None, "p50_ns": percentile(values, 50), "p90_ns": percentile(values, 90), "p99_ns": percentile(values, 99), "p99_9_ns": percentile(values, 99.9)}
    return {"metadata": meta, "metrics": metrics}


def main():
    parser = argparse.ArgumentParser(description="Join mock benchmark traces and summarize latency")
    parser.add_argument("--raw-dir", type=Path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    raw_dir = pick_raw_dir(args.raw_dir)
    rows, meta = join(raw_dir)
    summary = summarize(rows, meta)
    joined_path = args.out_dir / "joined_latency.csv"
    summary_path = args.out_dir / "summary.json"
    write_csv(joined_path, rows, JOINED_FIELDS)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"raw_dir: {raw_dir}")
    print(f"joined_rows: {len(rows)}")
    print(f"join_counts: {meta['join_counts']}")
    def fmt_ns(value):
        return "n/a" if value is None else f"{value}ns"

    for name, stats in summary["metrics"].items():
        print(
            f"{name}: count={stats['count']} "
            f"p50={fmt_ns(stats['p50_ns'])} p90={fmt_ns(stats['p90_ns'])} "
            f"p99={fmt_ns(stats['p99_ns'])} p99.9={fmt_ns(stats['p99_9_ns'])}"
        )
    print(f"joined_csv: {joined_path}")
    print(f"summary_json: {summary_path}")


if __name__ == "__main__":
    main()
