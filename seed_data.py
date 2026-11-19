"""
seed_data.py
------------
Creates the demo history (seed_ledger.json), so the leaderboard is not empty
when you open the app for the first time.

Run it only if you want to regenerate the demo data:

    python seed_data.py

It creates 4 fictional influencers with STANDARD calls (settled at the daily close,
target at least 2% away) between August and November 2026, scored with the
SIMULATED market (not real prices). Each one shows a typical behaviour:

    @valuevera      careful analyst, reveals every call, good hit rate
    @cryptokingmax  "hype" account: only reveals winners -> his losers expire
    @moonshotmarco  honest but not very good: reveals everything, low hit rate
    @dividendgiulia few calls: still building a track record (under 20 calls)
"""

import json
import random
from datetime import datetime, timedelta, timezone

import config
import ledger
import prices
import services


# Fixed random seed: the demo data is identical every time you run the script
random.seed(7)


INFLUENCERS = [
    # handle,           name,             platform,   skill, reveals_losers, number_of_calls
    ("@valuevera",      "Vera Rossi",     "YouTube",   0.68, True,  26),
    ("@cryptokingmax",  "Max Crypto",     "TikTok",    0.15, False, 30),
    ("@moonshotmarco",  "Marco Moonshot", "Telegram",  0.25, True,  22),
    ("@dividendgiulia", "Giulia Bianchi", "Instagram", 0.65, True,  8),
]

TICKERS = ["BTC-USD", "ETH-USD", "SOL-USD", "AAPL", "TSLA", "NVDA", "ENI.MI"]

START = datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc)
END = datetime(2026, 11, 10, 8, 0, tzinfo=timezone.utc)
LAST_DAY = datetime(2026, 11, 18, 18, 0, tzinfo=timezone.utc)
MIN_DISTANCE = config.CALL_TYPES["standard"]["min_target_distance"]


def random_moment(start, end):
    seconds = int((end - start).total_seconds())
    return (start + timedelta(seconds=random.randint(0, seconds))).replace(second=0, microsecond=0)


def choose_prediction(entry_price, future_price, skill):
    """
    Pick direction and target. A skilled influencer more often picks a target
    the price really reaches. The target is always at least 2% away (valid call).
    """
    real_move = future_price / entry_price - 1
    real_direction = "UP" if real_move >= 0 else "DOWN"

    wants_to_be_right = random.random() < skill
    if wants_to_be_right and abs(real_move) > MIN_DISTANCE + 0.002:
        # A target between +2% and the real move: it will be reached
        direction = real_direction
        distance = random.uniform(MIN_DISTANCE + 0.001, abs(real_move) - 0.001)
    else:
        # A random guess: 3% - 8% in a random direction (usually not reached)
        direction = random.choice(["UP", "DOWN"])
        distance = random.uniform(0.03, 0.08)

    target = entry_price * (1 + distance) if direction == "UP" else entry_price * (1 - distance)
    return direction, round(target, 2)


def plan_calls():
    """Decide (before writing anything) every commit and reveal, in time order."""
    events = []

    for handle, _, _, skill, reveals_losers, number_of_calls in INFLUENCERS:
        for _ in range(number_of_calls):
            committed_at = random_moment(START, END)

            # Skilled influencers are better at picking opportunities: they look at
            # a few tickers/horizons and keep the one with a clear move
            attempts = 6 if random.random() < skill else 1
            for _attempt in range(attempts):
                deadline_day = (committed_at + timedelta(days=random.randint(1, 7))).date()
                deadline = services.daily_close_deadline(deadline_day)
                ticker = random.choice(TICKERS)
                entry_price = prices.get_simulated_price(ticker, committed_at)
                future_price = prices.get_simulated_price(ticker, deadline)
                if abs(future_price / entry_price - 1) > MIN_DISTANCE + 0.005:
                    break
            direction, target = choose_prediction(entry_price, future_price, skill)

            will_be_correct = services.evaluate_call(direction, target, future_price)
            events.append({
                "handle": handle, "ticker": ticker, "direction": direction, "target": target,
                "committed_at": committed_at, "deadline": deadline,
                "reveal": will_be_correct or reveals_losers,
            })

    # Two calls still open at the time of the class demo (hidden on the ledger)
    for handle, ticker, direction in [("@valuevera", "NVDA", "UP"), ("@cryptokingmax", "BTC-USD", "UP")]:
        committed_at = datetime(2026, 11, 18, 16, 30, tzinfo=timezone.utc)
        entry_price = prices.get_simulated_price(ticker, committed_at)
        events.append({
            "handle": handle, "ticker": ticker, "direction": direction,
            "target": round(entry_price * 1.04, 2), "committed_at": committed_at,
            "deadline": services.daily_close_deadline(datetime(2026, 11, 27).date()),
            "reveal": False,
        })

    return events


def main():
    # Build the seed in a temporary database, starting from a fresh genesis block
    config.LEDGER_DB = config.BASE_DIR / "seed_build.db"
    ledger.replace_all_blocks([ledger.create_genesis_block(START - timedelta(days=10))])

    # 1) Register the influencers
    for number, (handle, name, platform, *_rest) in enumerate(INFLUENCERS):
        services.register_influencer(handle, name, platform, now=START - timedelta(days=5 - number))

    # 2) Turn the plan into a time-ordered list of actions (commits and reveals)
    actions = []
    for event in plan_calls():
        actions.append((event["committed_at"], "commit", event))
        if event["reveal"]:
            reveal_time = event["deadline"] + timedelta(minutes=random.randint(5, 600))
            actions.append((reveal_time, "reveal", event))

    # Verified subscriptions (still valid during the class demo)
    actions.append((datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc), "verify",
                    {"handle": "@valuevera", "plan": "Plus"}))
    actions.append((datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc), "verify",
                    {"handle": "@dividendgiulia", "plan": "Pro"}))

    actions.sort(key=lambda action: action[0])

    # 3) Replay everything in chronological order, exactly like real users would
    for moment, kind, event in actions:
        services.expire_overdue_commits(now=moment)  # anti-cheating rule runs along the way

        if kind == "commit":
            result = services.create_commit(event["handle"], event["ticker"], event["direction"],
                                            event["target"], event["deadline"], call_type="standard",
                                            use_live_data=False, now=moment)
            event["code"] = result["code"]
            event["nonce"] = json.loads(result["receipt"])["nonce"]  # the secret kept by the influencer

        elif kind == "reveal":
            services.reveal_commit(event["code"], event["ticker"], event["direction"], event["target"],
                                   event["nonce"], use_live_data=False, now=moment)

        elif kind == "verify":
            services.subscribe_verified(event["handle"], event["plan"], now=moment)

    services.expire_overdue_commits(now=LAST_DAY)

    # 4) Save as readable JSON and remove the temporary database
    ledger.export_chain_to_json(config.SEED_LEDGER_FILE)
    chain = ledger.load_chain()
    config.LEDGER_DB.unlink()

    print(f"Seed ledger created: {len(chain)} blocks -> {config.SEED_LEDGER_FILE.name}")
    print(ledger.verify_chain(chain)[1])
    print()
    table = services.compute_leaderboard(chain, now=LAST_DAY)
    print(table.drop(columns=["Name", "Platform"]).to_string())


if __name__ == "__main__":
    main()
