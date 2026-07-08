from dataclasses import dataclass
from typing import Any, Dict, Optional

try:
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
except ImportError:
    from common import (  # type: ignore
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


@dataclass
class MockQuote:
    source: str
    symbol: str
    bid_price: float
    bid_qty: float
    ask_price: float
    ask_qty: float
    event_id: int
    t_exchange_emit_ns: int
    t_msg_received_ns: int


class MockMd:
    def __init__(self, low_latency: bool = False, locator: Any = None, account_config: Any = None):
        self.low_latency = low_latency
        self.locator = locator
        self.config = load_config(account_config)
        self.host = config_value(self.config, "md_host", DEFAULT_MD_HOST)
        self.port = int(config_value(self.config, "md_port", DEFAULT_MD_PORT))
        self.source_id = config_value(self.config, "source_id", "mock")
        self.trace = TraceWriter(
            resolve_path(config_value(self.config, "md_trace_path", None), DEFAULT_TRACE_DIR / "mock_md.csv"),
            MD_TRACE_FIELDS,
        )
        self.client: Optional[JsonLineClient] = None
        self.last_quote: Optional[MockQuote] = None

    def run(self) -> None:
        self.client = JsonLineClient(self.host, self.port).connect()
        try:
            for msg in self.client.iter_json():
                if msg.get("type") != "bookTicker":
                    continue
                quote = self._quote_from_msg(msg)
                t_strategy_visible_ns = now_ns()
                self.last_quote = quote
                self._publish_quote(quote)
                self.trace.write(
                    {
                        "event_id": quote.event_id,
                        "symbol": quote.symbol,
                        "t_exchange_emit_ns": quote.t_exchange_emit_ns,
                        "t_msg_received_ns": quote.t_msg_received_ns,
                        "t_strategy_visible_ns": t_strategy_visible_ns,
                        "md_ingest_ns": t_strategy_visible_ns - quote.t_msg_received_ns,
                    }
                )
        finally:
            if self.client is not None:
                self.client.close()
            self.trace.close()

    def _quote_from_msg(self, msg: Dict[str, Any]) -> MockQuote:
        return MockQuote(
            source=self.source_id,
            symbol=str(msg["symbol"]),
            bid_price=float(msg["bid_px"]),
            bid_qty=float(msg["bid_qty"]),
            ask_price=float(msg["ask_px"]),
            ask_qty=float(msg["ask_qty"]),
            event_id=int(msg["event_id"]),
            t_exchange_emit_ns=int(msg["t_exchange_emit_ns"]),
            t_msg_received_ns=now_ns(),
        )

    def _publish_quote(self, quote: MockQuote) -> None:
        if hasattr(self, "write_quote"):
            self.write_quote(quote)  # type: ignore[attr-defined]
            return

        writer_getter = getattr(self, "get_writer", None)
        if writer_getter is None:
            return

        try:
            import pywingchun
            from kungfu.wingchun import msg as wc_msg
        except ImportError:
            return

        writer = writer_getter(0)
        depth = writer.open_data(0, wc_msg.Depth)
        depth.source_id = self.source_id
        depth.data_time = quote.t_msg_received_ns
        depth.symbol = quote.symbol
        depth.exchange_id = "mock"
        depth.instrument_type = getattr(pywingchun.constants.InstrumentType, "Spot", 0)
        depth.bid_price[0] = quote.bid_price
        depth.bid_volume[0] = quote.bid_qty
        depth.ask_price[0] = quote.ask_price
        depth.ask_volume[0] = quote.ask_qty
        writer.close_data()
