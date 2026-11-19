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

SCORING RULE (from the PRD)
    - UP   is a hit if the price at the deadline is AT or ABOVE the target
    - DOWN is a hit if the price at the deadline is AT or BELOW the target
    - the target must be at least 2% away from the price at commit time
      (0.1% for live demo calls), in the predicted direction
    - unrevealed or invalid calls count as WRONG
    - a hit rate is shown only from 20 resolved calls, with a 95% confidence interval
"""

import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

import commitments
import config
import ledger
import prices


# Possible states of a call
STATUS_PENDING = "Pending"                    # deadline not reached yet
STATUS_AWAITING = "Awaiting reveal"           # deadline passed, reveal window open
STATUS_CORRECT = "Correct"
STATUS_WRONG = "Wrong"
STATUS_EXPIRED = "Expired (counts as wrong)"
STATUS_INVALID = "Invalid (counts as wrong)"  # target too close to the entry price

RESOLVED_STATUSES = (STATUS_CORRECT, STATUS_WRONG, STATUS_EXPIRED, STATUS_INVALID)

LOCAL_TZ = ZoneInfo(config.DISPLAY_TIMEZONE)


class ProofOfCallError(Exception):
    """An error with a message that can be shown directly to the user."""


def _now(now=None) -> datetime:
    return now or datetime.now(timezone.utc)


# ===========================================================================
# Small rule helpers
# ===========================================================================

def daily_close_deadline(day) -> datetime:
    """A calendar date -> the 'close' moment of that day (22:00 Italian time), in UTC."""
    hour, minute = (int(part) for part in config.DAILY_CLOSE_TIME.split(":"))
    local_close = datetime(day.year, day.month, day.day, hour, minute, tzinfo=LOCAL_TZ)
    return local_close.astimezone(timezone.utc)


def target_distance(direction: str, target: float, entry_price: float) -> float:
    """
    How far the target is from the entry price, IN THE PREDICTED DIRECTION.
    Example: entry 100, UP to 103 -> +0.03 (3%). UP to 98 -> -0.02 (wrong direction).
    """
    if direction == "UP":
        return float(target) / entry_price - 1
    return 1 - float(target) / entry_price


def evaluate_call(direction: str, target: float, price_at_deadline: float) -> bool:
    """UP: hit if price >= target. DOWN: hit if price <= target."""
    if direction == "UP":
        return price_at_deadline >= float(target)
    return price_at_deadline <= float(target)


def wilson_interval(successes: int, total: int, z: float = config.CONFIDENCE_Z) -> tuple:
    """
    95% confidence interval of a hit rate (Wilson score interval).
    With few calls the interval is wide: a 3/3 record is NOT proof of skill.
    """
    if total == 0:
        return None, None
    rate = successes / total
    denominator = 1 + z ** 2 / total
    centre = (rate + z ** 2 / (2 * total)) / denominator
    margin = z * math.sqrt(rate * (1 - rate) / total + z ** 2 / (4 * total ** 2)) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


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
                "call_type": data.get("call_type", "demo"),
                "committed_at": block["timestamp"],
                "deadline": data["deadline"],
                "reveal_until": data["reveal_until"],
                "min_target_distance": data.get("min_target_distance", 0.0),
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
            if data.get("valid", True) is False:
                status = STATUS_INVALID
            elif data["correct"]:
                status = STATUS_CORRECT
            else:
                status = STATUS_WRONG

            call.update({
                "ticker": data["ticker"],
                "direction": data["direction"],
                "target": data["target"],
                "price_at_commit": data["price_at_commit"],
                "price_at_deadline": data["price_at_deadline"],
                "price_source": data["price_source"],
                "status": status,
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
    code = code.strip().lower().replace(config.CODE_PREFIX.lower(), "")
    for call in get_calls(chain, now):
        if call["code"] == code or call["commit_hash"] == code:
            return call
    raise ProofOfCallError(f"No call found with code '{code}'.")


def active_plan(chain: list, handle: str, now=None):
    """Name of the active Verified plan ('Pro', 'Plus') or None."""
    now = _now(now)
    for block in reversed(chain):
        if block["type"] == "VERIFY" and block["data"]["handle"] == handle:
            valid_until = commitments.parse_deadline(block["data"]["valid_until"])
            return block["data"]["plan"] if now <= valid_until else None
    return None


def is_verified(chain: list, handle: str, now=None) -> bool:
    """True if the influencer has an active 'Verified' subscription."""
    return active_plan(chain, handle, now) is not None


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


def create_commit(handle, ticker, direction, target, deadline: datetime,
                  call_type="standard", use_live_data=True, now=None) -> dict:
    """
    Commit a hidden prediction.
    Returns a dict with the block, the full hash, the short code, the secret receipt
    and the entry price used to check the 2% rule.
    """
    now = _now(now)
    handle = commitments.normalize_handle(handle)
    ticker = commitments.normalize_ticker(ticker)
    rules = config.CALL_TYPES[call_type]

    # --- Basic checks -----------------------------------------------------
    if handle not in get_influencers(ledger.load_chain()):
        raise ProofOfCallError(f"{handle} is not registered. Create a profile first.")
    if not ticker:
        raise ProofOfCallError("Please enter a ticker.")
    if direction not in config.DIRECTIONS:
        raise ProofOfCallError("Direction must be UP or DOWN.")
    if target is None or float(target) <= 0:
        raise ProofOfCallError("The target price must be greater than 0.")
    if deadline < now + timedelta(minutes=config.MIN_MINUTES_UNTIL_DEADLINE):
        raise ProofOfCallError("The deadline must be in the future.")

    # --- The 2% rule: the target must be far enough from today's price ----
    try:
        entry_price, _ = prices.get_price(ticker, now, use_live_data)
    except prices.PriceNotAvailable as error:
        raise ProofOfCallError(f"Cannot check the target against the current price: {error}")

    distance = target_distance(direction, target, entry_price)
    minimum = rules["min_target_distance"]
    if distance < minimum:
        if direction == "UP":
            needed = entry_price * (1 + minimum)
            raise ProofOfCallError(
                f"Target too close: {ticker} is at {entry_price:,.2f}. "
                f"An UP call needs a target of at least {needed:,.2f} (+{minimum:.1%}).")
        needed = entry_price * (1 - minimum)
        raise ProofOfCallError(
            f"Target too close: {ticker} is at {entry_price:,.2f}. "
            f"A DOWN call needs a target of at most {needed:,.2f} (-{minimum:.1%}).")

    # --- Build the commitment ---------------------------------------------
    deadline_iso = commitments.format_deadline(deadline)
    reveal_until = deadline.replace(microsecond=0) + timedelta(minutes=rules["reveal_window_minutes"])
    nonce = commitments.generate_nonce()
    commit_hash = commitments.compute_commitment(handle, ticker, direction, target, deadline_iso, nonce)

    # Only PUBLIC information goes on the ledger: who, when, the hash, the deadline and the rules.
    # Ticker, direction, target and nonce stay secret in the receipt.
    block = ledger.append_block(
        "COMMIT",
        {
            "handle": handle,
            "commit_hash": commit_hash,
            "commit_code": commitments.short_code(commit_hash),
            "call_type": call_type,
            "deadline": deadline_iso,
            "reveal_until": commitments.format_deadline(reveal_until),
            "min_target_distance": minimum,
        },
        moment=now,
    )

    receipt = commitments.make_receipt(handle, ticker, direction, target, deadline_iso, nonce, commit_hash)

    return {
        "block": block,
        "commit_hash": commit_hash,
        "code": commitments.short_code(commit_hash),
        "receipt": receipt,
        "entry_price": entry_price,
    }


def reveal_commit(code, ticker, direction, target, nonce, use_live_data=True, now=None) -> dict:
    """
    Reveal a call: check the hash, fetch the real prices, check the 2% rule,
    decide if the call was correct and write the result on the ledger.
    """
    now = _now(now)
    chain = ledger.load_chain()
    call = find_call(chain, code, now)

    # --- Is this call in a state that can be revealed? --------------------
    if call["status"] in (STATUS_CORRECT, STATUS_WRONG, STATUS_INVALID):
        raise ProofOfCallError("This call has already been revealed.")
    if call["status"] == STATUS_EXPIRED:
        raise ProofOfCallError("Too late: this call expired and already counts as wrong.")

    deadline = commitments.parse_deadline(call["deadline"])
    reveal_until = commitments.parse_deadline(call["reveal_until"])

    if now < deadline:
        minutes_left = int((deadline - now).total_seconds() // 60) + 1
        if minutes_left > 120:
            raise ProofOfCallError(f"The deadline has not arrived yet (about {minutes_left // 60} hours left).")
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

    # --- Fetch prices -----------------------------------------------------
    ticker = commitments.normalize_ticker(ticker)
    committed_at = commitments.parse_deadline(call["committed_at"])

    try:
        price_at_deadline, source = prices.get_price(ticker, deadline, use_live_data)
        price_at_commit, _ = prices.get_price(ticker, committed_at, use_live_data)
    except prices.PriceNotAvailable as error:
        raise ProofOfCallError(str(error))

    # --- 2% rule, checked again with the official price at commit time ----
    # (small 10% tolerance: the live quote seen at commit time can differ slightly
    #  from the 1-minute candle used here)
    distance = target_distance(direction, target, price_at_commit)
    valid = distance >= call["min_target_distance"] * 0.9

    correct = valid and evaluate_call(direction, target, price_at_deadline)

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
            "valid": valid,
            "correct": correct,
        },
        moment=now,
    )

    return {"block": block, "correct": correct, "valid": valid,
            "price_at_deadline": price_at_deadline, "price_at_commit": price_at_commit,
            "source": source, "ticker": ticker}


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


def subscribe_verified(handle: str, plan: str = "Pro", now=None) -> dict:
    """Simulated payment for a 'Verified' plan: adds a VERIFY block."""
    now = _now(now)
    handle = commitments.normalize_handle(handle)

    if handle not in get_influencers(ledger.load_chain()):
        raise ProofOfCallError(f"{handle} is not registered.")
    if plan not in config.VERIFIED_PLANS:
        raise ProofOfCallError(f"Unknown plan '{plan}'.")

    valid_until = now + timedelta(days=config.VERIFIED_PLAN_DAYS)
    return ledger.append_block(
        "VERIFY",
        {"handle": handle, "plan": plan,
         "price_eur": config.VERIFIED_PLANS[plan],
         "valid_until": commitments.format_deadline(valid_until)},
        moment=now,
    )


# ===========================================================================
# Statistics
# ===========================================================================

def compute_stats(calls: list) -> dict:
    """Hit rate, confidence interval and counts for a list of calls (usually one influencer's)."""
    correct = sum(1 for call in calls if call["status"] == STATUS_CORRECT)
    wrong = sum(1 for call in calls if call["status"] == STATUS_WRONG)
    expired = sum(1 for call in calls if call["status"] == STATUS_EXPIRED)
    invalid = sum(1 for call in calls if call["status"] == STATUS_INVALID)
    open_calls = sum(1 for call in calls if call["status"] in (STATUS_PENDING, STATUS_AWAITING))

    resolved = correct + wrong + expired + invalid
    hit_rate = correct / resolved if resolved > 0 else None
    ci_low, ci_high = wilson_interval(correct, resolved)

    # What followers would believe if they only saw the revealed winners and losers
    revealed = correct + wrong
    feed_hit_rate = correct / revealed if revealed > 0 else None

    return {
        "correct": correct,
        "wrong": wrong,
        "expired": expired,
        "invalid": invalid,
        "open": open_calls,
        "resolved": resolved,
        "hit_rate": hit_rate,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "feed_hit_rate": feed_hit_rate,
        "has_track_record": resolved >= config.MIN_CALLS_FOR_HIT_RATE,
    }


def compute_leaderboard(chain: list, now=None) -> pd.DataFrame:
    """One row per influencer: established track records first, best hit rate first."""
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
            "Track record": stats["has_track_record"],
            "Hit rate": stats["hit_rate"],
            "CI low": stats["ci_low"],
            "CI high": stats["ci_high"],
            "Feed hit rate": stats["feed_hit_rate"],
            "Resolved calls": stats["resolved"],
            "Correct": stats["correct"],
            "Wrong": stats["wrong"],
            "Expired": stats["expired"],
            "Invalid": stats["invalid"],
            "Open": stats["open"],
        })

    table = pd.DataFrame(rows)
    if table.empty:
        return table

    table = table.sort_values(["Track record", "Hit rate", "Resolved calls"],
                              ascending=[False, False, False], na_position="last")
    return table.reset_index(drop=True)


def badge_text(chain: list, handle: str, now=None) -> str:
    """The text an influencer can paste in their social media bio."""
    calls = [call for call in get_calls(chain, now) if call["handle"] == handle]
    stats = compute_stats(calls)
    if not stats["has_track_record"]:
        return (f"✅ ProofOfCall Verified · building track record "
                f"({stats['resolved']}/{config.MIN_CALLS_FOR_HIT_RATE} calls) · {handle}")
    return (f"✅ ProofOfCall Verified · {stats['hit_rate']:.0%} hit rate on "
            f"{stats['resolved']} verified calls · {handle}")
