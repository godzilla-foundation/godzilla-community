import csv
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
    context.set_object("benchmark_trace", TraceWriter(trace_path))
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
