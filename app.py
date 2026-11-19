"""
app.py
------
ProofOfCall - verified track records for finfluencers.
The Streamlit interface. Start it with:

    streamlit run app.py

The app is organised in pages (chosen from the sidebar). Each page is one
function below. All the real work is done in services.py.
"""

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import commitments
import config
import ledger
import prices
import services


LOCAL_TZ = ZoneInfo(config.DISPLAY_TIMEZONE)

st.set_page_config(page_title="ProofOfCall", page_icon="✅", layout="wide")


# ===========================================================================
# Small helpers used by several pages
# ===========================================================================

def show_time(iso_text: str) -> str:
    """'2026-11-23T14:30:00Z' -> '23 Nov 2026, 15:30' (local time)."""
    if not iso_text:
        return ""
    moment = commitments.parse_deadline(iso_text).astimezone(LOCAL_TZ)
    return moment.strftime("%d %b %Y, %H:%M")


def show_percent(value) -> str:
    if value is None or pd.isna(value):
        return "–"
    return f"{value:.0%}"


@st.cache_data(ttl=60, show_spinner=False)
def current_price(ticker: str, use_live_data: bool):
    """Current price, cached for 60 seconds so the app stays fast."""
    try:
        price, source = prices.get_price(ticker, datetime.now(timezone.utc), use_live_data)
        return price, source
    except prices.PriceNotAvailable:
        return None, None


def influencer_selector(label: str, key: str):
    """A dropdown with all registered influencers (or a warning if there are none)."""
    influencers = services.get_influencers(ledger.load_chain())
    if not influencers:
        st.warning("No influencer registered yet. Go to **👤 Register** first.")
        return None
    return st.selectbox(label, list(influencers.keys()), key=key)


def calls_to_table(calls: list) -> pd.DataFrame:
    """Turn a list of calls into a readable table. Hidden fields show as 🔒."""
    rows = []
    for call in calls:
        hidden = call["ticker"] is None
        rows.append({
            "Code": "#PoC-" + call["code"],
            "Influencer": call["handle"],
            "Committed": show_time(call["committed_at"]),
            "Deadline": show_time(call["deadline"]),
            "Ticker": "🔒" if hidden else call["ticker"],
            "Direction": "🔒" if hidden else ("📈 UP" if call["direction"] == "UP" else "📉 DOWN"),
            "Target": "🔒" if hidden else call["target"],
            "Price at commit": call["price_at_commit"],
            "Price at deadline": call["price_at_deadline"],
            "Status": call["status"],
        })
    return pd.DataFrame(rows)


STATUS_ICONS = {
    services.STATUS_CORRECT: "✅",
    services.STATUS_WRONG: "❌",
    services.STATUS_EXPIRED: "⌛",
    services.STATUS_PENDING: "🔒",
    services.STATUS_AWAITING: "⏰",
}


# ===========================================================================
# Sidebar: navigation and demo settings
# ===========================================================================

PAGES = [
    "🏠 Home",
    "👤 Register",
    "🔒 Commit a call",
    "🔓 Reveal a call",
    "🏆 Leaderboard",
    "📊 Influencer profile",
    "⛓️ Ledger explorer",
    "🔌 API for brokers",
]

with st.sidebar:
    st.title("✅ ProofOfCall")
    st.caption("Verified track records for finfluencers")

    page = st.radio("Go to", PAGES, label_visibility="collapsed")

    st.divider()
    st.subheader("Price data")
    use_live_data = st.toggle(
        "Live prices (Yahoo Finance)",
        value=True,
        help="Turn off to use the offline simulated market (backup if there is no internet).",
    )
    if use_live_data:
        st.caption("Real market prices. Tip: use crypto (BTC-USD) for live demos, it trades 24/7.")
    else:
        st.caption("⚠️ Simulated prices: NOT real market data.")

    st.divider()
    with st.expander("Demo tools"):
        st.write("Restore the demo influencers and their history.")
        if st.button("Reset demo data"):
            ledger.reset_to_seed()
            st.cache_data.clear()
            st.success("Demo data restored.")
            st.rerun()


