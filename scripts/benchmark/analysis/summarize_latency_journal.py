#!/usr/bin/env python3
import argparse
import csv
from contextlib import contextmanager
import json
import math
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Tuple

DEFAULT_HOME = Path.home() / ".config" / "kungfu" / "app"
DEFAULT_OUT_DIR = Path("analysis/output")
DEFAULT_TARGETS = {
    "md": ("md", "mock", "mock"),
    "strategy": ("strategy", "benchmark", ("simple_benchmark", "simple_benchmark_cpp")),
    "td": ("td", "mock", "benchmark"),
}
JOINED_FIELDS = [
    "run_id",
    "system",
    "depth_session_id",
    "strategy_session_id",
    "td_session_id",
    "depth_gen_time_ns",
    "depth_trigger_time_ns",
    "order_input_gen_time_ns",
    "order_input_trigger_time_ns",
    "order_gen_time_ns",
    "order_trigger_time_ns",
    "depth_event_id",
    "join_depth_method",
    "join_order_method",
    "symbol",
    "side",
    "price",
    "qty",
    "order_id",
    "client_order_id",
    "md_to_order_input_ns",
    "order_report_ns",
    "total_tick_to_trade_ns",
]
METRICS = ["md_to_order_input_ns", "order_report_ns", "total_tick_to_trade_ns"]


@contextmanager
def suppress_native_logs():
    if os.getenv("GZ_JOURNAL_ANALYSIS_VERBOSE", "").strip().lower() in {"1", "true", "yes", "on"}:
        yield
        return
    sys.stdout.flush()
    sys.stderr.flush()
    saved_stdout = os.dup(1)
    saved_stderr = os.dup(2)
    try:
        with open(os.devnull, "w") as devnull:
            os.dup2(devnull.fileno(), 1)
            os.dup2(devnull.fileno(), 2)
            yield
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(saved_stdout, 1)
        os.dup2(saved_stderr, 2)
        os.close(saved_stdout)
        os.close(saved_stderr)


