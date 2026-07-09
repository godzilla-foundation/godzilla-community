import csv
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any, Dict

try:
    from kungfu.wingchun.constants import Exchange
    from pywingchun.constants import InstrumentType, OrderType, Side
except ImportError:
    class _Fallback:
        pass

    Exchange = _Fallback()
    Exchange.MOCK = "mock"
    InstrumentType = _Fallback()
    InstrumentType.Spot = 1
    OrderType = _Fallback()
    OrderType.Limit = 1
    Side = _Fallback()
    Side.Buy = "BUY"
    Side.Sell = "SELL"


TRACE_FIELDS = [
    "run_id",
    "system",
    "event_id",
    "symbol",
    "side",
    "order_id",
    "client_order_id",
    "t_exchange_emit_ns",
    "t_msg_received_ns",
    "t_strategy_visible_ns",
    "t_strategy_triggered_ns",
    "t_order_constructed_ns",
    "decision_ns",
]


def now_ns() -> int:
    return time.monotonic_ns()


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _config_value(config: Dict[str, Any], key: str, default: Any) -> Any:
    return config.get(key, config.get(key.replace("_", "-"), default))


def _enum_value(container: Any, name: str, default: Any) -> Any:
    return getattr(container, name, default)


def _side_name(side: Any) -> str:
    text = str(side)
    if text.lower().endswith("buy") or text.upper() == "BUY":
        return "BUY"
    if text.lower().endswith("sell") or text.upper() == "SELL":
        return "SELL"
    return text


class TraceWriter:
    def __init__(self, path: str):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(self.file, fieldnames=TRACE_FIELDS)
        if self.path.stat().st_size == 0:
            self.writer.writeheader()
            self.file.flush()

    def write(self, row: Dict[str, Any]) -> None:
        self.writer.writerow({field: row.get(field, "") for field in TRACE_FIELDS})
        self.file.flush()

    def close(self) -> None:
        self.file.close()


