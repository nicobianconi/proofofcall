"""
commitments.py
--------------
The cryptography of ProofOfCall: the commit-reveal scheme.

How it works
1. COMMIT: before posting a tip, the influencer computes

       sha256(handle|ticker|direction|target|deadline|nonce)

   and publishes ONLY this hash on the ledger. Nobody can tell from the hash
   which stock they picked or what they predicted.

2. REVEAL: after the deadline, the influencer publishes the original values.
   Anyone can recompute the hash and check that it is identical to the one
   committed earlier. If even one character is different, the hash changes
   completely, so the prediction cannot be edited after the fact.

The "nonce" is a long random secret. Without it, someone could guess the
prediction by trying all common tickers and directions (a brute-force attack).
"""

import hashlib
import json
import secrets
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Small helpers to always write values in exactly the same way.
# This matters: "100" and "100.00" would give two different hashes.
# ---------------------------------------------------------------------------

def normalize_handle(handle: str) -> str:
    """'  Vera ' -> '@vera'"""
    handle = handle.strip().lower()
    if not handle.startswith("@"):
        handle = "@" + handle
    return handle


def normalize_ticker(ticker: str) -> str:
    """' btc-usd ' -> 'BTC-USD'"""
    return ticker.strip().upper()


def format_target(target: float) -> str:
    """Always 2 decimals: 105 -> '105.00'"""
    return f"{float(target):.2f}"


def format_deadline(deadline: datetime) -> str:
    """Datetime -> ISO string in UTC, without microseconds: '2026-11-23T15:30:00Z'"""
    deadline_utc = deadline.astimezone(timezone.utc).replace(microsecond=0)
    return deadline_utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_deadline(text: str) -> datetime:
    """ISO string '2026-11-23T15:30:00Z' -> timezone-aware datetime (UTC)"""
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# The commitment itself
# ---------------------------------------------------------------------------

def generate_nonce() -> str:
    """A random 32-character secret (128 bits of randomness)."""
    return secrets.token_hex(16)


def build_message(handle, ticker, direction, target, deadline_iso, nonce) -> str:
    """The exact text that gets hashed, with fields separated by '|'."""
    return "|".join([
        normalize_handle(handle),
        normalize_ticker(ticker),
        direction.upper(),
        format_target(target),
        deadline_iso,
        nonce,
    ])


def compute_commitment(handle, ticker, direction, target, deadline_iso, nonce) -> str:
    """Return the SHA-256 hash (64 hexadecimal characters) of the prediction."""
    message = build_message(handle, ticker, direction, target, deadline_iso, nonce)
    return hashlib.sha256(message.encode("utf-8")).hexdigest()


def short_code(commit_hash: str) -> str:
    """
    The first 8 characters of the hash.
    This is the code the influencer puts in the social post (e.g. "#PoC-1a2b3c4d")
    so followers can find the commit on the ledger.
    """
    return commit_hash[:8]


# ---------------------------------------------------------------------------
# The receipt: what the influencer must keep secret until the reveal
# ---------------------------------------------------------------------------

def make_receipt(handle, ticker, direction, target, deadline_iso, nonce, commit_hash) -> str:
    """Return the receipt as nicely formatted JSON text."""
    receipt = {
        "app": "ProofOfCall",
        "commit_code": short_code(commit_hash),
        "handle": normalize_handle(handle),
        "ticker": normalize_ticker(ticker),
        "direction": direction.upper(),
        "target": format_target(target),
        "deadline": deadline_iso,
        "nonce": nonce,
    }
    return json.dumps(receipt, indent=2)


def read_receipt(receipt_text: str) -> dict:
    """
    Parse a receipt pasted by the user.
    Raises ValueError with a clear message if something is missing.
    """
    try:
        receipt = json.loads(receipt_text)
    except json.JSONDecodeError:
        raise ValueError("The receipt is not valid JSON. Paste it exactly as you saved it.")

    required_fields = ["commit_code", "handle", "ticker", "direction", "target", "deadline", "nonce"]
    missing = [field for field in required_fields if field not in receipt]
    if missing:
        raise ValueError("The receipt is missing these fields: " + ", ".join(missing))

    return receipt