class Logger:
    def debug(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def warn(self, *args, **kwargs):
        print("warning:", *args, file=sys.stderr)

    warning = warn

    def error(self, *args, **kwargs):
        print("error:", *args, file=sys.stderr)


def add_repo_python_to_path() -> None:
    repo = Path(__file__).resolve().parents[3]
    core_python = repo / "core" / "python"
    if core_python.exists() and str(core_python) not in sys.path:
        sys.path.insert(0, str(core_python))


def load_kungfu_modules():
    add_repo_python_to_path()
    if os.getenv("GZ_JOURNAL_ANALYSIS_VERBOSE", "").strip().lower() not in {"1", "true", "yes", "on"}:
        os.environ["KF_LOG_LEVEL"] = "warning"
    try:
        import kungfu  # noqa: F401
        import pyyjj
        import kungfu.msg
        import kungfu.wingchun.msg  # noqa: F401, registers wingchun msg names
        import kungfu.yijinjing.msg as yjj_msg
        import kungfu.yijinjing.journal as kfj
    except ImportError as exc:
        raise SystemExit(
            "failed to import Kungfu journal runtime modules. "
            "Run this script in the same Kungfu Python environment used by pm2/kfc. "
            f"missing import: {exc}"
        ) from exc
    return pyyjj, kungfu.msg, yjj_msg, kfj


def make_ctx(home: Path, category: str = "*", group: str = "*", name: str = "*", mode: str = "*"):
    pyyjj, _kf_msg, _yjj_msg, kfj = load_kungfu_modules()
    home.mkdir(parents=True, exist_ok=True)
    ctx = SimpleNamespace()
    ctx.home = str(home.expanduser())
    ctx.log_level = "warning"
    ctx.settings = {}
    ctx.locator = kfj.Locator(ctx.home)
    ctx.category = category
    ctx.group = group
    ctx.name = name
    ctx.mode = mode
    ctx.logger = Logger()
    ctx.low_latency = False
    ctx.location = pyyjj.location(kfj.MODES[mode], kfj.CATEGORIES[category], group, name, ctx.locator)
    ctx.journal_util_location = pyyjj.location(pyyjj.mode.LIVE, pyyjj.category.SYSTEM, "util", "journal", ctx.locator)
    ctx.system_config_location = pyyjj.location(pyyjj.mode.LIVE, pyyjj.category.SYSTEM, "etc", "kungfu", ctx.locator)
    return ctx


def write_csv(path: Path, rows: List[Dict[str, Any]], fields: Optional[Iterable[str]] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        seen = []
        for row in rows:
            for key in row.keys():
                if key not in seen:
                    seen.append(key)
        fields = seen
    fields = list(fields)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def flatten(prefix: str, value: Any, out: Dict[str, Any]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            flatten(f"{prefix}{key}.", child, out)
    elif isinstance(value, (list, tuple)):
        out[prefix[:-1]] = json.dumps(value, separators=(",", ":"), default=str)
        if value:
            out[f"{prefix[:-1]}_0"] = value[0]
    else:
        out[prefix[:-1]] = value


def frame_to_row(frame: Dict[str, Any], msg_name: str) -> Dict[str, Any]:
    row = {
        "source": frame.get("source", ""),
        "dest": frame.get("dest", ""),
        "trigger_time": frame.get("trigger_time", ""),
        "gen_time": frame.get("gen_time", ""),
        "msg_type": frame.get("msg_type", ""),
        "msg_name": msg_name,
    }
    data = frame.get("data")
    if isinstance(data, dict):
        flatten("data.", data, row)
    elif data is not None:
        row["data"] = data
    return row


def find_sessions(home: Path):
    _pyyjj, _kf_msg, _yjj_msg, kfj = load_kungfu_modules()
    ctx = make_ctx(home)
    with suppress_native_logs():
        sessions = kfj.find_sessions(ctx)
    records = sessions.to_dict("records")
    return records


def latest_session_id(records: List[Dict[str, Any]], target: Tuple[str, str, Any]) -> Optional[int]:
    category, group, name = target
    names = set(name) if isinstance(name, (list, tuple, set)) else {name}
    matches = [
        r for r in records
        if str(r.get("mode")) == "live"
        and str(r.get("category")) == category
        and str(r.get("group")) == group
        and str(r.get("name")) in names
    ]
    if not matches:
        return None
    matches.sort(key=lambda r: int(r.get("begin_time") or 0))
    return int(matches[-1]["id"])


def read_session_frames(home: Path, session_id: int, msg_name: str, io_type: str, max_messages: int) -> List[Dict[str, Any]]:
    pyyjj, kf_msg, yjj_msg, kfj = load_kungfu_modules()
    ctx = make_ctx(home)
    with suppress_native_logs():
        session = kfj.find_session(ctx, int(session_id))
    uname = f"{session['category']}/{session['group']}/{session['name']}/{session['mode']}"
    uid = pyyjj.hash_str_32(uname)

    ctx.category = "*"
    ctx.group = "*"
    ctx.name = "*"
    ctx.mode = "*"
    with suppress_native_logs():
        locations = kfj.collect_journal_locations(ctx)
        location = locations[uid]
        home_location = kfj.make_location_from_dict(ctx, location)
        io_device = pyyjj.io_device(home_location)
        reader = io_device.open_reader_to_subscribe()

    with suppress_native_logs():
        if io_type in {"out", "all"}:
            for dest in location["readers"]:
                reader.join(home_location, int(dest, 16), int(session["begin_time"]))

        if io_type in {"in", "all"} and not (
            home_location.category == pyyjj.category.SYSTEM
            and home_location.group == "master"
            and home_location.name == "master"
        ):
            master_home_uid = pyyjj.hash_str_32("system/master/master/live")
            if master_home_uid in locations:
                master_home_location = kfj.make_location_from_dict(ctx, locations[master_home_uid])
                reader.join(master_home_location, 0, int(session["begin_time"]))
            master_cmd_uid = pyyjj.hash_str_32(f"system/master/{location['uid']:08x}/live")
            if master_cmd_uid in locations:
                master_cmd_location = kfj.make_location_from_dict(ctx, locations[master_cmd_uid])
                reader.join(master_cmd_location, location["uid"], int(session["begin_time"]))

    msg_meta = kf_msg.Registry.meta_from_name(msg_name)
    if msg_meta is None:
        raise SystemExit(f"unknown Kungfu msg name: {msg_name}")
    msg_type = msg_meta["id"]

    rows = []
    with suppress_native_logs():
        while reader.data_available() and len(rows) < max_messages:
            frame = reader.current_frame()
            if frame.dest == home_location.uid and frame.msg_type in {yjj_msg.RequestReadFrom, yjj_msg.RequestReadFromPublic}:
                request = pyyjj.get_RequestReadFrom(frame)
                source_location = kfj.make_location_from_dict(ctx, locations[request.source_id])
                reader.join(source_location, location["uid"] if frame.msg_type == yjj_msg.RequestReadFrom else 0, request.from_time)
            elif frame.dest == home_location.uid and frame.msg_type == yjj_msg.Deregister:
                loc = json.loads(frame.data_as_string())
                reader.disjoin(loc["uid"])
            elif frame.msg_type == msg_type and frame.gen_time >= int(session["begin_time"]):
                rows.append(frame_to_row(frame.as_dict(), msg_name))
            reader.next()
        del reader
        del io_device
    return rows


def cell(row: Dict[str, Any], *keys: str, default: str = "") -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return default


def to_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value)))
    except ValueError:
        return None


