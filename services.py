"""
services.py
-----------
The business logic of ProofOfCall: everything the app can DO.

    register_influencer()      create a profile
    create_commit()            commit a hidden prediction
    reveal_commit()            reveal it after the deadline and score it
    expire_overdue_commits()   anti-cheating rule: unrevealed calls become WRONG
    subscribe_verified()       buy the "Verified" badge (simulated payment)
    compute_leaderboard()      hit rates of every influencer

The Streamlit pages (app.py) only call these functions, so the logic can be
tested without opening the app.

Every function accepts an optional `now` argument. In the app it is left empty
(= the real current time). The demo-data script uses it to create calls "in the past".
"""

from datetime import datetime, timedelta, timezone

import pandas as pd

import commitments
import config
import ledger
import prices


# Possible states of a call
STATUS_PENDING = "Pending"                  # deadline not reached yet
STATUS_AWAITING = "Awaiting reveal"         # deadline passed, reveal window open
STATUS_CORRECT = "Correct"
STATUS_WRONG = "Wrong"
STATUS_EXPIRED = "Expired (counts as wrong)"


class ProofOfCallError(Exception):
    """An error with a message that can be shown directly to the user."""


def _now(now=None) -> datetime:
    return now or datetime.now(timezone.utc)


# ===========================================================================
# Reading the ledger
# ===========================================================================

def get_influencers(chain: list) -> dict:
    """Return {handle: profile} from the REGISTER blocks."""
    influencers = {}
    for block in chain:
        if block["type"] == "REGISTER":
            profile = dict(block["data"])
            profile["registered_at"] = block["timestamp"]
            influencers[profile["handle"]] = profile
    return influencers


def get_calls(chain: list, now=None) -> list:
    """
    Combine COMMIT, REVEAL and EXPIRE blocks into one list of calls,
    each with its current status. Newest calls first.
    """
    now = _now(now)
    calls = {}

    for block in chain:
        data = block["data"]

        if block["type"] == "COMMIT":
            calls[data["commit_hash"]] = {
                "code": data["commit_code"],
                "commit_hash": data["commit_hash"],
                "handle": data["handle"],
                "committed_at": block["timestamp"],
                "deadline": data["deadline"],
                "reveal_until": data["reveal_until"],
                "commit_block": block["index"],
                # Hidden until the reveal:
                "ticker": None,
                "direction": None,
                "target": None,
                "price_at_commit": None,
                "price_at_deadline": None,
                "price_source": None,
                "status": None,
            }

        elif block["type"] == "REVEAL" and data["commit_hash"] in calls:
            call = calls[data["commit_hash"]]
            call.update({
                "ticker": data["ticker"],
                "direction": data["direction"],
                "target": data["target"],
                "price_at_commit": data["price_at_commit"],
                "price_at_deadline": data["price_at_deadline"],
                "price_source": data["price_source"],
                "status": STATUS_CORRECT if data["correct"] else STATUS_WRONG,
            })

        elif block["type"] == "EXPIRE" and data["commit_hash"] in calls:
            calls[data["commit_hash"]]["status"] = STATUS_EXPIRED

    # Calls still without a final status: pending or awaiting reveal
    for call in calls.values():
        if call["status"] is None:
            deadline = commitments.parse_deadline(call["deadline"])
            call["status"] = STATUS_PENDING if now < deadline else STATUS_AWAITING

    return sorted(calls.values(), key=lambda call: call["committed_at"], reverse=True)


def find_call(chain: list, code: str, now=None) -> dict:
    """Find a call by its 8-character code (or full hash)."""
    code = code.strip().lower().replace("#poc-", "")
    for call in get_calls(chain, now):
        if call["code"] == code or call["commit_hash"] == code:
            return call
    raise ProofOfCallError(f"No call found with code '{code}'.")


def is_verified(chain: list, handle: str, now=None) -> bool:
    """True if the influencer has an active 'Verified' subscription."""
    now = _now(now)
    for block in reversed(chain):
        if block["type"] == "VERIFY" and block["data"]["handle"] == handle:
            valid_until = commitments.parse_deadline(block["data"]["valid_until"])
            return now <= valid_until
    return False


# ===========================================================================
# Actions (each one adds a block to the ledger)
# ===========================================================================

def register_influencer(handle: str, display_name: str, platform: str, now=None) -> dict:
    handle = commitments.normalize_handle(handle)

    if len(handle) < 3:
        raise ProofOfCallError("The handle must have at least 2 characters after the @.")

    if handle in get_influencers(ledger.load_chain()):
        raise ProofOfCallError(f"{handle} is already registered.")

    return ledger.append_block(
        "REGISTER",
        {"handle": handle, "display_name": display_name.strip() or handle, "platform": platform},
        moment=_now(now),
    )