# ANTI-CHEATING RULE: every time anyone opens the app, overdue calls expire
expired_now = services.expire_overdue_commits()
if expired_now:
    st.toast(f"⌛ {expired_now} call(s) were not revealed in time and now count as wrong.")

chain = ledger.load_chain()


# ===========================================================================
# Page: Home
# ===========================================================================

def page_home():
    st.title("ProofOfCall")
    st.subheader("Verified track records for financial influencers")

    st.write(
        "Finfluencers on TikTok, YouTube and Telegram can delete their wrong stock and crypto "
        "calls and repost only the winners. Their followers never see the real hit rate. "
        "**ProofOfCall makes every call permanent and verifiable.**"
    )

    column_1, column_2, column_3 = st.columns(3)
    with column_1:
        st.markdown("#### 1. 🔒 Commit")
        st.write("Before posting a tip, the influencer publishes a **hash** of the prediction. "
                 "Nobody can read it, and nobody can change it.")
    with column_2:
        st.markdown("#### 2. 🔓 Reveal")
        st.write("At the deadline, the influencer reveals the prediction. The app checks the hash "
                 "and fetches the **real market price**.")
    with column_3:
        st.markdown("#### 3. 🏆 Track record")
        st.write(f"Every result is scored automatically. A call not revealed within "
                 f"{config.REVEAL_WINDOW_MINUTES} minutes after the deadline **counts as wrong**.")

    st.divider()

    calls = services.get_calls(chain)
    influencers = services.get_influencers(chain)
    verified_count = sum(services.is_verified(chain, handle) for handle in influencers)
    is_intact, integrity_message = ledger.verify_chain(chain)

    metric_1, metric_2, metric_3, metric_4 = st.columns(4)
    metric_1.metric("Influencers", len(influencers))
    metric_2.metric("Verified badges", verified_count)
    metric_3.metric("Calls on the ledger", len(calls))
    metric_4.metric("Ledger blocks", len(chain))

    if is_intact:
        st.success("⛓️ Ledger integrity: " + integrity_message)
    else:
        st.error("⛓️ Ledger integrity problem: " + integrity_message)

    st.markdown("#### Latest calls")
    st.dataframe(calls_to_table(calls[:10]), hide_index=True, width="stretch")


# ===========================================================================
# Page: Register
# ===========================================================================

def page_register():
    st.title("👤 Register as an influencer")
    st.write("Create your public profile. Your handle is linked to every call you commit.")

    with st.form("register_form", clear_on_submit=True):
        handle = st.text_input("Handle", placeholder="@yourname")
        display_name = st.text_input("Display name", placeholder="Your Name")
        platform = st.selectbox("Main platform", ["TikTok", "YouTube", "Instagram", "Telegram", "X", "Other"])
        submitted = st.form_submit_button("Create profile", type="primary")

    if submitted:
        try:
            block = services.register_influencer(handle, display_name, platform)
            st.success(f"Welcome {block['data']['handle']}! Your profile is on the ledger (block #{block['index']}).")
        except services.ProofOfCallError as error:
            st.error(str(error))


# ===========================================================================
# Page: Commit a call
# ===========================================================================