def to_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(str(value))
    except ValueError:
        return None


def side_name(row: Dict[str, Any]) -> str:
    text = str(cell(row, "data.side", "side", default=""))
    if text.lower().endswith("buy") or text.upper() == "BUY" or text == "1":
        return "BUY"
    if text.lower().endswith("sell") or text.upper() == "SELL" or text == "2":
        return "SELL"
    return text


def symbol_of(row: Dict[str, Any]) -> str:
    return str(cell(row, "data.symbol", "symbol", "data.instrument_id", "instrument_id", default=""))


def price_of(row: Dict[str, Any]) -> Any:
    return cell(row, "data.price", "data.limit_price", "price", "limit_price", default="")


def qty_of(row: Dict[str, Any]) -> Any:
    return cell(row, "data.volume", "data.qty", "volume", "qty", default="")


def order_id_of(row: Dict[str, Any]) -> str:
    return str(cell(row, "data.order_id", "order_id", default=""))


def depth_event_id_of(row: Dict[str, Any]) -> Optional[int]:
    return to_int(cell(row, "data.data_time", "event_id", "data.event_id", default=""))


def depth_price_for_side(row: Dict[str, Any], side: str) -> Optional[float]:
    if side == "BUY":
        return to_float(cell(row, "data.bid_price_0", "bid_price_0", default=""))
    if side == "SELL":
        return to_float(cell(row, "data.ask_price_0", "ask_price_0", default=""))
    return None


def same_price(left: Any, right: Any, epsilon: float) -> bool:
    left_f = to_float(left)
    right_f = to_float(right)
    return left_f is not None and right_f is not None and abs(left_f - right_f) <= epsilon


def client_order_id_of(row: Dict[str, Any]) -> str:
    return str(cell(row, "data.client_order_id", "client_order_id", default=""))