def create_commit(handle, ticker, direction, target, deadline: datetime, now=None) -> dict:
    """
    Commit a hidden prediction.
    Returns a dict with the block, the full hash, the short code and the secret receipt.
    """
    now = _now(now)
    handle = commitments.normalize_handle(handle)
    ticker = commitments.normalize_ticker(ticker)

    # --- Checks ------------------------------------------------------------
    if handle not in get_influencers(ledger.load_chain()):
        raise ProofOfCallError(f"{handle} is not registered. Create a profile first.")
    if not ticker:
        raise ProofOfCallError("Please enter a ticker.")
    if direction not in config.DIRECTIONS:
        raise ProofOfCallError("Direction must be UP or DOWN.")
    if target is None or float(target) <= 0:
        raise ProofOfCallError("The target price must be greater than 0.")
    if deadline < now + timedelta(minutes=config.MIN_MINUTES_UNTIL_DEADLINE):
        raise ProofOfCallError(
            f"The deadline must be at least {config.MIN_MINUTES_UNTIL_DEADLINE} minute(s) in the future."
        )

    # --- Build the commitment ---------------------------------------------
    deadline_iso = commitments.format_deadline(deadline)
    reveal_until = deadline.replace(microsecond=0) + timedelta(minutes=config.REVEAL_WINDOW_MINUTES)
    nonce = commitments.generate_nonce()
    commit_hash = commitments.compute_commitment(handle, ticker, direction, target, deadline_iso, nonce)

    # Only PUBLIC information goes on the ledger: who, when, the hash and the deadline.
    # Ticker, direction, target and nonce stay secret in the receipt.
    block = ledger.append_block(
        "COMMIT",
        {
            "handle": handle,
            "commit_hash": commit_hash,
            "commit_code": commitments.short_code(commit_hash),
            "deadline": deadline_iso,
            "reveal_until": commitments.format_deadline(reveal_until),
        },
        moment=now,
    )

    receipt = commitments.make_receipt(handle, ticker, direction, target, deadline_iso, nonce, commit_hash)

    return {
        "block": block,
        "commit_hash": commit_hash,
        "code": commitments.short_code(commit_hash),
        "receipt": receipt,
    }


def evaluate_call(direction: str, target: float, price_at_deadline: float) -> bool:
    """
    The scoring rule:
        UP   is correct if the price at the deadline is AT or ABOVE the target
        DOWN is correct if the price at the deadline is AT or BELOW the target
    """
    if direction == "UP":
        return price_at_deadline >= float(target)
    return price_at_deadline <= float(target)