def page_commit():
    st.title("🔒 Commit a call")
    st.write("Lock in your prediction **before** you post it. Only the hash goes on the public ledger.")

    handle = influencer_selector("Who are you?", key="commit_handle")
    if handle is None:
        return

    # --- Ticker (outside the form, so the current price updates immediately)
    ticker_choice = st.selectbox("Ticker", config.SUGGESTED_TICKERS + ["Other..."])
    if ticker_choice == "Other...":
        ticker = st.text_input("Yahoo Finance ticker", placeholder="e.g. MSFT, ISP.MI, DOGE-USD")
    else:
        ticker = ticker_choice
    ticker = commitments.normalize_ticker(ticker or "")

    if ticker:
        price_now, source = current_price(ticker, use_live_data)
        if price_now is not None:
            st.info(f"Current price of **{ticker}**: **{price_now:,.2f}**  ·  source: {source}")
        else:
            st.warning(f"Could not fetch the current price of {ticker}. Check the ticker or switch to offline mode.")

    # --- The rest of the prediction
    with st.form("commit_form"):
        direction = st.radio("Direction", config.DIRECTIONS, horizontal=True,
                             format_func=lambda value: "📈 UP" if value == "UP" else "📉 DOWN")
        target = st.number_input("Target price", min_value=0.0, value=None, step=0.01, format="%.2f",
                                 help="UP is correct if the price at the deadline is ≥ target. "
                                      "DOWN is correct if it is ≤ target.")

        deadline_mode = st.radio("Deadline", ["In a few minutes (live demo)", "Specific date and time"],
                                 horizontal=True)
        minutes_from_now = st.number_input("Minutes from now", min_value=1, max_value=600, value=5)
        deadline_date = st.date_input("Date", value=datetime.now(LOCAL_TZ).date() + timedelta(days=1))
        deadline_time = st.time_input("Time (local)", value=datetime.strptime("17:30", "%H:%M").time())
        st.caption("Only the field matching the chosen deadline type is used.")

        submitted = st.form_submit_button("🔒 Commit to the ledger", type="primary")

    if submitted:
        if deadline_mode.startswith("In a few minutes"):
            # Round up to the next full minute, so deadlines look clean (e.g. 15:42:00)
            deadline = datetime.now(timezone.utc) + timedelta(minutes=int(minutes_from_now))
            deadline = deadline.replace(second=0, microsecond=0) + timedelta(minutes=1)
        else:
            deadline = datetime.combine(deadline_date, deadline_time, tzinfo=LOCAL_TZ)

        try:
            result = services.create_commit(handle, ticker, direction, target, deadline)
            st.session_state["last_commit"] = result
        except services.ProofOfCallError as error:
            st.error(str(error))

    # --- Show the result of the last commit (stays visible after reruns)
    result = st.session_state.get("last_commit")
    if result:
        st.divider()
        st.success(f"Committed! Your call code is **#PoC-{result['code']}** "
                   f"(block #{result['block']['index']}).")

        st.markdown("**What the public ledger shows** (no one can tell what you predicted):")
        st.code(result["commit_hash"], language=None)

        st.markdown("**Your secret receipt.** Save it! You need it to reveal the call. "
                    "If you lose it, the call will expire and count as wrong.")
        st.code(result["receipt"], language="json")
        st.download_button("⬇️ Download receipt", data=result["receipt"],
                           file_name=f"proofofcall_{result['code']}.json", mime="application/json")

        receipt = json.loads(result["receipt"])
        arrow = "📈" if receipt["direction"] == "UP" else "📉"
        st.markdown("**Suggested social post:**")
        st.code(f"{arrow} My call: {receipt['ticker']} {receipt['direction']} to {receipt['target']} "
                f"by {show_time(receipt['deadline'])}\n"
                f"Verified on ProofOfCall · #PoC-{result['code']}", language=None)


# ===========================================================================
# Page: Reveal a call
# ===========================================================================

def do_reveal(code, ticker, direction, target, nonce):
    """Run the reveal and show the outcome."""
    try:
        with st.spinner("Checking the hash and fetching the market price..."):
            outcome = services.reveal_commit(code, ticker, direction, target, nonce, use_live_data)
    except services.ProofOfCallError as error:
        st.error(str(error))
        return

    move = (outcome["price_at_deadline"] / outcome["price_at_commit"] - 1) if outcome["price_at_commit"] else 0
    st.markdown(
        f"Hash verified ✅  ·  **{outcome['ticker']}** went from **{outcome['price_at_commit']:,.2f}** "
        f"to **{outcome['price_at_deadline']:,.2f}** ({move:+.2%})  ·  target was {float(target):,.2f}"
    )
    st.caption(f"Price source: {outcome['source']}  ·  result saved in block #{outcome['block']['index']}")

    if outcome["correct"]:
        st.success("🎯 CORRECT call! Added to your verified track record.")
        st.balloons()
    else:
        st.error("❌ WRONG call. It stays on your track record forever, that's the point.")


