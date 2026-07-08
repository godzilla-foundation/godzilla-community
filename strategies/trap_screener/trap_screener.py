#!/usr/bin/env python3
"""
trap_screener.py — 币安永续"妖币/费率陷阱"筛选器

针对资金费率套利前的风控过滤，识别低流通、高控盘、逼空风险高的标的。

核心指标：
  1. oi_mcap_ratio   : 合约名义持仓 / 流通市值      (>0.5 警惕, >1.0 高危)
  2. perp_spot_ratio : 合约24h成交 / 现货24h成交    (>15 警惕, >40 高危)
  3. funding_apr     : 当前资金费率年化(绝对值)      (>100% 警惕, >300% 高危)
  4. listing_days    : 合约上线天数                  (<180 警惕, <60 高危)
  5. mcap            : 流通市值                      (<1e8 警惕, <3e7 高危)

无需 API key，仅用币安公开接口 + CoinGecko 免费接口。
输出：终端表格 + CSV。

用法：
  pip install requests
  python trap_screener.py                 # 全市场扫描
  python trap_screener.py TRB TNSR        # 只查指定标的
  python trap_screener.py --min-score 3   # 只显示风险分>=3的
"""

import argparse
import csv
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import requests

FAPI = "https://fapi.binance.com"
SAPI = "https://api.binance.com"
CG = "https://api.coingecko.com/api/v3"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "trap-screener/1.0"})


def get(url: str, params: dict | None = None, retries: int = 3) -> dict | list:
    for i in range(retries):
        try:
            r = SESSION.get(url, params=params, timeout=10)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 5))
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if i == retries - 1:
                raise
            time.sleep(1.5 * (i + 1))
    return {}


# ---------------------------------------------------------------- 数据抓取

def fetch_perp_universe() -> dict[str, dict]:
    """所有 USDT 本位永续，含上线时间。返回 {symbol: info}"""
    info = get(f"{FAPI}/fapi/v1/exchangeInfo")
    out = {}
    for s in info["symbols"]:
        if (
            s.get("contractType") == "PERPETUAL"
            and s.get("quoteAsset") == "USDT"
            and s.get("status") == "TRADING"
        ):
            out[s["symbol"]] = {
                "base": s["baseAsset"],
                "onboard_ms": s.get("onboardDate", 0),
            }
    return out


def fetch_funding() -> dict[str, float]:
    """当前预测资金费率 {symbol: rate}"""
    data = get(f"{FAPI}/fapi/v1/premiumIndex")
    return {d["symbol"]: float(d["lastFundingRate"]) for d in data}


def fetch_perp_tickers() -> dict[str, dict]:
    """合约 24h 成交额与最新价"""
    data = get(f"{FAPI}/fapi/v1/ticker/24hr")
    return {
        d["symbol"]: {
            "quote_vol": float(d["quoteVolume"]),
            "last": float(d["lastPrice"]),
        }
        for d in data
    }


def fetch_spot_tickers() -> dict[str, float]:
    """现货 24h 成交额（USDT 计价对）"""
    data = get(f"{SAPI}/api/v3/ticker/24hr")
    return {
        d["symbol"]: float(d["quoteVolume"])
        for d in data
        if d["symbol"].endswith("USDT")
    }


def fetch_open_interest(symbol: str) -> float:
    """单个合约的持仓量（币本位数量）"""
    try:
        d = get(f"{FAPI}/fapi/v1/openInterest", {"symbol": symbol})
        return float(d["openInterest"])
    except Exception:
        return 0.0


def fetch_mcaps(bases: set[str]) -> dict[str, float]:
    """
    CoinGecko 流通市值。按 symbol 匹配（小写），同名取市值最大者，
    避免把大币误配成同名小币。免费接口分页拉市值前 ~2000 名。
    """
    mcap: dict[str, float] = {}
    wanted = {b.lower() for b in bases}
    for page in range(1, 9):  # 8页 x 250 = 前2000名
        try:
            data = get(
                f"{CG}/coins/markets",
                {
                    "vs_currency": "usd",
                    "order": "market_cap_desc",
                    "per_page": 250,
                    "page": page,
                    "sparkline": "false",
                },
            )
        except Exception:
            break
        if not data:
            break
        for c in data:
            sym = (c.get("symbol") or "").lower()
            if sym in wanted and c.get("market_cap"):
                # 同 symbol 冲突时保留市值更大的（先出现的排名更高）
                mcap.setdefault(sym, float(c["market_cap"]))
        time.sleep(1.2)  # 免费接口限速
    return mcap


# ---------------------------------------------------------------- 打分

@dataclass
class Row:
    symbol: str
    base: str
    mcap: float = 0.0
    oi_notional: float = 0.0
    oi_mcap_ratio: float = 0.0
    perp_vol: float = 0.0
    spot_vol: float = 0.0
    perp_spot_ratio: float = 0.0
    funding: float = 0.0
    funding_apr: float = 0.0
    listing_days: int = 0
    score: int = 0
    flags: list[str] = field(default_factory=list)


