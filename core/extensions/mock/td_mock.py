from typing import Any, Dict, Optional

import pywingchun
import pyyjj
import kungfu.wingchun.msg as wc_msg
from kungfu.yijinjing.log import create_logger

from .common import (
    DEFAULT_ORDER_HOST,
    DEFAULT_ORDER_PORT,
    DEFAULT_TRACE_DIR,
    JsonLineClient,
    make_trace_writer,
    config_value,
    env_bool,
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


class MockTd(pywingchun.Trader):
    def __init__(self, low_latency: bool, locator: Any, account_id: str, json_config: str):
        pywingchun.Trader.__init__(self, low_latency, locator, "mock", account_id)
        self.account_id = account_id
        self.config = load_config(json_config)
        self.host = config_value(self.config, "order_host", DEFAULT_ORDER_HOST)
        self.port = int(config_value(self.config, "order_port", DEFAULT_ORDER_PORT))
        self.no_socket = env_bool("GZ_MOCK_TD_NO_SOCKET", bool(config_value(self.config, "no_socket", False)))
        self.default_status = config_value(self.config, "order_status", "Submitted")
        self.client: Optional[JsonLineClient] = None
        self.trace = make_trace_writer(
            resolve_path(config_value(self.config, "td_trace_path", None), DEFAULT_TRACE_DIR / "mock_td.csv"),
            TD_TRACE_FIELDS,
            self.config,
        )
        self.logger = create_logger(
            "mock_td",
            config_value(self.config, "log_level", "info"),
            pyyjj.location(pyyjj.mode.LIVE, pyyjj.category.TD, "mock", account_id, locator),
        )
        self.sent_count = 0

    def on_start(self):
        if not self.no_socket:
            self.client = JsonLineClient(self.host, self.port).connect()
        else:
            self.logger.info("mock td no-socket shm benchmark mode enabled")
        pywingchun.Trader.on_start(self)

    def insert_order(self, event):
        order_input = event.data
        msg = self._send_order_input(order_input)
        self._write_order_report(event, order_input)
        self.sent_count += 1
        if self.sent_count <= 3:
            self.logger.info(f"mock order sent: {msg}")
        return True

    def cancel_order(self, event):
        return True

    def req_account(self):
        return False

    def req_position(self):
        return False

    def _send_order_input(self, order_input: Any) -> Dict[str, Any]:
        if not self.no_socket and self.client is None:
            self.client = JsonLineClient(self.host, self.port).connect()

        t_order_constructed_ns = now_ns()
        t_order_socket_write_ns = now_ns()
        event_id = getattr(order_input, "event_id", getattr(order_input, "order_id", ""))
        client_order_id = getattr(order_input, "client_order_id", f"gz-{event_id}")
        msg = {
            "type": "order",
            "event_id": event_id,
            "client_order_id": client_order_id,
            "symbol": getattr(order_input, "symbol", ""),
            "side": self._side_name(getattr(order_input, "side", "")),
            "price": float(getattr(order_input, "price", getattr(order_input, "limit_price", 0.0))),
            "qty": float(getattr(order_input, "volume", getattr(order_input, "qty", 0.0))),
            "t_order_socket_write_ns": t_order_socket_write_ns,
        }
        if not self.no_socket:
            self.client.send_json(msg)
        self.trace.write(
            {
                **msg,
                "t_order_constructed_ns": t_order_constructed_ns,
                "t_order_socket_write_ns": t_order_socket_write_ns,
            }
        )
        return msg

    def _write_order_report(self, event: Any, order_input: Any) -> None:
        order = pywingchun.utils.order_from_input(order_input)
        status = getattr(pywingchun.constants.OrderStatus, self.default_status, pywingchun.constants.OrderStatus.Submitted)
        order.status = status
        order.volume_left = order.volume - order.volume_traded
        self.get_writer(event.source).write_data(0, wc_msg.Order, order)

    def _side_name(self, side: Any) -> str:
        if side == getattr(pywingchun.constants.Side, "Buy", None):
            return "BUY"
        if side == getattr(pywingchun.constants.Side, "Sell", None):
            return "SELL"
        text = str(side)
        if text.lower().endswith("buy"):
            return "BUY"
        if text.lower().endswith("sell"):
            return "SELL"
        return text


TraderMock = MockTd