def page_reveal():
    st.title("🔓 Reveal a call")
    st.write(f"After the deadline you have **{config.REVEAL_WINDOW_MINUTES} minutes** to reveal. "
             "The app recomputes the hash: if anything was changed, the reveal is rejected.")

    # Calls that can be revealed right now
    awaiting = [call for call in services.get_calls(chain) if call["status"] == services.STATUS_AWAITING]
    if awaiting:
        st.markdown("**Calls waiting for a reveal right now:**")
        for call in awaiting:
            st.write(f"⏰ #PoC-{call['code']} by {call['handle']} · reveal before {show_time(call['reveal_until'])}")

    tab_receipt, tab_manual = st.tabs(["📋 Paste receipt", "✍️ Enter manually"])

    with tab_receipt:
        receipt_text = st.text_area("Paste the receipt you saved when committing", height=220)
        if st.button("🔓 Reveal from receipt", type="primary"):
            try:
                receipt = commitments.read_receipt(receipt_text)
                do_reveal(receipt["commit_code"], receipt["ticker"], receipt["direction"],
                          float(receipt["target"]), receipt["nonce"])
            except ValueError as error:
                st.error(str(error))

    with tab_manual:
        with st.form("manual_reveal_form"):
            code = st.text_input("Call code", placeholder="#PoC-1a2b3c4d")
            ticker = st.text_input("Ticker")
            direction = st.radio("Direction", config.DIRECTIONS, horizontal=True)
            target = st.number_input("Target price", min_value=0.0, value=None, step=0.01, format="%.2f")
            nonce = st.text_input("Nonce (secret)")
            submitted = st.form_submit_button("🔓 Reveal", type="primary")

        if submitted:
            if not (code and ticker and target and nonce):
                st.error("Please fill in all the fields.")
            else:
                do_reveal(code, ticker, direction, target, nonce)


# ===========================================================================
# Page: Leaderboard
# ===========================================================================

def page_leaderboard():
    st.title("🏆 Leaderboard")
    st.write("Verified hit rates. **Expired calls count as wrong**, so deleting losers doesn't help.")

    table = services.compute_leaderboard(chain)
    if table.empty:
        st.info("No influencers yet.")
        return

    # What followers would believe if they only saw the revealed (posted) calls
    revealed = table["Correct"] + table["Wrong"]
    table["What their feed shows"] = (table["Correct"] / revealed).where(revealed > 0)
    table["Verified"] = table["Verified"].map({True: "✅", False: ""})

    columns = ["Influencer", "Verified", "Platform", "Hit rate", "What their feed shows",
               "Resolved calls", "Correct", "Wrong", "Expired", "Open"]

    st.dataframe(
        table[columns],
        hide_index=True,
        width="stretch",
        column_config={
            "Hit rate": st.column_config.ProgressColumn(
                "Verified hit rate", format="percent", min_value=0, max_value=1),
            "What their feed shows": st.column_config.NumberColumn(
                "Hit rate on revealed calls only", format="percent",
                help="What followers would see if expired (hidden) calls were ignored."),
        },
    )
    st.caption(f"Influencers with fewer than {config.MIN_CALLS_FOR_RANKING} resolved calls are listed at the bottom.")

    st.markdown("#### Feed vs reality")
    chart_data = table.set_index("Influencer")[["What their feed shows", "Hit rate"]].rename(
        columns={"What their feed shows": "Revealed calls only", "Hit rate": "Verified (expired = wrong)"})
    st.bar_chart(chart_data * 100, stack=False, y_label="Hit rate (%)")


# ===========================================================================
# Page: Influencer profile
# ===========================================================================