def score_row(r: Row) -> None:
    def add(cond_hi, cond_mid, name):
        if cond_hi:
            r.score += 2
            r.flags.append(f"{name}!!")
        elif cond_mid:
            r.score += 1
            r.flags.append(name)

    add(r.oi_mcap_ratio > 1.0, r.oi_mcap_ratio > 0.5, "OI/MCAP")
    add(r.perp_spot_ratio > 40, r.perp_spot_ratio > 15, "期现比")
    add(abs(r.funding_apr) > 3.0, abs(r.funding_apr) > 1.0, "极端费率")
    add(0 < r.listing_days < 60, 60 <= r.listing_days < 180, "新上线")
    add(0 < r.mcap < 3e7, 3e7 <= r.mcap < 1e8, "微市值")
    # 市值缺失本身就是信号：太小/太新，CG前2000名都排不进
    if r.mcap == 0:
        r.score += 1
        r.flags.append("无市值数据")


# ---------------------------------------------------------------- 主流程

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="*", help="只查指定 base，如 TRB TNSR")
    ap.add_argument("--min-score", type=int, default=2)
    ap.add_argument("--out", default="trap_screen_result.csv")
    ap.add_argument("--top", type=int, default=50)
    args = ap.parse_args()

    print("拉取合约列表...", file=sys.stderr)
    universe = fetch_perp_universe()
    if args.symbols:
        keep = {s.upper() for s in args.symbols}
        universe = {k: v for k, v in universe.items() if v["base"] in keep}
    if not universe:
        sys.exit("没有匹配的合约")

    print(f"共 {len(universe)} 个永续，拉取行情...", file=sys.stderr)
    funding = fetch_funding()
    perp_t = fetch_perp_tickers()
    spot_t = fetch_spot_tickers()

    print("拉取流通市值 (CoinGecko)...", file=sys.stderr)
    mcaps = fetch_mcaps({v["base"] for v in universe.values()})

    print("拉取持仓量...", file=sys.stderr)
    oi: dict[str, float] = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(fetch_open_interest, s): s for s in universe}
        for f in as_completed(futs):
            oi[futs[f]] = f.result()

    now_ms = time.time() * 1000
    rows: list[Row] = []
    for sym, meta in universe.items():
        base = meta["base"]
        # 币安合约符号里 1000PEPE 这类前缀要还原
        cg_base = base[4:] if base.startswith("1000") else base
        pt = perp_t.get(sym, {})
        last = pt.get("last", 0.0)
        r = Row(symbol=sym, base=base)
        r.mcap = mcaps.get(cg_base.lower(), 0.0)
        r.oi_notional = oi.get(sym, 0.0) * last
        r.perp_vol = pt.get("quote_vol", 0.0)
        r.spot_vol = spot_t.get(f"{base}USDT", 0.0)
        r.funding = funding.get(sym, 0.0)
        r.funding_apr = r.funding * 3 * 365  # 8小时费率年化
        if meta["onboard_ms"]:
            r.listing_days = int((now_ms - meta["onboard_ms"]) / 86400000)
        if r.mcap > 0:
            r.oi_mcap_ratio = r.oi_notional / r.mcap
        if r.spot_vol > 0:
            r.perp_spot_ratio = r.perp_vol / r.spot_vol
        elif r.perp_vol > 0:
            r.perp_spot_ratio = float("inf")  # 币安无现货，合约孤儿盘
        score_row(r)
        rows.append(r)

    rows.sort(key=lambda x: (-x.score, -abs(x.funding_apr)))
    shown = [r for r in rows if r.score >= args.min_score][: args.top]

    hdr = f"{'合约':<16}{'风险':>4}{'市值($M)':>10}{'OI/MCAP':>9}{'期现比':>8}{'费率APR':>9}{'上线(天)':>9}  标记"
    print("\n" + hdr)
    print("-" * len(hdr))
    for r in shown:
        psr = "∞" if r.perp_spot_ratio == float("inf") else f"{r.perp_spot_ratio:.1f}"
        print(
            f"{r.symbol:<16}{r.score:>4}"
            f"{r.mcap/1e6:>10.1f}{r.oi_mcap_ratio:>9.2f}{psr:>8}"
            f"{r.funding_apr*100:>8.0f}%{r.listing_days:>9}  {','.join(r.flags)}"
        )

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            ["symbol", "score", "mcap_usd", "oi_notional_usd", "oi_mcap_ratio",
             "perp_vol_24h", "spot_vol_24h", "perp_spot_ratio",
             "funding_rate", "funding_apr", "listing_days", "flags"]
        )
        for r in rows:
            w.writerow(
                [r.symbol, r.score, f"{r.mcap:.0f}", f"{r.oi_notional:.0f}",
                 f"{r.oi_mcap_ratio:.4f}", f"{r.perp_vol:.0f}", f"{r.spot_vol:.0f}",
                 "" if r.perp_spot_ratio == float("inf") else f"{r.perp_spot_ratio:.2f}",
                 f"{r.funding:.6f}", f"{r.funding_apr:.4f}",
                 r.listing_days, "|".join(r.flags)]
            )
    print(f"\n全量结果已写入 {args.out}（共 {len(rows)} 个合约）", file=sys.stderr)


if __name__ == "__main__":
    main()