def reveal_commit(code, ticker, direction, target, nonce, use_live_data=True, now=None) -> dict:
    """
    Reveal a call: check the hash, fetch the real price at the deadline,
    decide if the call was correct and write the result on the ledger.
    """
    now = _now(now)
    chain = ledger.load_chain()
    call = find_call(chain, code, now)

    # --- Is this call in a state that can be revealed? --------------------
    if call["status"] in (STATUS_CORRECT, STATUS_WRONG):
        raise ProofOfCallError("This call has already been revealed.")
    if call["status"] == STATUS_EXPIRED:
        raise ProofOfCallError("Too late: this call expired and already counts as wrong.")

    deadline = commitments.parse_deadline(call["deadline"])
    reveal_until = commitments.parse_deadline(call["reveal_until"])

    if now < deadline:
        minutes_left = int((deadline - now).total_seconds() // 60) + 1
        raise ProofOfCallError(f"The deadline has not arrived yet (about {minutes_left} min left).")
    if now > reveal_until:
        expire_overdue_commits(now)
        raise ProofOfCallError("Too late: the reveal window is closed. The call now counts as wrong.")

    # --- Does the revealed prediction match the hash? ---------------------
    recomputed_hash = commitments.compute_commitment(
        call["handle"], ticker, direction, target, call["deadline"], nonce.strip()
    )
    if recomputed_hash != call["commit_hash"]:
        raise ProofOfCallError(
            "The data does NOT match the commitment. Either a value is mistyped, "
            "or someone is trying to change the prediction after the fact."
        )

    # --- Fetch prices and score the call ----------------------------------
    ticker = commitments.normalize_ticker(ticker)
    committed_at = commitments.parse_deadline(call["committed_at"])

    try:
        price_at_deadline, source = prices.get_price(ticker, deadline, use_live_data)
        price_at_commit, _ = prices.get_price(ticker, committed_at, use_live_data)
    except prices.PriceNotAvailable as error:
        raise ProofOfCallError(str(error))

    correct = evaluate_call(direction, target, price_at_deadline)

    block = ledger.append_block(
        "REVEAL",
        {
            "commit_hash": call["commit_hash"],
            "commit_code": call["code"],
            "handle": call["handle"],
            "ticker": ticker,
            "direction": direction,
            "target": commitments.format_target(target),
            "deadline": call["deadline"],
            "nonce": nonce.strip(),
            "price_at_commit": round(price_at_commit, 4),
            "price_at_deadline": round(price_at_deadline, 4),
            "price_source": source,
            "correct": correct,
        },
        moment=now,
    )

    return {"block": block, "correct": correct, "price_at_deadline": price_at_deadline,
            "price_at_commit": price_at_commit, "source": source, "ticker": ticker}


def expire_overdue_commits(now=None) -> int:
    """
    ANTI-CHEATING RULE: every call whose reveal window has closed without a
    reveal gets an EXPIRE block and counts as wrong.
    Called every time the app is opened. Returns how many calls were expired.
    """
    now = _now(now)
    expired_count = 0

    for call in get_calls(ledger.load_chain(), now):
        if call["status"] == STATUS_AWAITING:
            reveal_until = commitments.parse_deadline(call["reveal_until"])
            if now > reveal_until:
                ledger.append_block(
                    "EXPIRE",
                    {"commit_hash": call["commit_hash"], "commit_code": call["code"],
                     "handle": call["handle"], "reason": "Not revealed within the reveal window"},
                    moment=now,
                )
                expired_count += 1

    return expired_count


def subscribe_verified(handle: str, now=None) -> dict:
    """Simulated payment for the 'Verified' plan: adds a VERIFY block."""
    now = _now(now)
    handle = commitments.normalize_handle(handle)

    if handle not in get_influencers(ledger.load_chain()):
        raise ProofOfCallError(f"{handle} is not registered.")

    valid_until = now + timedelta(days=config.VERIFIED_PLAN_DAYS)
    return ledger.append_block(
        "VERIFY",
        {"handle": handle, "plan": "Verified monthly",
         "price_eur": config.VERIFIED_PRICE_EUR_PER_MONTH,
         "valid_until": commitments.format_deadline(valid_until)},
        moment=now,
    )


# ===========================================================================
# Statistics
# ===========================================================================

def compute_stats(calls: list) -> dict:
    """Hit rate and counts for a list of calls (usually one influencer's calls)."""
    correct = sum(1 for call in calls if call["status"] == STATUS_CORRECT)
    wrong = sum(1 for call in calls if call["status"] == STATUS_WRONG)
    expired = sum(1 for call in calls if call["status"] == STATUS_EXPIRED)
    open_calls = sum(1 for call in calls if call["status"] in (STATUS_PENDING, STATUS_AWAITING))

    resolved = correct + wrong + expired
    hit_rate = correct / resolved if resolved > 0 else None

    # Reveal rate: how often the influencer had the courage to reveal
    reveal_rate = (correct + wrong) / resolved if resolved > 0 else None

    return {
        "correct": correct,
        "wrong": wrong,
        "expired": expired,
        "open": open_calls,
        "resolved": resolved,
        "hit_rate": hit_rate,
        "reveal_rate": reveal_rate,
    }


def compute_leaderboard(chain: list, now=None) -> pd.DataFrame:
    """One row per influencer, best verified hit rate first."""
    now = _now(now)
    all_calls = get_calls(chain, now)
    rows = []

    for handle, profile in get_influencers(chain).items():
        their_calls = [call for call in all_calls if call["handle"] == handle]
        stats = compute_stats(their_calls)

        rows.append({
            "Influencer": handle,
            "Name": profile["display_name"],
            "Platform": profile["platform"],
            "Verified": is_verified(chain, handle, now),
            "Hit rate": stats["hit_rate"],
            "Resolved calls": stats["resolved"],
            "Correct": stats["correct"],
            "Wrong": stats["wrong"],
            "Expired": stats["expired"],
            "Open": stats["open"],
            "Reveal rate": stats["reveal_rate"],
        })

    table = pd.DataFrame(rows)
    if table.empty:
        return table

    # Influencers with enough calls first, then by hit rate
    table["Ranked"] = table["Resolved calls"] >= config.MIN_CALLS_FOR_RANKING
    table = table.sort_values(["Ranked", "Hit rate", "Resolved calls"],
                              ascending=[False, False, False], na_position="last")
    return table.drop(columns="Ranked").reset_index(drop=True)


def badge_text(chain: list, handle: str, now=None) -> str:
    """The text an influencer can paste in their social media bio."""
    calls = [call for call in get_calls(chain, now) if call["handle"] == handle]
    stats = compute_stats(calls)
    if stats["hit_rate"] is None:
        return f"✅ ProofOfCall Verified · track record starting · {handle}"
    return (f"✅ ProofOfCall Verified · {stats['hit_rate']:.0%} hit rate on "
            f"{stats['resolved']} verified calls · {handle}")
