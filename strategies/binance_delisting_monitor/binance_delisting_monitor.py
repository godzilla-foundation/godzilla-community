#!/usr/bin/env python3
"""抓取 Binance 公告，筛出下架（delisting）相关的通知。

每天跑一次即可（cron 或 --interval）。已经上报过的公告会记录在状态文件里，
下次运行只输出新增的，方便直接接告警。

用法:
    python3 binance_delisting_monitor.py                    # 抓一次，输出新增的下架公告
    python3 binance_delisting_monitor.py --all              # 忽略状态文件，输出全部命中项
    python3 binance_delisting_monitor.py --json             # JSON 输出，方便管道处理
    python3 binance_delisting_monitor.py --webhook <url>    # 推送到飞书/钉钉/企微/Slack
    python3 binance_delisting_monitor.py --interval 86400   # 常驻，每天抓一次
    python3 binance_delisting_monitor.py --selftest         # 只检查网络连通性
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests

LOG = logging.getLogger("binance-delisting")

# ---------------------------------------------------------------- 接口配置

# 公告接口只在 www 域名上提供，api.binance.com 的 ELB 会直接 403。
API_HOSTS = (
    "https://www.binance.com",
    "https://www.binance.info",
)

# 这个名字容易误导：catalog/list/query 实际上要求 catalogId，返回的是该
# 分区的文章列表；不带 catalogId 的分区发现应使用 article/list/query。
CATALOG_PATH = "/bapi/composite/v1/public/cms/article/catalog/list/query"
ARTICLE_PATHS = (
    "/bapi/composite/v1/public/cms/article/list/query",
    "/bapi/apex/v1/public/apex/cms/article/list/query",
    CATALOG_PATH,
)
ARTICLE_URL = "https://www.binance.com/{lang}/support/announcement/{code}"

# 公告分区。不传 --catalog 时会自动发现全部分区，这里只作为发现失败时的兜底。
FALLBACK_CATALOGS = {
    161: "Delisting",
    48: "New Cryptocurrency Listing",
    49: "Latest Binance News",
    93: "API Updates",
}

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.binance.com/en/support/announcement",
    "clienttype": "web",
}

# ---------------------------------------------------------------- 关键词

# 命中任意一条即视为下架公告。中英文都覆盖，币安中文站用「下架」「停止交易」。
DELIST_PATTERNS = [
    r"de-?list",                                   # delist / delisting / delisted / de-list
    r"\bremov(?:e|es|ed|al)\b",                    # will remove / removal of
    r"ceas(?:e|es|ing)\s+(?:the\s+)?trading",
    r"terminat\w*\s+(?:the\s+)?(?:trading|support|service)",
    r"discontinu\w*\s+(?:the\s+)?(?:trading|support|service)",
    r"suspend\w*\s+(?:the\s+)?(?:spot\s+)?trading",
    r"下架",
    r"下線",
    r"下线",
    r"移除",
    r"停止.{0,4}交易",
    r"终止.{0,6}(?:交易|服务|支持)",
    r"終止.{0,6}(?:交易|服務|支援)",
]

# 明显误报的标题（撤销下架、恢复交易之类）直接排除。
EXCLUDE_PATTERNS = [
    r"cancel\w*\s+the\s+(?:delisting|removal)",
    r"resum\w*\s+(?:the\s+)?trading",
    r"取消下架",
    r"恢复交易",
]

# 从标题里抠交易对/币种。
QUOTE_ASSETS = "USDT|USDC|BUSD|FDUSD|TUSD|BTC|ETH|BNB|TRY|EUR|BRL|ARS|DAI"
PAIR_RE = re.compile(rf"\b([A-Z0-9]{{2,12}})[/_-]?({QUOTE_ASSETS})\b")
TICKER_IN_PARENS_RE = re.compile(r"[(（]\s*([A-Z][A-Z0-9]{0,11})\s*[)）]")
# 「Will Delist AGLD, LOOM, POLS, RARE」这种裸 ticker 列表最常见，
# 标题是 Title Case，所以全大写词基本就是币种代码。
BARE_TICKER_RE = re.compile(r"\b(?=[A-Z0-9]{2,12}\b)(?=[A-Z0-9]*[A-Z])[A-Z0-9]+\b")
# 全大写但不是币种的常见词，避免误抓。
NOT_TICKERS = {
    "AMA", "AML", "API", "APR", "APY", "ATH", "BNB", "CEO", "CET", "CNY", "DEX",
    "EOD", "ETF", "EST", "EUR", "FAQ", "FIX", "GMT", "HKD", "IEO", "IOU", "JPY",
    "KRW", "KYC", "NFT", "P2P", "PDF", "PST", "RMB", "ROI", "SDK", "SEC", "SEPA",
    "SWIFT", "TBD", "TRY", "TWD", "UID", "URL", "USA", "USD", "UTC", "VIP", "VPN",
    "AND", "FOR", "THE", "WILL", "NEW", "ALL", "OTC", "SPOT", "USDT", "USDC",
    "BUSD", "FDUSD", "TUSD", "DAI", "BRL", "ARS", "ZAR", "IDR", "NGN", "UAH",
    "UK", "US", "EU", "EEA", "UAE", "CIS", "JP", "KR", "CN", "IN", "BR", "TR",
}


# ---------------------------------------------------------------- 数据结构


@dataclass
class Announcement:
    code: str
    title: str
    catalog_id: int
    catalog_name: str
    release_ts: int  # 毫秒
    symbols: list[str] = field(default_factory=list)
    matched: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        return ARTICLE_URL.format(lang="en", code=self.code)

    @property
    def released_at(self) -> str:
        if not self.release_ts:
            return "unknown"
        dt = datetime.fromtimestamp(self.release_ts / 1000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M UTC")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "title": self.title,
            "catalog_id": self.catalog_id,
            "catalog_name": self.catalog_name,
            "release_ts": self.release_ts,
            "released_at": self.released_at,
            "symbols": self.symbols,
            "matched": self.matched,
            "url": self.url,
        }


# ---------------------------------------------------------------- 抓取


class BinanceAnnouncements:
    def __init__(
        self,
        lang: str = "en",
        timeout: float = 20.0,
        retries: int = 3,
        proxy: str | None = None,
    ) -> None:
        self.lang = lang
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.session.headers["lang"] = lang
        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}
        # 第一次成功的 host 会被记住，避免每次都从头试。
        self._host: str | None = None

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        hosts = [self._host] if self._host else list(API_HOSTS)
        last_err: Exception | None = None

        for host in hosts:
            for attempt in range(1, self.retries + 1):
                url = f"{host}{path}"
                try:
                    resp = self.session.get(url, params=params, timeout=self.timeout)
                    if resp.status_code == 429:
                        wait = min(2 ** attempt, 30)
                        LOG.warning("被限流 (429)，%ss 后重试", wait)
                        time.sleep(wait)
                        continue
                    resp.raise_for_status()
                    payload = resp.json()
                    if not payload.get("success", True):
                        raise RuntimeError(
                            f"接口返回失败: code={payload.get('code')} "
                            f"msg={payload.get('message')}"
                        )
                    self._host = host
                    return payload.get("data") or {}
                except Exception as exc:  # noqa: BLE001 - 逐个 host 降级重试
                    last_err = exc
                    LOG.debug("%s 第 %s 次失败: %s", url, attempt, exc)
                    if attempt < self.retries:
                        time.sleep(min(2 ** attempt, 10))
            # 这个 host 彻底不通，换下一个
            if self._host == host:
                self._host = None

        raise RuntimeError(f"所有接口地址都请求失败，最后一个错误: {last_err}")

    def catalogs(self) -> dict[int, str]:
        """列出全部公告分区，失败时退回硬编码列表。"""
        data: dict[str, Any] = {}
        last_err: Exception | None = None
        params = {"type": 1, "pageNo": 1, "pageSize": 50}
        for path in ARTICLE_PATHS:
            try:
                data = self._get(path, params)
                break
            except Exception as exc:  # noqa: BLE001 - 多套路径互为备份
                last_err = exc
                LOG.debug("分区发现路径 %s 失败: %s", path, exc)
        else:
            LOG.warning("获取分区列表失败（%s），改用内置列表", last_err)
            return dict(FALLBACK_CATALOGS)

        found: dict[int, str] = {}

        def walk(nodes: Iterable[dict[str, Any]]) -> None:
            for node in nodes or []:
                cid = node.get("catalogId")
                if isinstance(cid, int):
                    found[cid] = node.get("catalogName") or str(cid)
                walk(node.get("catalogs") or [])

        walk(data.get("catalogs") or [])
        if not found:
            LOG.warning("分区列表为空，改用内置列表")
            return dict(FALLBACK_CATALOGS)
        return found

    def articles(self, catalog_id: int, pages: int = 1, page_size: int = 50) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for page in range(1, pages + 1):
            params = {
                "type": 1,
                "catalogId": catalog_id,
                "pageNo": page,
                "pageSize": page_size,
            }
            data: dict[str, Any] = {}
            for path in ARTICLE_PATHS:
                try:
                    data = self._get(path, params)
                    break
                except Exception as exc:  # noqa: BLE001 - 多套路径互为备份
                    LOG.debug("路径 %s 失败: %s", path, exc)
            else:
                LOG.warning("分区 %s 第 %s 页抓取失败，跳过", catalog_id, page)
                break

            # Binance 的两个接口版本返回结构并不一致：有的是
            # data.articles，有的是 data.catalogs[*].articles。
            batch = list(data.get("articles") or [])
            if not batch:
                for catalog in data.get("catalogs") or []:
                    if catalog.get("catalogId") in (None, catalog_id):
                        batch.extend(catalog.get("articles") or [])
            out.extend(batch)
            if len(batch) < page_size:
                break
        return out


# ---------------------------------------------------------------- 筛选


def _compile(patterns: Iterable[str]) -> list[re.Pattern[str]]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


def extract_symbols(title: str) -> list[str]:
    """从标题里提取涉及的交易对/币种，去重保序。"""
    symbols: list[str] = []

    for base, quote in PAIR_RE.findall(title):
        pair = f"{base}{quote}"
        if pair not in symbols:
            symbols.append(pair)

    for ticker in TICKER_IN_PARENS_RE.findall(title):
        if ticker not in symbols and not any(s.startswith(ticker) for s in symbols):
            symbols.append(ticker)

    for ticker in BARE_TICKER_RE.findall(title):
        if ticker in NOT_TICKERS or ticker in symbols:
            continue
        if any(s.startswith(ticker) for s in symbols):  # 已经作为交易对收录了
            continue
        symbols.append(ticker)

    return symbols


def is_delisting(
    title: str,
    include: list[re.Pattern[str]],
    exclude: list[re.Pattern[str]],
) -> list[str]:
    """命中返回匹配到的关键词列表，未命中返回空列表。"""
    if any(p.search(title) for p in exclude):
        return []
    return [p.pattern for p in include if p.search(title)]


def collect(
    client: BinanceAnnouncements,
    catalog_ids: list[int] | None,
    pages: int,
    include: list[re.Pattern[str]],
    exclude: list[re.Pattern[str]],
) -> list[Announcement]:
    catalogs = client.catalogs()
    if catalog_ids:
        catalogs = {cid: catalogs.get(cid, str(cid)) for cid in catalog_ids}
    LOG.info("扫描 %s 个分区: %s", len(catalogs), ", ".join(catalogs.values()))

    hits: list[Announcement] = []
    seen_codes: set[str] = set()

    for cid, cname in catalogs.items():
        raw = client.articles(cid, pages=pages)
        LOG.info("分区 %s (%s): %s 条公告", cid, cname, len(raw))
        for item in raw:
            code = item.get("code") or str(item.get("id") or "")
            title = (item.get("title") or "").strip()
            if not code or not title or code in seen_codes:
                continue
            matched = is_delisting(title, include, exclude)
            if not matched:
                continue
            seen_codes.add(code)
            hits.append(
                Announcement(
                    code=code,
                    title=title,
                    catalog_id=cid,
                    catalog_name=cname,
                    release_ts=int(item.get("releaseDate") or 0),
                    symbols=extract_symbols(title),
                    matched=matched,
                )
            )

    hits.sort(key=lambda a: a.release_ts, reverse=True)
    return hits


# ---------------------------------------------------------------- 状态


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"seen": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        LOG.warning("状态文件读取失败（%s），当作空状态处理", exc)
        return {"seen": {}}
    state.setdefault("seen", {})
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)  # 原子替换，中途被 kill 也不会写坏


# ---------------------------------------------------------------- 输出


def format_text(items: list[Announcement]) -> str:
    lines = [f"🚨 Binance 下架公告 {len(items)} 条"]
    for a in items:
        syms = f" [{', '.join(a.symbols)}]" if a.symbols else ""
        lines.append(f"\n• {a.title}{syms}\n  {a.released_at} · {a.catalog_name}\n  {a.url}")
    return "\n".join(lines)


def push_webhook(url: str, text: str, timeout: float = 15.0) -> None:
    """按 URL 猜测机器人类型，构造对应的文本消息体。"""
    if "open.feishu.cn" in url or "larksuite.com" in url:
        payload = {"msg_type": "text", "content": {"text": text}}
    elif "dingtalk.com" in url or "weixin.qq.com" in url:
        payload = {"msgtype": "text", "text": {"content": text}}
    else:  # Slack / Discord / 自建服务
        payload = {"text": text, "content": text}

    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    LOG.info("已推送到 webhook (%s)", resp.status_code)


# ---------------------------------------------------------------- 主流程


def run_once(args: argparse.Namespace) -> int:
    include = _compile(DELIST_PATTERNS + list(args.keyword or []))
    exclude = _compile(EXCLUDE_PATTERNS + list(args.exclude or []))

    client = BinanceAnnouncements(
        lang=args.lang,
        timeout=args.timeout,
        retries=args.retries,
        proxy=args.proxy or os.environ.get("BINANCE_PROXY"),
    )

    hits = collect(client, args.catalog, args.pages, include, exclude)
    LOG.info("命中下架公告 %s 条", len(hits))

    state_path = Path(args.state).expanduser()
    state = load_state(state_path)
    seen: dict[str, Any] = state["seen"]

    new = hits if args.all else [a for a in hits if a.code not in seen]

    now = datetime.now(timezone.utc).isoformat()
    for a in hits:
        seen.setdefault(a.code, {"title": a.title, "first_seen": now})
    if not args.dry_run:
        state["last_run"] = now
        save_state(state_path, state)

    if not new:
        if args.json:
            print(json.dumps([], ensure_ascii=False))
        else:
            print(f"没有新的下架公告（历史累计 {len(seen)} 条）")
        return 0

    if args.json:
        print(json.dumps([a.to_dict() for a in new], ensure_ascii=False, indent=2))
    else:
        print(format_text(new))

    if args.out:
        out_path = Path(args.out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("a", encoding="utf-8") as fh:
            for a in new:
                fh.write(json.dumps(a.to_dict(), ensure_ascii=False) + "\n")

    webhook = args.webhook or os.environ.get("BINANCE_WEBHOOK_URL")
    if webhook and not args.dry_run:
        try:
            push_webhook(webhook, format_text(new))
        except Exception as exc:  # noqa: BLE001 - 推送失败不应让抓取结果丢失
            LOG.error("webhook 推送失败: %s", exc)

    return 0


def selftest(args: argparse.Namespace) -> int:
    proxy = args.proxy or os.environ.get("BINANCE_PROXY")
    proxies = {"http": proxy, "https": proxy} if proxy else None
    print(f"代理: {proxy or '未设置（走系统 http(s)_proxy 环境变量）'}\n")

    ok = False
    for host in API_HOSTS:
        # article/list/query 不带 catalogId 时返回分区及各分区文章，适合同时
        # 验证连通性和响应结构；catalog/list/query 缺 catalogId 会返回 400。
        url = f"{host}{ARTICLE_PATHS[0]}"
        try:
            resp = requests.get(
                url,
                params={"type": 1, "pageNo": 1, "pageSize": 1},
                headers=DEFAULT_HEADERS,
                proxies=proxies,
                timeout=args.timeout,
            )
            body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            catalogs = ((body.get("data") or {}).get("catalogs") or [])
            print(f"  ✅ {host}  HTTP {resp.status_code}  分区数 {len(catalogs)}")
            structure_ok = bool(catalogs)
            ok = ok or (resp.status_code == 200 and structure_ok)
        except Exception as exc:  # noqa: BLE001
            print(f"  ❌ {host}  {type(exc).__name__}: {exc}")

    if not ok:
        print(
            "\n公告接口不通。这个域名在部分网络下会被 TLS 重置，"
            "请让代理接管 binance.com，或用 --proxy http://127.0.0.1:7897 指定。"
        )
        return 1
    print("\n连通性正常。")
    return 0


def build_parser() -> argparse.ArgumentParser:
    default_state = Path(__file__).resolve().parent / "state" / "seen.json"
    p = argparse.ArgumentParser(
        description="抓取 Binance 公告并筛出下架通知",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="每天 09:00 跑一次:\n"
               "  0 9 * * * cd %s && /usr/bin/python3 binance_delisting_monitor.py "
               ">> monitor.log 2>&1" % Path(__file__).resolve().parent,
    )
    p.add_argument("--catalog", type=int, nargs="*", help="只扫描指定分区 ID（默认全部；161=Delisting）")
    p.add_argument("--pages", type=int, default=1, help="每个分区翻几页，每页 50 条（默认 1）")
    p.add_argument("--lang", default="en", help="公告语言，如 en / zh-CN（默认 en）")
    p.add_argument("--keyword", nargs="*", help="追加自定义命中正则")
    p.add_argument("--exclude", nargs="*", help="追加自定义排除正则")
    p.add_argument("--state", default=str(default_state), help="状态文件路径")
    p.add_argument("--out", help="把新命中的公告追加写入 JSONL 文件")
    p.add_argument("--webhook", help="飞书/钉钉/企微/Slack 机器人地址，也可用 BINANCE_WEBHOOK_URL")
    p.add_argument("--proxy", help="HTTP 代理，也可用 BINANCE_PROXY")
    p.add_argument("--timeout", type=float, default=20.0)
    p.add_argument("--retries", type=int, default=3)
    p.add_argument("--interval", type=int, help="常驻模式，每隔 N 秒抓一次（86400 = 每天）")
    p.add_argument("--all", action="store_true", help="忽略状态文件，输出全部命中项")
    p.add_argument("--dry-run", action="store_true", help="不写状态、不推送")
    p.add_argument("--json", action="store_true", help="JSON 输出")
    p.add_argument("--selftest", action="store_true", help="只检查接口连通性")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )

    if args.selftest:
        return selftest(args)

    if not args.interval:
        try:
            return run_once(args)
        except Exception as exc:  # noqa: BLE001
            LOG.error("抓取失败: %s", exc)
            return 1

    LOG.info("常驻模式，每 %s 秒抓一次", args.interval)
    while True:
        try:
            run_once(args)
        except KeyboardInterrupt:
            return 130
        except Exception as exc:  # noqa: BLE001 - 单次失败不能让守护进程退出
            LOG.error("本轮抓取失败: %s", exc)
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            return 130


if __name__ == "__main__":
    sys.exit(main())
