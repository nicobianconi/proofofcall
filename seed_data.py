"""
seed_data.py
------------
Creates the demo history (seed_ledger.json), so the leaderboard is not empty
when you open the app for the first time.

Run it only if you want to regenerate the demo data:

    python seed_data.py

It creates 4 fictional influencers with calls between September and November 2026,
scored with the SIMULATED market (not real prices). Each one shows a typical behaviour:

    @valuevera      careful analyst, reveals every call, high hit rate
    @cryptokingmax  "hype" account: only reveals winners -> his losers expire
    @moonshotmarco  honest but not very good: reveals everything, low hit rate
    @dividendgiulia few calls, still building a track record
"""

import json
import random
from datetime import datetime, timedelta, timezone

import config
import ledger
import prices
import services


# Fixed random seed: the demo data is identical every time you run the script
random.seed(42)


INFLUENCERS = [
    # handle,           name,             platform,   skill, reveals_losers, number_of_calls
    ("@valuevera",      "Vera Rossi",     "YouTube",   0.78, True,  14),
    ("@cryptokingmax",  "Max Crypto",     "TikTok",    0.45, False, 18),
    ("@moonshotmarco",  "Marco Moonshot", "Telegram",  0.40, True,  10),
    ("@dividendgiulia", "Giulia Bianchi", "Instagram", 0.65, True,  4),
]

TICKERS = ["BTC-USD", "ETH-USD", "SOL-USD", "AAPL", "TSLA", "NVDA", "ENI.MI"]

START = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
END = datetime(2026, 11, 14, 9, 0, tzinfo=timezone.utc)
LAST_DAY = datetime(2026, 11, 18, 18, 0, tzinfo=timezone.utc)


def random_moment(start, end):
    seconds = int((end - start).total_seconds())
    return (start + timedelta(seconds=random.randint(0, seconds))).replace(second=0, microsecond=0)


def plan_calls():
    """Decide (before writing anything) every commit and reveal, in time order."""
    events = []

    for handle, _, _, skill, reveals_losers, number_of_calls in INFLUENCERS:
        for _ in range(number_of_calls):
            committed_at = random_moment(START, END)
            deadline = (committed_at + timedelta(days=random.randint(1, 6))).replace(hour=21, minute=0)
            ticker = random.choice(TICKERS)

            price_now = prices.get_simulated_price(ticker, committed_at)
            price_later = prices.get_simulated_price(ticker, deadline)

            # A skilled influencer "guesses" the real direction more often
            real_direction = "UP" if price_later >= price_now else "DOWN"
            if random.random() < skill:
                direction = real_direction
            else:
                direction = "DOWN" if real_direction == "UP" else "UP"

            # Target: a small move (0.5% - 3%) in the predicted direction
            move = random.uniform(0.005, 0.03)
            target = price_now * (1 + move) if direction == "UP" else price_now * (1 - move)
            target = round(target, 2)

            will_be_correct = services.evaluate_call(direction, target, price_later)
            will_reveal = will_be_correct or reveals_losers

            events.append({
                "handle": handle, "ticker": ticker, "direction": direction, "target": target,
                "committed_at": committed_at, "deadline": deadline, "reveal": will_reveal,
            })

    # Two calls that are still open at the time of the class demo (hidden on the ledger)
    for handle, ticker, direction in [("@valuevera", "NVDA", "UP"), ("@cryptokingmax", "BTC-USD", "UP")]:
        committed_at = datetime(2026, 11, 18, 16, 30, tzinfo=timezone.utc)
        deadline = datetime(2026, 11, 27, 21, 0, tzinfo=timezone.utc)
        price_now = prices.get_simulated_price(ticker, committed_at)
        events.append({
            "handle": handle, "ticker": ticker, "direction": direction,
            "target": round(price_now * 1.04, 2),
            "committed_at": committed_at, "deadline": deadline, "reveal": False,
        })

    return events


def main():
    # Build the seed in its own file, starting from a fresh genesis block
    config.LEDGER_FILE = config.SEED_LEDGER_FILE
    ledger.save_chain([ledger.create_genesis_block(START - timedelta(days=10))])

    # 1) Register the influencers
    for number, (handle, name, platform, *_rest) in enumerate(INFLUENCERS):
        services.register_influencer(handle, name, platform, now=START - timedelta(days=5 - number))

    # 2) Turn the plan into a time-ordered list of actions (commits and reveals)
    actions = []
    for event in plan_calls():
        actions.append((event["committed_at"], "commit", event))
        if event["reveal"]:
            reveal_time = event["deadline"] + timedelta(minutes=random.randint(1, 10))
            actions.append((reveal_time, "reveal", event))

    # Verified subscriptions (still valid during the class demo)
    actions.append((datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc), "verify", {"handle": "@valuevera"}))
    actions.append((datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc), "verify", {"handle": "@dividendgiulia"}))

    actions.sort(key=lambda action: action[0])

    # 3) Replay everything in chronological order, exactly like real users would
    for moment, kind, event in actions:
        services.expire_overdue_commits(now=moment)  # anti-cheating rule runs along the way

        if kind == "commit":
            result = services.create_commit(event["handle"], event["ticker"], event["direction"],
                                            event["target"], event["deadline"], now=moment)
            event["code"] = result["code"]
            event["nonce"] = json.loads(result["receipt"])["nonce"]  # the secret kept by the influencer

        elif kind == "reveal":
            services.reveal_commit(event["code"], event["ticker"], event["direction"], event["target"],
                                   event["nonce"], use_live_data=False, now=moment)

        elif kind == "verify":
            services.subscribe_verified(event["handle"], now=moment)

    services.expire_overdue_commits(now=LAST_DAY)

    chain = ledger.load_chain()
    print(f"Seed ledger created: {len(chain)} blocks -> {config.SEED_LEDGER_FILE.name}")
    print(ledger.verify_chain(chain)[1])
    print()
    print(services.compute_leaderboard(chain, now=LAST_DAY).to_string())


if __name__ == "__main__":
    main()
