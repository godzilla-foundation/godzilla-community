#!/usr/bin/env python3
"""
trap_screener.py — squeeze-trap screener for Binance USDT perpetuals

Pre-trade risk filter for funding rate arbitrage: flags low-float,
concentrated-ownership, squeeze-prone contracts before you put on the carry.

Signals:
  1. oi_mcap_ratio   : open interest notional / circulating mcap  (>0.5 warn, >1.0 danger)
  2. perp_spot_ratio : perp 24h volume / spot 24h volume           (>15 warn, >40 danger)
  3. funding_apr     : current funding rate, annualized (abs)      (>100% warn, >300% danger)
  4. listing_days    : days since the perp was listed              (<180 warn, <60 danger)
  5. mcap            : circulating market cap                      (<$100M warn, <$30M danger)

No API keys required — Binance public endpoints + CoinGecko free tier only.
Output: terminal table + CSV.

Usage:
  pip install requests
  python trap_screener.py                 # scan the full universe
  python trap_screener.py TRB TNSR        # only the given base assets
  python trap_screener.py --min-score 3   # only show risk score >= 3
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


# ---------------------------------------------------------------- data fetching

def fetch_perp_universe() -> dict[str, dict]:
    """All USDT-margined perpetuals, with listing time. Returns {symbol: info}."""
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
    """Current funding rate per symbol: {symbol: rate}."""
    data = get(f"{FAPI}/fapi/v1/premiumIndex")
    return {d["symbol"]: float(d["lastFundingRate"]) for d in data}


def fetch_perp_tickers() -> dict[str, dict]:
    """Perp 24h quote volume and last price."""
    data = get(f"{FAPI}/fapi/v1/ticker/24hr")
    return {
        d["symbol"]: {
            "quote_vol": float(d["quoteVolume"]),
            "last": float(d["lastPrice"]),
        }
        for d in data
    }


def fetch_spot_tickers() -> dict[str, float]:
    """Spot 24h quote volume (USDT-quoted pairs only)."""
    data = get(f"{SAPI}/api/v3/ticker/24hr")
    return {
        d["symbol"]: float(d["quoteVolume"])
        for d in data
        if d["symbol"].endswith("USDT")
    }


def fetch_open_interest(symbol: str) -> float:
    """Open interest for a single contract (in base-asset units)."""
    try:
        d = get(f"{FAPI}/fapi/v1/openInterest", {"symbol": symbol})
        return float(d["openInterest"])
    except Exception:
        return 0.0


def fetch_mcaps(bases: set[str]) -> dict[str, float]:
    """
    Circulating market caps from CoinGecko, matched by (lowercased) ticker
    symbol. On symbol collisions, keep the highest-mcap match to avoid
    attributing a large cap to a same-ticker impostor. Free tier, paginated
    over roughly the top 2000 coins by market cap.
    """
    mcap: dict[str, float] = {}
    wanted = {b.lower() for b in bases}
    for page in range(1, 9):  # 8 pages x 250 = top ~2000
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
                # on symbol collision, keep the highest-mcap match
                # (results are mcap-descending, so first seen wins)
                mcap.setdefault(sym, float(c["market_cap"]))
        time.sleep(1.2)  # free-tier rate limit
    return mcap


# ---------------------------------------------------------------- scoring

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
    add(r.perp_spot_ratio > 40, r.perp_spot_ratio > 15, "PERP/SPOT")
    add(abs(r.funding_apr) > 3.0, abs(r.funding_apr) > 1.0, "EXTREME_FUNDING")
    add(0 < r.listing_days < 60, 60 <= r.listing_days < 180, "NEW_LISTING")
    add(0 < r.mcap < 3e7, 3e7 <= r.mcap < 1e8, "MICRO_CAP")
    # Missing mcap is itself a signal: too small/new to rank in CG's top ~2000
    if r.mcap == 0:
        r.score += 1
        r.flags.append("NO_MCAP_DATA")


# ---------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="*", help="only screen these base assets, e.g. TRB TNSR")
    ap.add_argument("--min-score", type=int, default=2)
    ap.add_argument("--out", default="trap_screen_result.csv")
    ap.add_argument("--top", type=int, default=50)
    args = ap.parse_args()

    print("Fetching contract list...", file=sys.stderr)
    universe = fetch_perp_universe()
    if args.symbols:
        keep = {s.upper() for s in args.symbols}
        universe = {k: v for k, v in universe.items() if v["base"] in keep}
    if not universe:
        sys.exit("No matching contracts")

    print(f"{len(universe)} perpetuals, fetching tickers...", file=sys.stderr)
    funding = fetch_funding()
    perp_t = fetch_perp_tickers()
    spot_t = fetch_spot_tickers()

    print("Fetching market caps (CoinGecko)...", file=sys.stderr)
    mcaps = fetch_mcaps({v["base"] for v in universe.values()})

    print("Fetching open interest...", file=sys.stderr)
    oi: dict[str, float] = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(fetch_open_interest, s): s for s in universe}
        for f in as_completed(futs):
            oi[futs[f]] = f.result()

    now_ms = time.time() * 1000
    rows: list[Row] = []
    for sym, meta in universe.items():
        base = meta["base"]
        # Binance lists some contracts as 1000PEPE etc. — strip the prefix
        # before the market cap lookup
        cg_base = base[4:] if base.startswith("1000") else base
        pt = perp_t.get(sym, {})
        last = pt.get("last", 0.0)
        r = Row(symbol=sym, base=base)
        r.mcap = mcaps.get(cg_base.lower(), 0.0)
        r.oi_notional = oi.get(sym, 0.0) * last
        r.perp_vol = pt.get("quote_vol", 0.0)
        r.spot_vol = spot_t.get(f"{base}USDT", 0.0)
        r.funding = funding.get(sym, 0.0)
        r.funding_apr = r.funding * 3 * 365  # 8h funding, annualized
        if meta["onboard_ms"]:
            r.listing_days = int((now_ms - meta["onboard_ms"]) / 86400000)
        if r.mcap > 0:
            r.oi_mcap_ratio = r.oi_notional / r.mcap
        if r.spot_vol > 0:
            r.perp_spot_ratio = r.perp_vol / r.spot_vol
        elif r.perp_vol > 0:
            r.perp_spot_ratio = float("inf")  # perp exists, no Binance spot pair
        score_row(r)
        rows.append(r)

    rows.sort(key=lambda x: (-x.score, -abs(x.funding_apr)))
    shown = [r for r in rows if r.score >= args.min_score][: args.top]

    hdr = f"{'CONTRACT':<16}{'RISK':>5}{'MCAP($M)':>10}{'OI/MCAP':>9}{'P/S':>7}{'FUND APR':>10}{'AGE(d)':>8}  FLAGS"
    print("\n" + hdr)
    print("-" * len(hdr))
    for r in shown:
        psr = "inf" if r.perp_spot_ratio == float("inf") else f"{r.perp_spot_ratio:.1f}"
        print(
            f"{r.symbol:<16}{r.score:>5}"
            f"{r.mcap/1e6:>10.1f}{r.oi_mcap_ratio:>9.2f}{psr:>7}"
            f"{r.funding_apr*100:>9.0f}%{r.listing_days:>8}  {','.join(r.flags)}"
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
    print(f"\nFull results written to {args.out} ({len(rows)} contracts)", file=sys.stderr)


if __name__ == "__main__":
    main()