import argparse
import asyncio
import csv
import json
from pathlib import Path
from typing import Dict

try:
    from .common import (
        DEFAULT_DATASET,
        DEFAULT_MD_HOST,
        DEFAULT_MD_PORT,
        DEFAULT_ORDER_HOST,
        DEFAULT_ORDER_PORT,
        DEFAULT_TRACE_DIR,
        TraceWriter,
        now_ns,
    )
except ImportError:
    from common import (  # type: ignore
        DEFAULT_DATASET,
        DEFAULT_MD_HOST,
        DEFAULT_MD_PORT,
        DEFAULT_ORDER_HOST,
        DEFAULT_ORDER_PORT,
        DEFAULT_TRACE_DIR,
        TraceWriter,
        now_ns,
    )


ORDER_TRACE_FIELDS = [
    "event_id",
    "client_order_id",
    "symbol",
    "side",
    "price",
    "qty",
    "t_order_socket_write_ns",
    "t_order_received_ns",
    "t_ack_ns",
]


class ReplayServer:
    def __init__(
        self,
        dataset: Path = DEFAULT_DATASET,
        md_host: str = DEFAULT_MD_HOST,
        md_port: int = DEFAULT_MD_PORT,
        order_host: str = DEFAULT_ORDER_HOST,
        order_port: int = DEFAULT_ORDER_PORT,
        order_trace_path: Path = DEFAULT_TRACE_DIR / "mock_exchange_orders.csv",
        loop: bool = False,
    ):
        self.dataset = Path(dataset)
        self.md_host = md_host
        self.md_port = int(md_port)
        self.order_host = order_host
        self.order_port = int(order_port)
        self.order_trace = TraceWriter(Path(order_trace_path), ORDER_TRACE_FIELDS)
        self.loop = loop

    async def handle_md_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        del reader
        try:
            while True:
                with self.dataset.open(newline="", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        delay_ns = int(row.get("delay_ns") or 0)
                        if delay_ns > 0:
                            await asyncio.sleep(delay_ns / 1_000_000_000)

                        msg = self._book_ticker_from_row(row)
                        writer.write(json.dumps(msg, separators=(",", ":")).encode("utf-8") + b"\n")
                        await writer.drain()
                if not self.loop:
                    break
        finally:
            writer.close()
            await writer.wait_closed()

    async def handle_order_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while True:
            line = await reader.readline()
            if not line:
                break

            t_order_received_ns = now_ns()
            order = json.loads(line.decode("utf-8"))
            t_ack_ns = now_ns()
            ack = {
                "type": "ack",
                "client_order_id": order.get("client_order_id"),
                "event_id": order.get("event_id"),
                "status": "ACCEPTED",
                "t_ack_ns": t_ack_ns,
            }
            self.order_trace.write(
                {
                    **order,
                    "t_order_received_ns": t_order_received_ns,
                    "t_ack_ns": t_ack_ns,
                }
            )
            writer.write(json.dumps(ack, separators=(",", ":")).encode("utf-8") + b"\n")
            await writer.drain()

        writer.close()
        await writer.wait_closed()

    def _book_ticker_from_row(self, row: Dict[str, str]) -> Dict[str, object]:
        return {
            "type": "bookTicker",
            "event_id": int(row["event_id"]),
            "symbol": row["symbol"],
            "bid_px": float(row["bid_px"]),
            "bid_qty": float(row["bid_qty"]),
            "ask_px": float(row["ask_px"]),
            "ask_qty": float(row["ask_qty"]),
            "t_exchange_emit_ns": now_ns(),
        }

    async def run(self) -> None:
        md_server = await asyncio.start_server(self.handle_md_client, self.md_host, self.md_port)
        order_server = await asyncio.start_server(self.handle_order_client, self.order_host, self.order_port)

        print(f"MD replay server listening on {self.md_host}:{self.md_port}")
        print(f"Order endpoint listening on {self.order_host}:{self.order_port}")
        print(f"Dataset: {self.dataset}")

        async with md_server, order_server:
            await asyncio.gather(md_server.serve_forever(), order_server.serve_forever())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mock exchange replay server for godzilla.dev benchmarks")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--md-host", default=DEFAULT_MD_HOST)
    parser.add_argument("--md-port", type=int, default=DEFAULT_MD_PORT)
    parser.add_argument("--order-host", default=DEFAULT_ORDER_HOST)
    parser.add_argument("--order-port", type=int, default=DEFAULT_ORDER_PORT)
    parser.add_argument("--order-trace", type=Path, default=DEFAULT_TRACE_DIR / "mock_exchange_orders.csv")
    parser.add_argument("--loop", action="store_true", help="Replay the dataset repeatedly for long-running benchmarks")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server = ReplayServer(
        dataset=args.dataset,
        md_host=args.md_host,
        md_port=args.md_port,
        order_host=args.order_host,
        order_port=args.order_port,
        order_trace_path=args.order_trace,
        loop=args.loop,
    )
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