def page_profile():
    st.title("📊 Influencer profile")

    handle = influencer_selector("Influencer", key="profile_handle")
    if handle is None:
        return

    profile = services.get_influencers(chain)[handle]
    calls = [call for call in services.get_calls(chain) if call["handle"] == handle]
    stats = services.compute_stats(calls)
    verified = services.is_verified(chain, handle)

    st.subheader(f"{profile['display_name']}  ·  {handle}  {'✅ Verified' if verified else ''}")
    st.caption(f"{profile['platform']} · on ProofOfCall since {show_time(profile['registered_at'])}")

    metric_1, metric_2, metric_3, metric_4 = st.columns(4)
    metric_1.metric("Verified hit rate", show_percent(stats["hit_rate"]))
    metric_2.metric("Resolved calls", stats["resolved"])
    metric_3.metric("Expired (hidden losers)", stats["expired"])
    metric_4.metric("Open calls", stats["open"])

    # --- Hit rate over time
    resolved_calls = [call for call in calls if call["status"] in
                      (services.STATUS_CORRECT, services.STATUS_WRONG, services.STATUS_EXPIRED)]
    if resolved_calls:
        resolved_calls = sorted(resolved_calls, key=lambda call: call["deadline"])
        history = pd.DataFrame({
            "Deadline": [commitments.parse_deadline(call["deadline"]) for call in resolved_calls],
            "Correct": [call["status"] == services.STATUS_CORRECT for call in resolved_calls],
        })
        history["Cumulative hit rate (%)"] = history["Correct"].expanding().mean() * 100
        st.markdown("#### Track record over time")
        st.line_chart(history.set_index("Deadline")["Cumulative hit rate (%)"])

    # --- All calls
    st.markdown("#### All calls")
    table = calls_to_table(calls)
    if not table.empty:
        table["Status"] = table["Status"].map(lambda status: f"{STATUS_ICONS.get(status, '')} {status}")
    st.dataframe(table, hide_index=True, width="stretch")

    # --- Verified subscription (business model)
    st.divider()
    st.markdown("#### ✅ Verified badge")
    if verified:
        st.success("Active subscription. Paste this badge in your bio:")
        st.code(services.badge_text(chain, handle), language=None)
    else:
        st.write(f"Get the **Verified** badge for your bio: €{config.VERIFIED_PRICE_EUR_PER_MONTH}/month. "
                 "Show your followers a track record nobody can fake.")
        if st.button(f"Subscribe for €{config.VERIFIED_PRICE_EUR_PER_MONTH} (simulated payment)", type="primary"):
            services.subscribe_verified(handle)
            st.success("Subscription active! The badge is now on your profile.")
            st.rerun()


# ===========================================================================
# Page: Ledger explorer
# ===========================================================================

def page_ledger():
    st.title("⛓️ Ledger explorer")
    st.write("Every action is a block. Each block contains the hash of the previous one, "
             "so changing history breaks the chain.")

    is_intact, message = ledger.verify_chain(chain)
    if is_intact:
        st.success(message)
    else:
        st.error(message)

    # --- Tampering demo
    st.markdown("#### 🕵️ Try to cheat")
    st.write("Simulate a dishonest edit: turn an old WRONG call into a CORRECT one "
             "(done on a copy, the real ledger is not touched).")
    if st.button("Tamper with a block"):
        block_index, (still_valid, verdict) = ledger.simulate_tampering(chain)
        if block_index is None:
            st.info(verdict)
        elif still_valid:
            st.warning(verdict)
        else:
            st.error(f"Edited block #{block_index} → detected immediately: {verdict}")

    # --- Verify a commitment by hand (anyone can do it)
    st.markdown("#### 🔍 Verify a hash yourself")
    st.write("You don't have to trust us: recompute any revealed call's hash.")
    with st.form("hash_checker"):
        column_1, column_2, column_3 = st.columns(3)
        handle = column_1.text_input("Handle", placeholder="@valuevera")
        ticker = column_2.text_input("Ticker", placeholder="BTC-USD")
        direction = column_3.selectbox("Direction", config.DIRECTIONS)
        column_4, column_5, column_6 = st.columns(3)
        target = column_4.number_input("Target", min_value=0.0, value=None, step=0.01, format="%.2f")
        deadline_text = column_5.text_input("Deadline (UTC, as on the ledger)", placeholder="2026-11-23T16:30:00Z")
        nonce = column_6.text_input("Nonce")
        submitted = st.form_submit_button("Compute SHA-256")

    if submitted:
        if not (handle and ticker and target and deadline_text and nonce):
            st.error("Please fill in all the fields.")
        else:
            message_text = commitments.build_message(handle, ticker, direction, target, deadline_text.strip(), nonce.strip())
            computed = commitments.compute_commitment(handle, ticker, direction, target, deadline_text.strip(), nonce.strip())
            st.write("Hashed text:")
            st.code(message_text, language=None)
            st.write("SHA-256:")
            st.code(computed, language=None)
            known_hashes = {call["commit_hash"] for call in services.get_calls(chain)}
            if computed in known_hashes:
                st.success(f"✅ This matches commit #PoC-{commitments.short_code(computed)} on the ledger.")
            else:
                st.warning("This hash is not on the ledger.")

    # --- The blocks
    st.markdown("#### Blocks (newest first)")
    block_types = sorted({block["type"] for block in chain})
    chosen_types = st.multiselect("Show block types", block_types, default=block_types)

    rows = []
    for block in reversed(chain):
        if block["type"] in chosen_types:
            rows.append({
                "#": block["index"],
                "Time": show_time(block["timestamp"]),
                "Type": block["type"],
                "Who": block["data"].get("handle", ""),
                "Hash": block["hash"][:16] + "…",
                "Previous hash": block["prev_hash"][:16] + "…",
            })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    block_number = st.number_input("Inspect block #", min_value=0, max_value=len(chain) - 1, value=len(chain) - 1)
    st.json(chain[int(block_number)])