class AsyncTraceWriter:
    def __init__(self, path: str, flush_interval_s: float = 0.1):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.flush_interval_s = flush_interval_s
        self.queue: queue.SimpleQueue[Any] = queue.SimpleQueue()
        self.closed = threading.Event()
        self.file = self.path.open("a", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(self.file, fieldnames=TRACE_FIELDS)
        if self.path.stat().st_size == 0:
            self.writer.writeheader()
            self.file.flush()
        self.thread = threading.Thread(target=self._run, name="benchmark-trace-writer", daemon=True)
        self.thread.start()

    def write(self, row: Dict[str, Any]) -> None:
        if not self.closed.is_set():
            self.queue.put(row)

    def close(self) -> None:
        if self.closed.is_set():
            return
        self.closed.set()
        self.queue.put(None)
        self.thread.join()
        self._drain()
        self.file.flush()
        self.file.close()

    def _run(self) -> None:
        last_flush = time.monotonic()
        while True:
            row = self.queue.get()
            if row is None:
                break
            self._write_row(row)
            now = time.monotonic()
            if now - last_flush >= self.flush_interval_s:
                self.file.flush()
                last_flush = now
        self._drain()
        self.file.flush()

    def _drain(self) -> None:
        while True:
            try:
                row = self.queue.get_nowait()
            except queue.Empty:
                return
            if row is not None:
                self._write_row(row)

    def _write_row(self, row: Dict[str, Any]) -> None:
        self.writer.writerow({field: row.get(field, "") for field in TRACE_FIELDS})


class NullTraceWriter:
    def write(self, row: Dict[str, Any]) -> None:
        pass

    def close(self) -> None:
        pass


def _env_value(name: str, default: Any = None) -> Any:
    value = os.getenv(name)
    return default if value is None or value == "" else value


def _make_trace_writer(path: str, config: Dict[str, Any]):
    mode = str(_env_value("GZ_BENCH_TRACE_MODE", _config_value(config, "trace_mode", "csv"))).strip().lower()
    if mode in {"0", "off", "none", "disabled", "journal"}:
        return NullTraceWriter()
    if mode in {"async", "buffered"}:
        interval = float(_env_value("GZ_BENCH_TRACE_FLUSH_INTERVAL_S", _config_value(config, "trace_flush_interval_s", 0.1)))
        return AsyncTraceWriter(path, interval)
    return TraceWriter(path)


def pre_start(context):
    config = context.get_config()
    symbol = _config_value(config, "symbol", "BTC-USDT")
    md_source = _config_value(config, "md_source", "mock")
    td_source = _config_value(config, "td_source", "mock")
    account = _config_value(config, "account", "benchmark")
    exchange_id = _config_value(config, "exchange", "mock")
    instrument_type = _enum_value(InstrumentType, _config_value(config, "instrument_type", "Spot"), InstrumentType.Spot)

    if hasattr(context, "add_account"):
        context.add_account(td_source, account)
    context.subscribe(md_source, [symbol], instrument_type, exchange_id)

    trace_path = _config_value(config, "strategy_trace_path", "traces/raw/simple_benchmark_strategy.csv")
    context.set_object("benchmark_trace", _make_trace_writer(trace_path, config))
    context.set_object("benchmark_orders", 0)
    context.set_object("benchmark_last_event_id", None)
    context.log().info(f"simple benchmark strategy subscribed: {symbol} from {md_source}")


def pre_stop(context):
    trace = context.get_object("benchmark_trace")
    if trace is not None:
        trace.close()


def on_depth(context, depth):
    _on_quote(context, depth)


def on_ticker(context, ticker):
    _on_quote(context, ticker)


def _on_quote(context, quote):
    config = context.get_config()
    symbol = _config_value(config, "symbol", "BTC-USDT")
    if _get(quote, "symbol") != symbol:
        return

    event_id = _get(quote, "event_id", _get(quote, "data_time", now_ns()))
    if _config_value(config, "dedupe_event_id", True):
        last_event_id = context.get_object("benchmark_last_event_id")
        if last_event_id == event_id:
            return
        context.set_object("benchmark_last_event_id", event_id)

    orders = int(context.get_object("benchmark_orders") or 0)
    max_orders = int(_config_value(config, "max_orders", 1000))
    if orders >= max_orders:
        return

    t_strategy_visible_ns = now_ns()
    t_strategy_triggered_ns = now_ns()
    side = _next_side(config, orders)
    price = _next_price(config, quote, side)
    qty = float(_config_value(config, "qty", 0.001))
    account = _config_value(config, "account", "benchmark")
    exchange_id = _config_value(config, "exchange", "mock")
    instrument_type = _enum_value(InstrumentType, _config_value(config, "instrument_type", "Spot"), InstrumentType.Spot)
    order_type = _enum_value(OrderType, _config_value(config, "order_type", "Limit"), OrderType.Limit)

    t_order_constructed_ns = now_ns()
    side_text = _side_name(side)
    trace = context.get_object("benchmark_trace")
    if trace is not None:
        trace.write(
            {
                "run_id": _config_value(config, "run_id", "local"),
                "system": "godzilla",
                "event_id": event_id,
                "symbol": symbol,
                "side": side_text,
                "order_id": "",
                "client_order_id": f"gz-{event_id}-{side_text}",
                "t_exchange_emit_ns": _get(quote, "t_exchange_emit_ns", ""),
                "t_msg_received_ns": _get(quote, "t_msg_received_ns", _get(quote, "data_time", "")),
                "t_strategy_visible_ns": t_strategy_visible_ns,
                "t_strategy_triggered_ns": t_strategy_triggered_ns,
                "t_order_constructed_ns": t_order_constructed_ns,
                "decision_ns": t_order_constructed_ns - t_strategy_triggered_ns,
            }
        )

    try:
        context.insert_order(symbol, instrument_type, exchange_id, account, price, qty, order_type, side)
        context.set_object("benchmark_orders", orders + 1)
    except Exception as exc:
        context.log().error(f"simple benchmark insert_order failed after trace write: {exc}")
        context.set_object("benchmark_orders", orders + 1)


def _next_side(config: Dict[str, Any], order_count: int):
    mode = str(_config_value(config, "side_mode", "alternate")).lower()
    if mode == "sell":
        return Side.Sell
    if mode == "buy":
        return Side.Buy
    return Side.Buy if order_count % 2 == 0 else Side.Sell


def _first_number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (list, tuple)):
        if not value:
            return default
        value = value[0]
    return float(value)


def _next_price(config: Dict[str, Any], quote: Any, side: Any) -> float:
    tick_size = float(_config_value(config, "tick_size", 0.5))
    fixed_price = _config_value(config, "fixed_price", None)
    if fixed_price is not None:
        return float(fixed_price)

    side_text = _side_name(side)
    if side_text == "BUY":
        bid = _get(quote, "bid_price", _get(quote, "bid_px", 0.0))
        return _first_number(bid) - tick_size

    ask = _get(quote, "ask_price", _get(quote, "ask_px", 0.0))
    return _first_number(ask) + tick_size
