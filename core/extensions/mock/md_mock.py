import threading
from typing import Any, Dict, Optional

import pywingchun
import pyyjj
import kungfu.wingchun.msg as wc_msg
from kungfu.yijinjing.log import create_logger

from .common import (
    DEFAULT_MD_HOST,
    DEFAULT_MD_PORT,
    DEFAULT_TRACE_DIR,
    JsonLineClient,
    TraceWriter,
    config_value,
    load_config,
    now_ns,
    resolve_path,
)


MD_TRACE_FIELDS = [
    "event_id",
    "symbol",
    "t_exchange_emit_ns",
    "t_msg_received_ns",
    "t_strategy_visible_ns",
    "md_ingest_ns",
]


class MockMd(pywingchun.MarketData):
    def __init__(self, low_latency: bool, locator: Any, config_json: str):
        pywingchun.MarketData.__init__(self, low_latency, locator, "mock")
        self.config = load_config(config_json)
        self.host = config_value(self.config, "md_host", DEFAULT_MD_HOST)
        self.port = int(config_value(self.config, "md_port", DEFAULT_MD_PORT))
        self.source_id = config_value(self.config, "source_id", "mock")
        self.exchange_id = config_value(self.config, "exchange", "mock")
        self.instrument_type = getattr(
            pywingchun.constants.InstrumentType,
            config_value(self.config, "instrument_type", "Spot"),
            pywingchun.constants.InstrumentType.Spot,
        )
        self.trace = TraceWriter(
            resolve_path(config_value(self.config, "md_trace_path", None), DEFAULT_TRACE_DIR / "mock_md.csv"),
            MD_TRACE_FIELDS,
        )
        self.logger = create_logger(
            "mock_md",
            config_value(self.config, "log_level", "info"),
            pyyjj.location(pyyjj.mode.LIVE, pyyjj.category.MD, "mock", "mock", locator),
        )
        self.client: Optional[JsonLineClient] = None
        self.thread: Optional[threading.Thread] = None
        self.running = False
        self.subscribed_symbols = set()

    def on_start(self):
        self.running = True
        self.thread = threading.Thread(target=self._read_replay_stream, name="mock-md-replay", daemon=True)
        self.thread.start()
        pywingchun.MarketData.on_start(self)

    def subscribe(self, instruments):
        for inst in instruments:
            self.subscribed_symbols.add(inst.symbol)
        return True

    def unsubscribe(self, instruments):
        for inst in instruments:
            self.subscribed_symbols.discard(inst.symbol)
        return True

    def _read_replay_stream(self):
        try:
            self.client = JsonLineClient(self.host, self.port).connect()
            for msg in self.client.iter_json():
                if not self.running:
                    break
                if msg.get("type") != "bookTicker":
                    continue
                symbol = str(msg["symbol"])
                if self.subscribed_symbols and symbol not in self.subscribed_symbols:
                    continue
                self._publish_book_ticker(msg)
        except Exception as exc:
            self.logger.error(f"mock md replay stream stopped: {exc}")
        finally:
            if self.client is not None:
                self.client.close()
                self.client = None
            self.trace.close()

    def _publish_book_ticker(self, msg: Dict[str, Any]):
        t_msg_received_ns = now_ns()
        depth = pywingchun.Depth()
        depth.source_id = self.source_id
        depth.data_time = t_msg_received_ns
        depth.symbol = str(msg["symbol"])
        depth.exchange_id = self.exchange_id
        depth.instrument_type = self.instrument_type
        depth.bid_price = [float(msg["bid_px"])]
        depth.bid_volume = [float(msg["bid_qty"])]
        depth.ask_price = [float(msg["ask_px"])]
        depth.ask_volume = [float(msg["ask_qty"])]

        # Python strategy code can read these attrs when the binding allows it;
        # native Depth consumers still use data_time and book fields above.
        self._try_setattr(depth, "event_id", int(msg["event_id"]))
        self._try_setattr(depth, "t_exchange_emit_ns", int(msg["t_exchange_emit_ns"]))
        self._try_setattr(depth, "t_msg_received_ns", t_msg_received_ns)

        t_strategy_visible_ns = now_ns()
        self.get_writer(0).write_data(0, wc_msg.Depth, depth)
        self.trace.write(
            {
                "event_id": int(msg["event_id"]),
                "symbol": depth.symbol,
                "t_exchange_emit_ns": int(msg["t_exchange_emit_ns"]),
                "t_msg_received_ns": t_msg_received_ns,
                "t_strategy_visible_ns": t_strategy_visible_ns,
                "md_ingest_ns": t_strategy_visible_ns - t_msg_received_ns,
            }
        )

    def _try_setattr(self, obj: Any, name: str, value: Any) -> None:
        try:
            setattr(obj, name, value)
        except Exception:
            pass


MarketDataMock = MockMd
