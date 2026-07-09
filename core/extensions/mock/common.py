import csv
import json
import os
import queue
import socket
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


DEFAULT_MD_HOST = "127.0.0.1"
DEFAULT_MD_PORT = 19001
DEFAULT_ORDER_HOST = "127.0.0.1"
DEFAULT_ORDER_PORT = 19002

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_DATASET = PACKAGE_DIR / "btcusdt_bookticker_sample.csv"
if os.getenv("GZ_TRACE_DIR"):
    DEFAULT_TRACE_DIR = Path(os.getenv("GZ_TRACE_DIR")).expanduser().resolve()
else:
    DEFAULT_TRACE_DIR = PACKAGE_DIR / "traces" / "raw"


def now_ns() -> int:
    return time.monotonic_ns()


def load_config(config: Any) -> Dict[str, Any]:
    if config is None or config == "":
        return {}
    if isinstance(config, dict):
        return dict(config)
    if isinstance(config, str):
        try:
            return json.loads(config)
        except json.JSONDecodeError:
            path = Path(config).expanduser()
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
            raise
    return {}


def config_value(config: Dict[str, Any], key: str, default: Any) -> Any:
    return config.get(key, config.get(key.replace("_", "-"), default))


def resolve_path(value: Optional[str], default: Path) -> Path:
    path = Path(value).expanduser() if value else default
    if not path.is_absolute():
        path = PACKAGE_DIR / path
    return path


class TraceWriter:
    def __init__(self, path: Path, fieldnames: Iterable[str]):
        self.path = path
        self.fieldnames = list(fieldnames)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._file = self.path.open("a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=self.fieldnames)
        if self.path.stat().st_size == 0:
            self._writer.writeheader()
            self._file.flush()

    def write(self, row: Dict[str, Any]) -> None:
        with self._lock:
            self._writer.writerow({name: row.get(name, "") for name in self.fieldnames})
            self._file.flush()

    def close(self) -> None:
        with self._lock:
            self._file.close()


class AsyncTraceWriter:
    def __init__(self, path: Path, fieldnames: Iterable[str], flush_interval_s: float = 0.1):
        self.path = path
        self.fieldnames = list(fieldnames)
        self.flush_interval_s = flush_interval_s
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._queue: queue.SimpleQueue[Optional[Dict[str, Any]]] = queue.SimpleQueue()
        self._closed = threading.Event()
        self._file = self.path.open("a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=self.fieldnames)
        if self.path.stat().st_size == 0:
            self._writer.writeheader()
            self._file.flush()
        self._thread = threading.Thread(target=self._run, name=f"trace-writer-{self.path.name}", daemon=True)
        self._thread.start()

    def write(self, row: Dict[str, Any]) -> None:
        if not self._closed.is_set():
            self._queue.put(row)

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        self._queue.put(None)
        self._thread.join()
        self._drain()
        self._file.flush()
        self._file.close()

    def _run(self) -> None:
        last_flush = time.monotonic()
        while True:
            row = self._queue.get()
            if row is None:
                break
            self._write_row(row)
            now = time.monotonic()
            if now - last_flush >= self.flush_interval_s:
                self._file.flush()
                last_flush = now
        self._drain()
        self._file.flush()

    def _drain(self) -> None:
        while True:
            try:
                row = self._queue.get_nowait()
            except queue.Empty:
                return
            if row is not None:
                self._write_row(row)

    def _write_row(self, row: Dict[str, Any]) -> None:
        self._writer.writerow({name: row.get(name, "") for name in self.fieldnames})


class NullTraceWriter:
    def write(self, row: Dict[str, Any]) -> None:
        pass

    def close(self) -> None:
        pass


def trace_mode(config: Optional[Dict[str, Any]] = None) -> str:
    config = config or {}
    return str(env_value("GZ_BENCH_TRACE_MODE", config_value(config, "trace_mode", "csv"))).strip().lower()


def make_trace_writer(path: Path, fieldnames: Iterable[str], config: Optional[Dict[str, Any]] = None):
    mode = trace_mode(config)
    if mode in {"0", "off", "none", "disabled", "journal"}:
        return NullTraceWriter()
    if mode in {"async", "buffered"}:
        interval = float(env_value("GZ_BENCH_TRACE_FLUSH_INTERVAL_S", config_value(config or {}, "trace_flush_interval_s", 0.1)))
        return AsyncTraceWriter(path, fieldnames, interval)
    return TraceWriter(path, fieldnames)


class JsonLineClient:
    def __init__(self, host: str, port: int, timeout_s: float = 5.0):
        self.host = host
        self.port = int(port)
        self.timeout_s = timeout_s
        self._sock: Optional[socket.socket] = None
        self._file = None

    def connect(self) -> "JsonLineClient":
        self._sock = socket.create_connection((self.host, self.port), self.timeout_s)
        self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._file = self._sock.makefile("rwb", buffering=0)
        return self

    def iter_json(self):
        if self._file is None:
            raise RuntimeError("JsonLineClient is not connected")
        while True:
            line = self._file.readline()
            if not line:
                return
            yield json.loads(line.decode("utf-8"))

    def send_json(self, msg: Dict[str, Any]) -> None:
        if self._file is None:
            raise RuntimeError("JsonLineClient is not connected")
        self._file.write(json.dumps(msg, separators=(",", ":")).encode("utf-8") + b"\n")

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
        if self._sock is not None:
            self._sock.close()
            self._sock = None


def get_field(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def env_value(name: str, default: Any = None) -> Any:
    value = os.getenv(name)
    return default if value is None or value == "" else value


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)
