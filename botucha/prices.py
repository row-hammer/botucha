"""Live market prices from Yahoo Finance's chart endpoint (no key). Only the ticker leaves the PC."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

import httpx

from .trigger import fold

log = logging.getLogger(__name__)

YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
MAX_SYMBOLS = 3

# Lowercase, diacritic-free stems. Stems of 4+ chars match word prefixes (nvidijos -> nvidi),
# shorter ones only whole words (eth does not match ethernet).
DEFAULT_ALIASES: dict[str, str] = {
    "spx": "^GSPC", "sp500": "^GSPC", "nasdaq": "^NDX", "ndx": "^NDX",
    "vwce": "VWCE.DE", "nvda": "NVDA", "nvidi": "NVDA", "coreweav": "CRWV", "crwv": "CRWV",
    "broadcom": "AVGO", "avgo": "AVGO", "btc": "BTC-USD", "bitcoin": "BTC-USD", "bitkoin": "BTC-USD",
    "eth": "ETH-USD", "ethereum": "ETH-USD", "eurusd": "EURUSD=X",
}

_TOKEN = re.compile(r"\$[A-Za-z][A-Za-z0-9.\-]{0,9}|\w+")


@dataclass
class Quote:
    symbol: str
    name: str
    price: float
    currency: str
    change_pct: float | None
    ts: float


def parse_chart(data: object) -> Quote | None:
    try:
        meta = data["chart"]["result"][0]["meta"]  # type: ignore[index]
        price = float(meta["regularMarketPrice"])
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        change = (price / float(prev) - 1) * 100 if prev else None
        return Quote(str(meta["symbol"]), str(meta.get("shortName") or meta["symbol"]), price,
                     str(meta.get("currency") or ""), change, float(meta.get("regularMarketTime") or 0))
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def format_quote(q: Quote) -> str:
    text = f"{q.symbol} {q.price:.2f} {q.currency}".strip()
    if q.change_pct is not None:
        sign = "−" if q.change_pct < 0 else "+"
        text += f" ({sign}{abs(q.change_pct):.1f} % šiandien)"
    return text


def detect_symbols(text: str, aliases: Mapping[str, str], limit: int = MAX_SYMBOLS) -> list[str]:
    found: list[str] = []
    for tok in _TOKEN.findall(text):
        if tok.startswith("$"):
            sym = tok[1:].upper()
        else:
            w = fold(tok)
            sym = next((s for k, s in aliases.items() if (w.startswith(k) if len(k) >= 4 else w == k)), None)
        if sym and sym not in found:
            found.append(sym)
            if len(found) >= limit:
                break
    return found


async def yahoo_fetch(symbol: str) -> dict | None:
    async with httpx.AsyncClient(timeout=5, headers={"User-Agent": "Mozilla/5.0"}) as client:
        r = await client.get(YAHOO_URL.format(symbol=symbol), params={"range": "1d", "interval": "1d"})
        return r.json() if r.status_code == 200 else None


class PriceClient:
    def __init__(self, fetch: Callable[[str], Awaitable[object]] = yahoo_fetch, *,
                 clock: Callable[[], float] = time.time, ttl_s: float = 300, fail_ttl_s: float = 60,
                 timeout_s: float = 5):
        self.fetch, self.clock = fetch, clock
        self.ttl_s, self.fail_ttl_s, self.timeout_s = ttl_s, fail_ttl_s, timeout_s
        self._cache: dict[str, tuple[float, Quote | None]] = {}

    async def quote(self, symbol: str) -> Quote | None:
        now = self.clock()
        hit = self._cache.get(symbol)
        if hit and now - hit[0] < (self.ttl_s if hit[1] else self.fail_ttl_s):
            return hit[1]
        try:
            q = parse_chart(await asyncio.wait_for(self.fetch(symbol), self.timeout_s))
        except Exception as e:  # network, timeout, bad JSON
            log.warning("price fetch failed for %s: %s", symbol, e)
            q = None
        self._cache[symbol] = (now, q)
        return q

    async def quotes(self, symbols: list[str]) -> list[Quote]:
        results = await asyncio.gather(*(self.quote(s) for s in symbols))
        return [q for q in results if q]
