"""
prices.py
---------
Fetching the market price of a ticker at a given moment.

Two sources:

1. LIVE  -> real prices from Yahoo Finance, through the `yfinance` library.
            Needs an internet connection.

2. SIMULATED -> an offline, made-up market. Prices move smoothly over time
            (they change every minute, so short demo calls still work) and are
            always the same for the same ticker and moment.
            Used as a backup if Wi-Fi fails during the presentation,
            and to build the demo history. It is NOT real market data.

Every reveal stores which source was used, so the track record is transparent.
"""

import hashlib
import math
from datetime import datetime, timedelta, timezone


SOURCE_LIVE = "Yahoo Finance (live)"
SOURCE_SIMULATED = "Simulated market (offline demo)"


class PriceNotAvailable(Exception):
    """Raised when no price can be found for that ticker and moment."""


# ---------------------------------------------------------------------------
# Live prices (Yahoo Finance)
# ---------------------------------------------------------------------------

def _last_close_before(history, moment: datetime):
    """From a price table, take the last 'Close' at or before the given moment."""
    if history is None or history.empty:
        return None

    # Make sure the table's time index is in UTC so we can compare it with `moment`
    index = history.index
    if index.tz is None:
        index = index.tz_localize("UTC")
    else:
        index = index.tz_convert("UTC")

    closes_before = history["Close"][index <= moment]
    if closes_before.empty:
        return None
    return float(closes_before.iloc[-1])


def get_live_price(ticker: str, moment: datetime) -> float:
    """
    Price of `ticker` at `moment` (or the last trade before it, e.g. if the
    stock market was closed). Uses 1-minute candles for recent moments and
    daily candles for older ones.
    """
    try:
        import yfinance as yf
    except ImportError:
        raise PriceNotAvailable("The 'yfinance' package is not installed (pip install yfinance).")

    now = datetime.now(timezone.utc)
    if moment > now:
        raise PriceNotAvailable("This moment is in the future: the price doesn't exist yet.")

    stock = yf.Ticker(ticker)

    try:
        # Yahoo only keeps 1-minute candles for the last ~7 days
        if now - moment < timedelta(days=6):
            start = max(moment - timedelta(days=3), now - timedelta(days=6, hours=23))
            history = stock.history(start=start, end=moment + timedelta(minutes=1), interval="1m")
            price = _last_close_before(history, moment)
            if price is not None:
                return price

        # Older moments (or no minute data): use daily candles
        history = stock.history(start=moment - timedelta(days=7), end=moment + timedelta(days=1), interval="1d")
        price = _last_close_before(history, moment)
        if price is not None:
            return price

    except Exception as error:  # network problems, unknown ticker, Yahoo changes...
        raise PriceNotAvailable(f"Yahoo Finance error for {ticker}: {error}")

    raise PriceNotAvailable(
        f"No price found for {ticker} at that time. Check the ticker, "
        f"or wait a minute if the deadline has just passed (live data can be slightly delayed)."
    )


# ---------------------------------------------------------------------------
# Simulated prices (offline)
# ---------------------------------------------------------------------------

# Starting level and "personality" of a few well-known tickers.
# Other tickers get a starting price derived from their name.
SIMULATED_BASE_PRICES = {
    "BTC-USD": 90000.0,
    "ETH-USD": 3200.0,
    "SOL-USD": 140.0,
    "AAPL": 230.0,
    "TSLA": 330.0,
    "NVDA": 180.0,
    "ENI.MI": 15.0,
}


def _ticker_seed(ticker: str) -> int:
    """A stable number derived from the ticker name (same ticker -> same number)."""
    return int(hashlib.sha256(ticker.encode("utf-8")).hexdigest()[:8], 16)


def get_simulated_price(ticker: str, moment: datetime) -> float:
    """
    A fake but realistic-looking price path, built by adding a few waves:
    a slow trend over weeks, medium moves over days and small wiggles over minutes.
    """
    seed = _ticker_seed(ticker)
    base_price = SIMULATED_BASE_PRICES.get(ticker, 20 + seed % 480)

    # Time in hours since 1 Jan 2026
    origin = datetime(2026, 1, 1, tzinfo=timezone.utc)
    hours = (moment - origin).total_seconds() / 3600

    # Each ticker gets its own phase shifts so they don't all move together
    phase_1 = (seed % 1000) / 1000 * 2 * math.pi
    phase_2 = (seed % 777) / 777 * 2 * math.pi
    phase_3 = (seed % 555) / 555 * 2 * math.pi
    phase_4 = (seed % 333) / 333 * 2 * math.pi

    change = (
        0.12 * math.sin(hours / (24 * 23) + phase_1)        # slow trend (weeks)
        + 0.05 * math.sin(hours / (24 * 3.1) + phase_2)     # swings over a few days
        + 0.015 * math.sin(hours / 5.3 + phase_3)           # moves within the day
        + 0.004 * math.sin(hours * 60 / 3.7 + phase_4)      # small moves within minutes
    )

    return round(base_price * (1 + change), 2)


# ---------------------------------------------------------------------------
# One function used by the rest of the app
# ---------------------------------------------------------------------------

def get_price(ticker: str, moment: datetime, use_live_data: bool = True) -> tuple:
    """
    Return (price, source_name).
    In live mode, errors are raised (we never silently switch to fake prices
    for a real reveal: the user decides to switch to offline mode).
    """
    if use_live_data:
        return get_live_price(ticker, moment), SOURCE_LIVE
    return get_simulated_price(ticker, moment), SOURCE_SIMULATED
