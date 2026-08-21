"""
Dynamic symbol universe: top-N Binance USDⓈ-M perpetual futures contracts
(linear, USDT-margined) by 24h quote volume.

ccxt's unified symbol for these is "BASE/USDT:USDT" (the ":USDT" suffix is the
settlement currency) — different from the plain "BASE/USDT" spot notation.
`to_perp_symbol` / `display_symbol` below convert between the exchange-ready
form and the human-friendly form used in config, logs, and LINE messages.

Refetching ex.fetch_tickers() (one request, but a heavy one — it returns every
symbol on the exchange) on every scan is wasteful and unnecessary: which coins
are "top by volume" does not meaningfully change minute to minute. Cache the
list to disk for `cache_ttl_hours` and only hit the network again once it goes
stale.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

log = logging.getLogger("qm-bot.universe")

_LEVERAGED_MARKERS = ("UP/", "DOWN/", "BULL/", "BEAR/")

# Stablecoin-to-stablecoin pairs dominate USDT volume rankings (arbitrage /
# market-making flow) but trade in a near-zero range, so they never form a
# real QM structure — they'd just occupy universe slots and burn API calls.
_STABLECOIN_BASES = {
    "USDC", "USD1", "RLUSD", "FDUSD", "TUSD", "DAI", "USDP", "EUR", "EURI",
    "BUSD", "USDD", "GUSD", "PYUSD", "USDE",
}


def to_perp_symbol(symbol: str) -> str:
    """'BTC/USDT' -> 'BTC/USDT:USDT'. Already-suffixed symbols pass through
    unchanged, so config's `always_include` can stay in friendly form."""
    return symbol if ":" in symbol else f"{symbol}:USDT"


def display_symbol(symbol: str) -> str:
    """'BTC/USDT:USDT' -> 'BTC/USDT' — for anything a human reads (LINE
    message, chart title, signals.db)."""
    return symbol.split(":")[0]


def _is_plain_linear_usdt_perp(symbol: str) -> bool:
    if not symbol.endswith("/USDT:USDT"):
        return False  # excludes spot, inverse (COIN-M, e.g. "BTC/USD:BTC"),
                       # and dated quarterly futures (different symbol shape)
    base = symbol.split("/")[0]
    if base in _STABLECOIN_BASES:
        return False
    return not any(marker.rstrip("/") in base for marker in _LEVERAGED_MARKERS)


def _is_crypto_perp(exchange, symbol: str) -> bool:
    """True only for an actual cryptocurrency perpetual.

    Binance's USDⓈ-M futures also lists TradFi products wrapped as
    perpetuals — tokenized gold/silver (XAU, XAG) and individual stocks
    (e.g. SNDK, SKHYNIX) — which can easily out-rank real altcoins by USDT
    volume. Binance-specific `info.contractType`/`underlyingType` fields are
    the only reliable way to tell them apart from a plain symbol string; a
    string-only filter would silently let gold back into a "crypto only"
    universe purely because it trades a lot.
    """
    if not _is_plain_linear_usdt_perp(symbol):
        return False
    market = exchange.markets.get(symbol)
    if not market:
        return False
    info = market.get("info", {})
    return info.get("contractType") == "PERPETUAL" and info.get("underlyingType") == "COIN"


def _fetch_fresh(exchange, n: int, always_include: list[str]) -> list[str]:
    exchange.load_markets()  # populate exchange.markets[...]['info'] for the contractType check
    tickers = exchange.fetch_tickers()
    ranked = [
        (sym, t.get("quoteVolume") or 0.0)
        for sym, t in tickers.items()
        if _is_crypto_perp(exchange, sym)
    ]
    ranked.sort(key=lambda pair: pair[1], reverse=True)
    top = [sym for sym, _ in ranked[:n]]

    ordered = [to_perp_symbol(sym) for sym in always_include]
    for sym in top:
        if sym not in ordered:
            ordered.append(sym)
    return ordered


def top_usdt_pairs(
    exchange,
    n: int = 20,
    always_include: list[str] | None = None,
    cache_path: str | Path = "universe_cache.json",
    cache_ttl_hours: float = 24,
) -> list[str]:
    """Return `always_include` + top-`n` Binance USDT-M perpetual futures
    contracts by 24h quote volume, as ccxt-ready 'BASE/USDT:USDT' symbols.

    Leveraged tokens (UP/DOWN/BULL/BEAR) are excluded — they are derivatives
    products whose price action does not represent the underlying coin's
    structure and would otherwise pollute the universe with noisy pseudo-QMs.
    Binance's TradFi-wrapped perpetuals (tokenized gold/silver, stocks) are
    excluded too — they aren't cryptocurrencies at all, see _is_crypto_perp.
    """
    always_include = always_include or []
    cache_path = Path(cache_path)

    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text())
            age_hours = (time.time() - cached["fetched_at"]) / 3600
            if age_hours < cache_ttl_hours and cached.get("n") == n:
                return cached["symbols"]
        except (json.JSONDecodeError, KeyError, OSError):
            pass  # corrupt or partial cache — fall through and refetch

    symbols = _fetch_fresh(exchange, n, always_include)
    cache_path.write_text(
        json.dumps({"fetched_at": time.time(), "n": n, "symbols": symbols})
    )
    log.info("universe refreshed: %d symbols (%s)", len(symbols), ", ".join(symbols[:5]) + ", ...")
    return symbols
