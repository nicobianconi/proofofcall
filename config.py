"""
config.py
---------
All the settings of ProofOfCall in one place.

Change the values here (not inside the other files) if you want to adjust
the rules of the app.
"""

from pathlib import Path


# ---------------------------------------------------------------------------
# Name and branding
# ---------------------------------------------------------------------------

APP_NAME = "ProofOfCall"
APP_TAGLINE = "Verified track records for finfluencers"

# Prefix of the short code the influencer puts in the social post, e.g. "#PoC-1a2b3c4d"
CODE_PREFIX = "#PoC-"

DISCLAIMER = ("ProofOfCall records and scores predictions. "
              "It is not investment advice and does not recommend any trade.")


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

# Folder where this file lives (so the app works no matter where you launch it from)
BASE_DIR = Path(__file__).resolve().parent

# The ledger: an append-only table of blocks in a SQLite database
LEDGER_DB = BASE_DIR / "ledger.db"

# The demo history (readable JSON), loaded into the database on the first launch
# and by the "Reset demo data" button
SEED_LEDGER_FILE = BASE_DIR / "seed_ledger.json"


# ---------------------------------------------------------------------------
# Admin password (protects the "Demo tools" in the sidebar)
# ---------------------------------------------------------------------------
# The password is NOT written in the code (the GitHub repository is public).
# It is read from Streamlit secrets:
#   - on Streamlit Cloud: App settings -> Secrets -> ADMIN_PASSWORD = "..."
#   - on your computer:   file .streamlit/secrets.toml -> ADMIN_PASSWORD = "..."
ADMIN_PASSWORD_SECRET_NAME = "ADMIN_PASSWORD"


# ---------------------------------------------------------------------------
# The two kinds of calls
# ---------------------------------------------------------------------------
# STANDARD: the real product rule from the PRD.
#   - the call settles at the CLOSE of the deadline day
#     (we take the last price before 22:00 Italian time, i.e. after the US close)
#   - the target must be at least 2% away from the price at commit time
#   - 24 hours to reveal after the close
#
# LIVE DEMO: same logic, shrunk to minutes so it can be shown in class.
#   - the call settles at the exact deadline minute
#   - the target must be at least 0.1% away (crypto moves ~0.1-0.5% in 10 minutes)
#   - 15 minutes to reveal

CALL_TYPES = {
    "standard": {
        "label": "Standard (close of a trading day)",
        "min_target_distance": 0.02,      # 2%
        "reveal_window_minutes": 24 * 60,  # 24 hours
    },
    "demo": {
        "label": "Live demo (deadline in minutes)",
        "min_target_distance": 0.001,     # 0.1%
        "reveal_window_minutes": 15,
    },
}

# Standard calls settle at this local time on the deadline day (after the US market close)
DAILY_CLOSE_TIME = "22:00"

# Live demo calls: the deadline must be at least this many minutes in the future
MIN_MINUTES_UNTIL_DEADLINE = 1

# Directions an influencer can predict
DIRECTIONS = ["UP", "DOWN"]

# Local time zone used for the daily close and to show dates (everything is stored in UTC)
DISPLAY_TIMEZONE = "Europe/Rome"


# ---------------------------------------------------------------------------
# Track record
# ---------------------------------------------------------------------------

# A hit rate is shown publicly only after this many resolved calls
MIN_CALLS_FOR_HIT_RATE = 20

# Confidence level of the interval shown next to the hit rate
CONFIDENCE_Z = 1.96   # 95%


# ---------------------------------------------------------------------------
# Business model (simulated: no real payment happens in the demo)
# ---------------------------------------------------------------------------

VERIFIED_PLANS = {
    "Pro": 9.00,    # EUR per month
    "Plus": 29.00,  # EUR per month
}
VERIFIED_PLAN_DAYS = 30


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
