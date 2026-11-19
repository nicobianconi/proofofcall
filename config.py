"""
config.py
---------
All the settings of ProofOfCall in one place.

Change the values here (not inside the other files) if you want to adjust
the rules of the app, for example how long an influencer has to reveal a call.
"""

from pathlib import Path


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

# Folder where this file lives (so the app works no matter where you launch it from)
BASE_DIR = Path(__file__).resolve().parent

# The ledger: an append-only list of blocks, saved as JSON
LEDGER_FILE = BASE_DIR / "ledger.json"

# A copy of the demo ledger, used by the "Reset demo data" button
SEED_LEDGER_FILE = BASE_DIR / "seed_ledger.json"


# ---------------------------------------------------------------------------
# Rules of the commit-reveal game
# ---------------------------------------------------------------------------

# After the deadline, the influencer has this many minutes to reveal the call.
# If they don't reveal in time, the call is marked EXPIRED and counts as WRONG.
# (Short value for the live class demo. A real product would use e.g. 24 hours.)
REVEAL_WINDOW_MINUTES = 15

# The deadline must be at least this many minutes after the commit
MIN_MINUTES_UNTIL_DEADLINE = 1

# Directions an influencer can predict
DIRECTIONS = ["UP", "DOWN"]

# Local time zone used to show dates in the app (everything is stored in UTC)
DISPLAY_TIMEZONE = "Europe/Rome"


# ---------------------------------------------------------------------------
# Business model (simulated: no real payment happens in the demo)
# ---------------------------------------------------------------------------

VERIFIED_PRICE_EUR_PER_MONTH = 9.99
VERIFIED_PLAN_DAYS = 30

# Minimum number of resolved calls before a hit rate is shown as meaningful
MIN_CALLS_FOR_RANKING = 3


# ---------------------------------------------------------------------------
# Tickers suggested in the app (any Yahoo Finance ticker works in live mode)
# ---------------------------------------------------------------------------

SUGGESTED_TICKERS = [
    "BTC-USD",   # Bitcoin   - trades 24/7, best for the live demo
    "ETH-USD",   # Ethereum  - trades 24/7
    "SOL-USD",   # Solana    - trades 24/7
    "AAPL",      # Apple
    "TSLA",      # Tesla
    "NVDA",      # Nvidia
    "ENI.MI",    # Eni (Borsa Italiana)
]