def sort_by_gen(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(rows, key=lambda r: to_int(r.get("gen_time")) or 0)


def match_depth_by_price_side(order_input: Dict[str, Any], depths: List[Dict[str, Any]], used: set, price_epsilon: float) -> Optional[Dict[str, Any]]:
    order_time = to_int(order_input.get("gen_time"))
    order_symbol = symbol_of(order_input)
    order_side = side_name(order_input)
    order_price = price_of(order_input)
    if order_time is None or not order_side:
        return None
    best_idx = None
    best_row = None
    best_delta = None
    for idx, depth in enumerate(depths):
        if idx in used:
            continue
        depth_time = to_int(depth.get("gen_time"))
        if depth_time is None or depth_time > order_time:
            continue
        depth_symbol = symbol_of(depth)
        if order_symbol and depth_symbol and order_symbol != depth_symbol:
            continue
        depth_price = depth_price_for_side(depth, order_side)
        if not same_price(order_price, depth_price, price_epsilon):
            continue
        delta = order_time - depth_time
        if best_delta is None or delta < best_delta:
            best_idx = idx
            best_row = depth
            best_delta = delta
    if best_idx is not None:
        used.add(best_idx)
    return best_row


def match_depth_by_time(order_input: Dict[str, Any], depths: List[Dict[str, Any]], used: set, max_delta_ns: int) -> Optional[Dict[str, Any]]:
    order_time = to_int(order_input.get("gen_time"))
    if order_time is None:
        return None
    order_symbol = symbol_of(order_input)
    best_idx = None
    best_row = None
    best_delta = None
    for idx, depth in enumerate(depths):
        if idx in used:
            continue
        depth_time = to_int(depth.get("gen_time"))
        if depth_time is None or depth_time > order_time:
            continue
        depth_symbol = symbol_of(depth)
        if order_symbol and depth_symbol and order_symbol != depth_symbol:
            continue
        delta = order_time - depth_time
        if delta <= max_delta_ns and (best_delta is None or delta < best_delta):
            best_idx = idx
            best_row = depth
            best_delta = delta
    if best_idx is not None:
        used.add(best_idx)
    return best_row


def match_depth(order_input: Dict[str, Any], depths: List[Dict[str, Any]], used: set, max_delta_ns: int, price_epsilon: float) -> Tuple[Optional[Dict[str, Any]], str]:
    depth = match_depth_by_price_side(order_input, depths, used, price_epsilon)
    if depth is not None:
        return depth, "price_side"
    depth = match_depth_by_time(order_input, depths, used, max_delta_ns)
    if depth is not None:
        return depth, "time"
    return None, "unmatched"


def build_order_id_index(orders: List[Dict[str, Any]], used: set) -> Dict[str, List[int]]:
    index: Dict[str, List[int]] = {}
    for idx, order in enumerate(orders):
        if idx in used:
            continue
        order_id = order_id_of(order)
        if order_id:
            index.setdefault(order_id, []).append(idx)
    return index


def match_order_by_id(order_input: Dict[str, Any], orders: List[Dict[str, Any]], used: set, order_id_index: Dict[str, List[int]]) -> Optional[Dict[str, Any]]:
    input_order_id = order_id_of(order_input)
    if not input_order_id:
        return None
    input_time = to_int(order_input.get("gen_time"))
    best_idx = None
    best_row = None
    best_delta = None
    for idx in order_id_index.get(input_order_id, []):
        if idx in used:
            continue
        order = orders[idx]
        order_time = to_int(order.get("gen_time"))
        if input_time is not None and order_time is not None and order_time < input_time:
            continue
        delta = 0 if input_time is None or order_time is None else order_time - input_time
        if best_delta is None or delta < best_delta:
            best_idx = idx
            best_row = order
            best_delta = delta
    if best_idx is not None:
        used.add(best_idx)
    return best_row


def match_order_by_time(order_input: Dict[str, Any], orders: List[Dict[str, Any]], used: set, max_delta_ns: int) -> Optional[Dict[str, Any]]:
    input_time = to_int(order_input.get("gen_time"))
    if input_time is None:
        return None
    input_order_id = order_id_of(order_input)
    input_client_id = client_order_id_of(order_input)
    input_symbol = symbol_of(order_input)
    best_idx = None
    best_row = None
    best_delta = None
    for idx, order in enumerate(orders):
        if idx in used:
            continue
        order_time = to_int(order.get("gen_time"))
        if order_time is None or order_time < input_time:
            continue
        if input_order_id and order_id_of(order) and input_order_id != order_id_of(order):
            continue
        if input_client_id and client_order_id_of(order) and input_client_id != client_order_id_of(order):
            continue
        if input_symbol and symbol_of(order) and input_symbol != symbol_of(order):
            continue
        delta = order_time - input_time
        if delta <= max_delta_ns and (best_delta is None or delta < best_delta):
            best_idx = idx
            best_row = order
            best_delta = delta
    if best_idx is not None:
        used.add(best_idx)
    return best_row


def match_order(order_input: Dict[str, Any], orders: List[Dict[str, Any]], used: set, order_id_index: Dict[str, List[int]], max_delta_ns: int) -> Tuple[Optional[Dict[str, Any]], str]:
    order = match_order_by_id(order_input, orders, used, order_id_index)
    if order is not None:
        return order, "order_id"
    order = match_order_by_time(order_input, orders, used, max_delta_ns)
    if order is not None:
        return order, "time"
    return None, "unmatched"


def join_journal(depths, order_inputs, orders, session_ids, max_match_delta_ns, price_epsilon):
    depths = sort_by_gen(depths)
    order_inputs = sort_by_gen(order_inputs)
    orders = sort_by_gen(orders)
    used_depths = set()
    used_orders = set()
    order_id_index = build_order_id_index(orders, used_orders)
    rows = []
    counts = {
        "depth_price_side": 0,
        "depth_time": 0,
        "depth_unmatched": 0,
        "order_order_id": 0,
        "order_time": 0,
        "order_unmatched": 0,
    }
    for order_input in order_inputs:
        depth, depth_method = match_depth(order_input, depths, used_depths, max_match_delta_ns, price_epsilon)
        order, order_method = match_order(order_input, orders, used_orders, order_id_index, max_match_delta_ns)
        counts[f"depth_{depth_method}"] += 1
        counts[f"order_{order_method}"] += 1
        depth_gen = to_int(depth.get("gen_time")) if depth else None
        input_gen = to_int(order_input.get("gen_time"))
        order_gen = to_int(order.get("gen_time")) if order else None
        md_to_order = "" if depth_gen is None or input_gen is None else input_gen - depth_gen
        order_report = "" if input_gen is None or order_gen is None else order_gen - input_gen
        total = md_to_order if order_gen is None else ("" if depth_gen is None else order_gen - depth_gen)
        rows.append({
            "run_id": "journal",
            "system": "godzilla",
            "depth_session_id": session_ids.get("md", ""),
            "strategy_session_id": session_ids.get("strategy", ""),
            "td_session_id": session_ids.get("td", ""),
            "depth_gen_time_ns": depth_gen or "",
            "depth_trigger_time_ns": cell(depth or {}, "trigger_time"),
            "order_input_gen_time_ns": input_gen or "",
            "order_input_trigger_time_ns": cell(order_input, "trigger_time"),
            "order_gen_time_ns": order_gen or "",
            "order_trigger_time_ns": cell(order or {}, "trigger_time"),
            "depth_event_id": depth_event_id_of(depth or {}) or "",
            "join_depth_method": depth_method,
            "join_order_method": order_method,
            "symbol": symbol_of(order_input) or symbol_of(depth or {}) or symbol_of(order or {}),
            "side": side_name(order_input) or side_name(order or {}),
            "price": price_of(order_input),
            "qty": qty_of(order_input),
            "order_id": order_id_of(order_input) or order_id_of(order or {}),
            "client_order_id": client_order_id_of(order_input) or client_order_id_of(order or {}),
            "md_to_order_input_ns": md_to_order,
            "order_report_ns": order_report,
            "total_tick_to_trade_ns": total,
        })
    return rows, counts


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


def summarize(rows: List[Dict[str, Any]], metadata: Dict[str, Any]) -> Dict[str, Any]:
    metrics = {}
    for field in METRICS:
        values = [v for v in (to_int(row.get(field)) for row in rows) if v is not None]
        metrics[field] = {
            "count": len(values),
            "min_ns": min(values) if values else None,
            "max_ns": max(values) if values else None,
            "mean_ns": sum(values) / len(values) if values else None,
            "p50_ns": percentile(values, 50),
            "p90_ns": percentile(values, 90),
            "p99_ns": percentile(values, 99),
            "p99_9_ns": percentile(values, 99.9),
        }
    return {"metadata": metadata, "metrics": metrics}


def fmt_ns(value):
    return "n/a" if value is None else f"{value}ns"


def main():
    parser = argparse.ArgumentParser(description="Summarize shm-only benchmark latency from Kungfu journal frames")
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME, help="Kungfu home containing app journals")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--md-session", type=int)
    parser.add_argument("--strategy-session", type=int)
    parser.add_argument("--td-session", type=int)
    parser.add_argument("--max-messages", type=int, default=int(os.getenv("GZ_JOURNAL_MAX_MESSAGES", "10000")), help="Maximum frames to read per session; can also be set with GZ_JOURNAL_MAX_MESSAGES")
    parser.add_argument("--max-match-delta-ns", type=int, default=5_000_000_000)
    parser.add_argument("--price-epsilon", type=float, default=1e-9, help="Price tolerance for depth/order_input price-side matching")
    parser.add_argument("--skip-first", type=int, default=int(os.getenv("GZ_JOURNAL_SKIP_FIRST", "0")), help="Skip this many joined rows before summarizing; can also be set with GZ_JOURNAL_SKIP_FIRST")
    parser.add_argument("--list-sessions", action="store_true", help="Only write/print discovered sessions")
    args = parser.parse_args()

    home = args.home.expanduser().resolve()
    sessions = find_sessions(home)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    sessions_path = args.out_dir / "journal_sessions.csv"
    write_csv(sessions_path, sessions)

    if args.list_sessions:
        print(f"home: {home}")
        print(f"sessions_csv: {sessions_path}")
        for row in sessions:
            print(row)
        return

    session_ids = {
        "md": args.md_session or latest_session_id(sessions, DEFAULT_TARGETS["md"]),
        "strategy": args.strategy_session or latest_session_id(sessions, DEFAULT_TARGETS["strategy"]),
        "td": args.td_session or latest_session_id(sessions, DEFAULT_TARGETS["td"]),
    }
    missing = [name for name, value in session_ids.items() if value is None]
    if missing:
        raise SystemExit(
            f"missing sessions for {missing}. Inspect {sessions_path}, then rerun with "
            "--md-session/--strategy-session/--td-session."
        )

    raw_dir = args.out_dir / "journal_raw"
    depths = read_session_frames(home, int(session_ids["md"]), "depth", "all", args.max_messages)
    order_inputs = read_session_frames(home, int(session_ids["strategy"]), "order_input", "all", args.max_messages)
    orders = read_session_frames(home, int(session_ids["td"]), "order", "all", args.max_messages)
    write_csv(raw_dir / "journal_depth.csv", depths)
    write_csv(raw_dir / "journal_order_input.csv", order_inputs)
    write_csv(raw_dir / "journal_order.csv", orders)

    joined_all, join_counts = join_journal(depths, order_inputs, orders, session_ids, args.max_match_delta_ns, args.price_epsilon)
    joined = joined_all[args.skip_first:] if args.skip_first > 0 else joined_all
    metadata = {
        "home": str(home),
        "session_ids": session_ids,
        "input_rows": {"depth": len(depths), "order_input": len(order_inputs), "order": len(orders)},
        "max_messages": args.max_messages,
        "join_counts": join_counts,
        "joined_rows_raw": len(joined_all),
        "joined_rows": len(joined),
        "skip_first": args.skip_first,
        "price_epsilon": args.price_epsilon,
        "time_basis": "Kungfu journal frame gen_time. total_tick_to_trade_ns is order report gen_time - depth gen_time when order reports are available; otherwise order_input gen_time - depth gen_time.",
    }
    summary = summarize(joined, metadata)
    joined_path = args.out_dir / "joined_latency_journal.csv"
    summary_path = args.out_dir / "summary_journal.json"
    write_csv(joined_path, joined, JOINED_FIELDS)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"home: {home}")
    print(f"sessions_csv: {sessions_path}")
    print(f"session_ids: {session_ids}")
    print(f"input_rows: {metadata['input_rows']}")
    print(f"joined_rows: {len(joined)}")
    if args.skip_first > 0:
        print(f"joined_rows_raw: {len(joined_all)}")
        print(f"skip_first: {args.skip_first}")
    print(f"join_counts: {join_counts}")
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
