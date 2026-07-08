import sys
from typing import Any, Dict, Optional

try:
    from .common import (
        DEFAULT_ORDER_HOST,
        DEFAULT_ORDER_PORT,
        DEFAULT_TRACE_DIR,
        JsonLineClient,
        TraceWriter,
        config_value,
        get_field,
        load_config,
        now_ns,
        resolve_path,
    )
except ImportError:
    from common import (  # type: ignore
        DEFAULT_ORDER_HOST,
        DEFAULT_ORDER_PORT,
        DEFAULT_TRACE_DIR,
        JsonLineClient,
        TraceWriter,
        config_value,
        get_field,
        load_config,
        now_ns,
        resolve_path,
    )


TD_TRACE_FIELDS = [
    "event_id",
    "client_order_id",
    "symbol",
    "side",
    "price",
    "qty",
    "t_order_constructed_ns",
    "t_order_socket_write_ns",
]


class MockTd:
    def __init__(self, low_latency: bool = False, locator: Any = None, account: str = "", account_config: Any = None):
        self.low_latency = low_latency
        self.locator = locator
        self.account = account
        self.config = load_config(account_config)
        self.host = config_value(self.config, "order_host", DEFAULT_ORDER_HOST)
        self.port = int(config_value(self.config, "order_port", DEFAULT_ORDER_PORT))
        self.trace = TraceWriter(
            resolve_path(config_value(self.config, "td_trace_path", None), DEFAULT_TRACE_DIR / "mock_td.csv"),
            TD_TRACE_FIELDS,
        )
        self.client: Optional[JsonLineClient] = None

    def run(self) -> None:
        self.client = JsonLineClient(self.host, self.port).connect()
        try:
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                self.send_order(load_config(line))
        finally:
            self.close()

    def insert_order(self, event: Any) -> bool:
        order = get_field(event, "data", event)
        self.send_order(order)
        return True

    def send_order(self, order: Any) -> Dict[str, Any]:
        if self.client is None:
            self.client = JsonLineClient(self.host, self.port).connect()

        t_order_constructed_ns = int(get_field(order, "t_order_constructed_ns", now_ns()))
        t_order_socket_write_ns = now_ns()
        event_id = get_field(order, "event_id", get_field(order, "order_id", ""))
        client_order_id = get_field(order, "client_order_id", f"gz-{event_id}")
        msg = {
            "type": "order",
            "event_id": event_id,
            "client_order_id": client_order_id,
            "symbol": get_field(order, "symbol", ""),
            "side": str(get_field(order, "side", "")),
            "price": float(get_field(order, "price", get_field(order, "limit_price", 0.0))),
            "qty": float(get_field(order, "qty", get_field(order, "volume", 0.0))),
            "t_order_socket_write_ns": t_order_socket_write_ns,
        }
        self.client.send_json(msg)
        self.trace.write(
            {
                **msg,
                "t_order_constructed_ns": t_order_constructed_ns,
                "t_order_socket_write_ns": t_order_socket_write_ns,
            }
        )
        return msg

    def close(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None
        self.trace.close()