# ===========================================================================
# Page: API for brokers
# ===========================================================================

def page_api():
    st.title("🔌 API for brokers and platforms")
    st.write("Brokers, apps and social platforms can query ProofOfCall to show (or promote) "
             "only creators with a verified track record. Below is a preview of the API response.")

    column_1, column_2, column_3 = st.columns(3)
    only_verified = column_1.checkbox("Only Verified creators", value=True)
    minimum_hit_rate = column_2.slider("Minimum hit rate (%)", 0, 100, 50)
    minimum_calls = column_3.number_input("Minimum resolved calls", min_value=0, value=config.MIN_CALLS_FOR_RANKING)

    table = services.compute_leaderboard(chain)
    creators = []
    for _, row in table.iterrows():
        if only_verified and not row["Verified"]:
            continue
        if row["Resolved calls"] < minimum_calls:
            continue
        if pd.isna(row["Hit rate"]) or row["Hit rate"] * 100 < minimum_hit_rate:
            continue
        creators.append({
            "handle": row["Influencer"],
            "platform": row["Platform"],
            "verified": bool(row["Verified"]),
            "hit_rate": round(float(row["Hit rate"]), 3),
            "resolved_calls": int(row["Resolved calls"]),
            "expired_calls": int(row["Expired"]),
        })

    response = {
        "endpoint": "GET /v1/creators",
        "generated_at": commitments.format_deadline(datetime.now(timezone.utc)),
        "ledger_height": len(chain),
        "ledger_head_hash": chain[-1]["hash"],
        "count": len(creators),
        "creators": creators,
    }

    st.code(f"GET /v1/creators?verified={str(only_verified).lower()}"
            f"&min_hit_rate={minimum_hit_rate / 100:.2f}&min_calls={minimum_calls}", language=None)
    st.json(response)
    st.download_button("⬇️ Download JSON", data=json.dumps(response, indent=2),
                       file_name="proofofcall_creators.json", mime="application/json")

    st.markdown("#### Pricing (B2B)")
    st.table(pd.DataFrame({
        "Plan": ["Starter", "Growth", "Enterprise"],
        "Requests / month": ["10,000", "250,000", "Unlimited"],
        "Price": ["€99 / month", "€499 / month", "Custom"],
    }))


# ===========================================================================
# Router: show the page chosen in the sidebar
# ===========================================================================

PAGE_FUNCTIONS = {
    "🏠 Home": page_home,
    "👤 Register": page_register,
    "🔒 Commit a call": page_commit,
    "🔓 Reveal a call": page_reveal,
    "🏆 Leaderboard": page_leaderboard,
    "📊 Influencer profile": page_profile,
    "⛓️ Ledger explorer": page_ledger,
    "🔌 API for brokers": page_api,
}

PAGE_FUNCTIONS[page]()
