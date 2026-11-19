"""
app.py
------
ProofOfCall - verified track records for finfluencers.
The Streamlit interface. Start it with:

    streamlit run app.py

The app is organised in pages (chosen from the sidebar). Each page is one
function below. All the real work is done in services.py.
"""

import hmac
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

st.set_page_config(page_title=config.APP_NAME, page_icon="✅", layout="wide")


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


def show_interval(low, high) -> str:
    if low is None or pd.isna(low):
        return "–"
    return f"{low:.0%} – {high:.0%}"


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


STATUS_ICONS = {
    services.STATUS_CORRECT: "✅",
    services.STATUS_WRONG: "❌",
    services.STATUS_EXPIRED: "⌛",
    services.STATUS_INVALID: "🚫",
    services.STATUS_PENDING: "🔒",
    services.STATUS_AWAITING: "⏰",
}


def calls_to_table(calls: list) -> pd.DataFrame:
    """Turn a list of calls into a readable table. Hidden fields show as 🔒."""
    rows = []
    for call in calls:
        hidden = call["ticker"] is None
        rows.append({
            "Code": config.CODE_PREFIX + call["code"],
            "Influencer": call["handle"],
            "Type": "Demo" if call["call_type"] == "demo" else "Standard",
            "Committed": show_time(call["committed_at"]),
            "Deadline": show_time(call["deadline"]),
            "Ticker": "🔒" if hidden else call["ticker"],
            "Direction": "🔒" if hidden else ("📈 UP" if call["direction"] == "UP" else "📉 DOWN"),
            "Target": "🔒" if hidden else call["target"],
            "Price at commit": call["price_at_commit"],
            "Price at deadline": call["price_at_deadline"],
            "Status": f"{STATUS_ICONS.get(call['status'], '')} {call['status']}",
        })
    return pd.DataFrame(rows)


def read_admin_password():
    """The admin password from Streamlit secrets, or None if it was never set."""
    try:
        return st.secrets.get(config.ADMIN_PASSWORD_SECRET_NAME)
    except Exception:  # no secrets file at all
        return None


# ===========================================================================
# Sidebar: navigation, price source, password-protected demo tools
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
    st.title(f"✅ {config.APP_NAME}")
    st.caption(config.APP_TAGLINE)

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
    with st.expander("🔐 Demo tools (admin)"):
        admin_password = read_admin_password()

        if not admin_password:
            st.caption(f"Disabled: no admin password set. Add `{config.ADMIN_PASSWORD_SECRET_NAME}` "
                       "to the Streamlit secrets to enable these tools.")
        elif st.session_state.get("is_admin"):
            st.success("Admin mode")
            st.write("Restore the demo influencers and their history. "
                     "**All calls made since the last reset will be deleted.**")
            if st.button("Reset demo data", type="primary"):
                ledger.reset_to_seed()
                st.cache_data.clear()
                st.toast("Demo data restored.")
                st.rerun()
            if st.button("Log out"):
                st.session_state["is_admin"] = False
                st.rerun()
        else:
            typed_password = st.text_input("Admin password", type="password")
            if st.button("Unlock"):
                # compare_digest: a safe way to compare passwords
                if hmac.compare_digest(typed_password.encode(), str(admin_password).encode()):
                    st.session_state["is_admin"] = True
                    st.rerun()
                else:
                    st.error("Wrong password.")

    st.divider()
    st.caption("⚠️ " + config.DISCLAIMER)


# ANTI-CHEATING RULE: every time anyone opens the app, overdue calls expire
expired_now = services.expire_overdue_commits()
if expired_now:
    st.toast(f"⌛ {expired_now} call(s) were not revealed in time and now count as wrong.")

chain = ledger.load_chain()


# ===========================================================================
# Page: Home
# ===========================================================================

def page_home():
    st.title(config.APP_NAME)
    st.subheader("Verified track records for financial influencers")

    st.write(
        "Finfluencers on TikTok, YouTube and Telegram can delete their wrong stock and crypto "
        "calls and repost only the winners. Their followers never see the real hit rate. "
        f"**{config.APP_NAME} makes every call permanent and verifiable.**"
    )

    column_1, column_2, column_3 = st.columns(3)
    with column_1:
        st.markdown("#### 1. 🔒 Commit")
        st.write("Before posting a tip, the influencer publishes a **hash** of the prediction. "
                 "Nobody can read it, and nobody can change it.")
    with column_2:
        st.markdown("#### 2. 🔓 Reveal")
        st.write("After the deadline, the influencer reveals the prediction. The app checks the hash "
                 "and fetches the **real market price**.")
    with column_3:
        st.markdown("#### 3. 🏆 Track record")
        st.write("Every result is scored automatically. Calls that are **not revealed** in time, "
                 "or that are **invalid**, count as wrong.")

    with st.expander("📏 The scoring rule"):
        standard = config.CALL_TYPES["standard"]
        demo = config.CALL_TYPES["demo"]
        st.markdown(f"""
- **UP** is a hit if the price at the deadline is **at or above** the target; **DOWN** if it is **at or below**.
- **Standard calls** settle at the **close of the deadline day** (last price before {config.DAILY_CLOSE_TIME} Italian time).
  The target must be at least **{standard['min_target_distance']:.0%} away** from the price at commit time.
  The influencer has **{standard['reveal_window_minutes'] // 60} hours** to reveal.
- **Live demo calls** use the same logic in minutes: target at least {demo['min_target_distance']:.1%} away,
  {demo['reveal_window_minutes']} minutes to reveal.
- **Unrevealed or invalid calls count as wrong.**
- A hit rate is shown only from **{config.MIN_CALLS_FOR_HIT_RATE} resolved calls**, with a 95% confidence interval.
""")

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
            st.success(f"Welcome {block['data']['handle']}! Your profile is on the ledger (block #{block['index']}). "
                       "Now go to **🔒 Commit a call**.")
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

    # --- Type of call
    call_type = st.radio("Type of call", list(config.CALL_TYPES.keys()), horizontal=True,
                         format_func=lambda key: config.CALL_TYPES[key]["label"])
    rules = config.CALL_TYPES[call_type]

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
            minimum = rules["min_target_distance"]
            st.info(
                f"Current price of **{ticker}**: **{price_now:,.2f}**  ·  source: {source}\n\n"
                f"Target rule ({minimum:.1%} minimum): UP needs **≥ {price_now * (1 + minimum):,.2f}**, "
                f"DOWN needs **≤ {price_now * (1 - minimum):,.2f}**"
            )
        else:
            st.warning(f"Could not fetch the current price of {ticker}. Check the ticker or switch to offline mode.")

    # --- The rest of the prediction
    with st.form("commit_form"):
        direction = st.radio("Direction", config.DIRECTIONS, horizontal=True,
                             format_func=lambda value: "📈 UP" if value == "UP" else "📉 DOWN")
        target = st.number_input("Target price", min_value=0.0, value=None, step=0.01, format="%.2f",
                                 help="UP is correct if the price at the deadline is ≥ target. "
                                      "DOWN is correct if it is ≤ target.")

        if call_type == "demo":
            minutes_from_now = st.number_input("Deadline: minutes from now", min_value=1, max_value=600, value=10)
            st.caption(f"You will have {rules['reveal_window_minutes']} minutes after the deadline to reveal.")
        else:
            deadline_day = st.date_input("Deadline day",
                                         value=datetime.now(LOCAL_TZ).date() + timedelta(days=1),
                                         min_value=datetime.now(LOCAL_TZ).date())
            st.caption(f"The call settles at the close of that day ({config.DAILY_CLOSE_TIME} Italian time). "
                       f"You will have {rules['reveal_window_minutes'] // 60} hours to reveal.")

        submitted = st.form_submit_button("🔒 Commit to the ledger", type="primary")

    if submitted:
        if call_type == "demo":
            # Round up to the next full minute, so deadlines look clean (e.g. 15:42:00)
            deadline = datetime.now(timezone.utc) + timedelta(minutes=int(minutes_from_now))
            deadline = deadline.replace(second=0, microsecond=0) + timedelta(minutes=1)
        else:
            deadline = services.daily_close_deadline(deadline_day)

        try:
            with st.spinner("Checking the target and writing to the ledger..."):
                result = services.create_commit(handle, ticker, direction, target, deadline,
                                                call_type=call_type, use_live_data=use_live_data)
            st.session_state["last_commit"] = result
        except services.ProofOfCallError as error:
            st.error(str(error))

    # --- Show the result of the last commit (stays visible after reruns)
    result = st.session_state.get("last_commit")
    if result:
        st.divider()
        st.success(f"Committed! Your call code is **{config.CODE_PREFIX}{result['code']}** "
                   f"(block #{result['block']['index']}).")

        st.markdown("**What the public ledger shows** (no one can tell what you predicted):")
        st.code(result["commit_hash"], language=None)

        st.markdown("**Your secret receipt.** Save it (copy icon at the top right of the box)! "
                    "You need it to reveal the call. If you lose it, the call will expire and count as wrong.")
        st.code(result["receipt"], language="json")
        st.download_button("⬇️ Download receipt", data=result["receipt"],
                           file_name=f"proofofcall_{result['code']}.json", mime="application/json")

        receipt = json.loads(result["receipt"])
        arrow = "📈" if receipt["direction"] == "UP" else "📉"
        st.markdown("**Suggested social post:**")
        st.code(f"{arrow} My call: {receipt['ticker']} {receipt['direction']} to {receipt['target']} "
                f"by {show_time(receipt['deadline'])}\n"
                f"Verified on {config.APP_NAME} · {config.CODE_PREFIX}{result['code']}", language=None)


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

    if not outcome["valid"]:
        st.error("🚫 INVALID call: the target was too close to the price at commit time. It counts as wrong.")
    elif outcome["correct"]:
        st.success("🎯 CORRECT call! Added to your verified track record.")
        st.balloons()
    else:
        st.error("❌ WRONG call. It stays on your track record forever, that's the point.")


def page_reveal():
    st.title("🔓 Reveal a call")
    st.write("After the deadline, reveal your prediction within the reveal window. "
             "The app recomputes the hash: if anything was changed, the reveal is rejected.")

    # Calls that can be revealed right now
    awaiting = [call for call in services.get_calls(chain) if call["status"] == services.STATUS_AWAITING]
    if awaiting:
        st.markdown("**Calls waiting for a reveal right now:**")
        for call in awaiting:
            st.write(f"⏰ {config.CODE_PREFIX}{call['code']} by {call['handle']} · "
                     f"reveal before {show_time(call['reveal_until'])}")

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
            code = st.text_input("Call code", placeholder=f"{config.CODE_PREFIX}1a2b3c4d")
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
    st.write(f"Verified hit rates. **Expired and invalid calls count as wrong**, so deleting losers "
             f"doesn't help. A hit rate is shown only from **{config.MIN_CALLS_FOR_HIT_RATE} resolved calls**.")

    table = services.compute_leaderboard(chain)
    if table.empty:
        st.info("No influencers yet.")
        return

    display = pd.DataFrame({
        "Influencer": table["Influencer"],
        "Verified": table["Verified"].map({True: "✅", False: ""}),
        "Platform": table["Platform"],
        "Hit rate": table["Hit rate"].where(table["Track record"]),
        "95% confidence interval": [
            show_interval(low, high) if has_record else "–"
            for low, high, has_record in zip(table["CI low"], table["CI high"], table["Track record"])
        ],
        "Resolved calls": [
            str(count) if has_record else f"{count}/{config.MIN_CALLS_FOR_HIT_RATE} (building)"
            for count, has_record in zip(table["Resolved calls"], table["Track record"])
        ],
        "Correct": table["Correct"],
        "Wrong": table["Wrong"],
        "Expired": table["Expired"],
        "Invalid": table["Invalid"],
        "Open": table["Open"],
    })

    st.dataframe(
        display,
        hide_index=True,
        width="stretch",
        column_config={
            "Hit rate": st.column_config.ProgressColumn(
                "Verified hit rate", format="percent", min_value=0, max_value=1),
        },
    )

    # --- The key insight of the pitch: what followers see vs reality
    st.markdown("#### Feed vs reality")
    st.write("Left bar: the hit rate followers would see if hidden (expired) calls were ignored. "
             "Right bar: the verified hit rate.")
    ranked = table[table["Track record"]]
    if ranked.empty:
        st.caption("No influencer has enough calls yet.")
    else:
        chart_data = ranked.set_index("Influencer")[["Feed hit rate", "Hit rate"]].rename(
            columns={"Feed hit rate": "Revealed calls only", "Hit rate": "Verified (expired = wrong)"})
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
    plan = services.active_plan(chain, handle)

    st.subheader(f"{profile['display_name']}  ·  {handle}  {'✅ Verified ' + plan if plan else ''}")
    st.caption(f"{profile['platform']} · on {config.APP_NAME} since {show_time(profile['registered_at'])}")

    metric_1, metric_2, metric_3, metric_4 = st.columns(4)
    if stats["has_track_record"]:
        metric_1.metric("Verified hit rate", show_percent(stats["hit_rate"]),
                        help="95% confidence interval: " + show_interval(stats["ci_low"], stats["ci_high"]))
    else:
        metric_1.metric("Verified hit rate", "Building…",
                        help=f"Shown after {config.MIN_CALLS_FOR_HIT_RATE} resolved calls.")
    metric_2.metric("Resolved calls", f"{stats['resolved']}/{config.MIN_CALLS_FOR_HIT_RATE}"
                    if not stats["has_track_record"] else stats["resolved"])
    metric_3.metric("Expired or invalid", stats["expired"] + stats["invalid"])
    metric_4.metric("Open calls", stats["open"])

    if stats["has_track_record"]:
        st.caption(f"95% confidence interval of the hit rate: **{show_interval(stats['ci_low'], stats['ci_high'])}**")
    else:
        st.info(f"Track record in progress: {stats['resolved']} of {config.MIN_CALLS_FOR_HIT_RATE} calls. "
                "With few calls, a high hit rate can be pure luck.")

    # --- Hit rate over time
    resolved_calls = [call for call in calls if call["status"] in services.RESOLVED_STATUSES]
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
    st.dataframe(calls_to_table(calls), hide_index=True, width="stretch")

    # --- Verified subscription (business model)
    st.divider()
    st.markdown("#### ✅ Verified badge")
    if plan:
        st.success(f"Active plan: **Verified {plan}**. Paste this badge in your bio:")
        st.code(services.badge_text(chain, handle), language=None)
    else:
        st.write("Show your followers a track record nobody can fake. Plans: **Free** (public profile), "
                 + ", ".join(f"**{name}** €{price:.0f}/month" for name, price in config.VERIFIED_PLANS.items())
                 + ".")
        chosen_plan = st.radio("Plan", list(config.VERIFIED_PLANS.keys()), horizontal=True,
                               format_func=lambda name: f"{name} · €{config.VERIFIED_PLANS[name]:.0f}/month")
        if st.button(f"Subscribe to {chosen_plan} (simulated payment)", type="primary"):
            services.subscribe_verified(handle, chosen_plan)
            st.success("Subscription active! The badge is now on your profile.")
            st.rerun()


# ===========================================================================
# Visual tampering demo (used by the Ledger explorer page)
# ===========================================================================

GREEN = "#2e7d32"
RED = "#c62828"
ORANGE = "#ef6c00"
GREY = "#616161"


def block_box_html(block: dict, colour: str, note: str) -> str:
    """One block of the chain drawn as a coloured box."""
    return f"""
    <div style="border: 3px solid {colour}; border-radius: 10px; padding: 10px 12px;
                min-width: 135px; background: rgba(255,255,255,0.03); font-size: 0.85rem;">
        <div style="font-weight: 700; font-size: 1rem;">#{block['index']} · {block['type']}</div>
        <div style="font-family: monospace; margin-top: 4px;">prev: {block['prev_hash'][:8]}…</div>
        <div style="font-family: monospace;">hash: {block['hash'][:8]}…</div>
        <div style="margin-top: 6px; color: {colour}; font-weight: 700;">{note}</div>
    </div>"""


def link_html(colour: str, label: str) -> str:
    """The arrow between two blocks."""
    return f"""
    <div style="display: flex; flex-direction: column; align-items: center; justify-content: center;
                color: {colour}; font-weight: 700; min-width: 60px; font-size: 0.75rem;">
        <div style="font-size: 1.8rem; line-height: 1;">⟶</div>
        <div>{label}</div>
    </div>"""


def chain_strip_html(blocks: list, block_styles: list, link_styles: list) -> str:
    """
    A row of blocks joined by arrows.
    block_styles[i] = (colour, note) for blocks[i]
    link_styles[i]  = (colour, label) for the arrow BEFORE blocks[i + 1]
    """
    parts = []
    for position, block in enumerate(blocks):
        if position > 0:
            parts.append(link_html(*link_styles[position - 1]))
        parts.append(block_box_html(block, *block_styles[position]))
    return ('<div style="display: flex; align-items: stretch; gap: 6px; overflow-x: auto; '
            'padding: 6px 0 12px 0;">' + "".join(parts) + "</div>")


def show_tampering_demo(chain: list):
    """Draw the two attacks of ledger.simulate_tampering_step_by_step()."""
    demo = ledger.simulate_tampering_step_by_step(chain) or ledger.simulate_tampering_step_by_step(chain[:-1])
    if demo is None:
        st.info("There is no wrong call to tamper with yet. Reveal a wrong call first.")
        return

    position = demo["position"]
    original = demo["original_block"]
    tampered = demo["tampered_block"]
    next_block = demo["next_block"]
    previous_block = chain[position - 1]
    after_next = None  # 3 blocks fit on any screen

    # --- Step 0: the honest chain --------------------------------------------
    st.markdown("**Step 0 · The honest ledger.** Each block stores the hash of the block before it.")
    blocks = [previous_block, original, next_block] + ([after_next] if after_next else [])
    st.markdown(chain_strip_html(
        blocks,
        [(GREEN, "✓ intact")] * len(blocks),
        [(GREEN, "linked")] * (len(blocks) - 1),
    ), unsafe_allow_html=True)

    # --- Step 1: change the result -------------------------------------------
    st.markdown(f"**Step 1 · The cheat.** In block #{position}, a WRONG call by "
                f"{original['data']['handle']} is changed to CORRECT.")

    fields = ["handle", "ticker", "direction", "target", "price_at_deadline", "correct"]
    rows = ""
    for field in fields:
        before = original["data"].get(field)
        after = tampered["data"].get(field)
        changed = before != after
        style = f"background: {RED}; color: white; font-weight: 700;" if changed else ""
        rows += (f"<tr style='{style}'><td style='padding:4px 10px'>{field}</td>"
                 f"<td style='padding:4px 10px'>{before}</td><td style='padding:4px 10px'>{after}</td></tr>")
    st.markdown(
        "<table style='border-collapse: collapse; font-family: monospace; font-size: 0.9rem;'>"
        "<tr><th style='padding:4px 10px; text-align:left'>field</th>"
        "<th style='padding:4px 10px; text-align:left'>original</th>"
        "<th style='padding:4px 10px; text-align:left'>tampered</th></tr>"
        f"{rows}</table>", unsafe_allow_html=True)

    st.markdown("&nbsp;", unsafe_allow_html=True)
    column_1, column_2 = st.columns(2)
    column_1.markdown("Hash **stored** in the block")
    column_1.code(demo["stored_hash"], language=None)
    column_2.markdown("Hash **recomputed** from the edited content")
    column_2.code(demo["recomputed_hash"], language=None)
    st.error("❌ The two hashes are different: the edit is detected. " + demo["attack_1_result"][1])

    st.markdown(chain_strip_html(
        blocks,
        [(GREEN, "✓ intact"), (RED, "✗ content ≠ hash"), (GREEN, "✓ intact")] + ([(GREEN, "✓ intact")] if after_next else []),
        [(GREEN, "linked"), (GREEN, "linked")] + ([(GREEN, "linked")] if after_next else []),
    ), unsafe_allow_html=True)

    # --- Step 2: the smarter cheater recomputes the hash ----------------------
    st.markdown(f"**Step 2 · A smarter cheat.** Recompute the hash of block #{position} so it looks valid again…")
    fixed_block = dict(tampered)
    fixed_block["hash"] = demo["recomputed_hash"]
    blocks_attack_2 = [previous_block, fixed_block, next_block] + ([after_next] if after_next else [])
    st.markdown(chain_strip_html(
        blocks_attack_2,
        [(GREEN, "✓ intact"), (ORANGE, "looks valid"), (GREY, "untrusted")] + ([(GREY, "untrusted")] if after_next else []),
        [(GREEN, "linked"), (RED, "✗ BROKEN")] + ([(GREY, "")] if after_next else []),
    ), unsafe_allow_html=True)
    st.error(f"❌ …but block #{position + 1} still points to the OLD hash "
             f"({next_block['prev_hash'][:8]}… ≠ {demo['recomputed_hash'][:8]}…). "
             "To hide the edit, the cheater would have to rewrite every later block, "
             "and anyone holding the latest hash would notice.")


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

    # --- Tampering demo (visual, step by step)
    st.markdown("#### 🕵️ Try to cheat")
    st.write("Simulate a dishonest edit: turn an old WRONG call into a CORRECT one. "
             "It is done on a copy: the real ledger is not touched.")

    column_1, column_2 = st.columns([2, 3])
    if column_1.button("Tamper with a block", type="primary"):
        st.session_state["show_tampering"] = True
    if st.session_state.get("show_tampering") and column_2.button("Hide"):
        st.session_state["show_tampering"] = False

    if st.session_state.get("show_tampering"):
        show_tampering_demo(chain)

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
        deadline_text = column_5.text_input("Deadline (UTC, as on the ledger)", placeholder="2026-11-23T21:00:00Z")
        nonce = column_6.text_input("Nonce")
        submitted = st.form_submit_button("Compute SHA-256")

    if submitted:
        if not (handle and ticker and target and deadline_text and nonce):
            st.error("Please fill in all the fields.")
        else:
            message_text = commitments.build_message(handle, ticker, direction, target,
                                                     deadline_text.strip(), nonce.strip())
            computed = commitments.compute_commitment(handle, ticker, direction, target,
                                                      deadline_text.strip(), nonce.strip())
            st.write("Hashed text:")
            st.code(message_text, language=None)
            st.write("SHA-256:")
            st.code(computed, language=None)
            known_hashes = {call["commit_hash"] for call in services.get_calls(chain)}
            if computed in known_hashes:
                st.success(f"✅ This matches commit {config.CODE_PREFIX}{commitments.short_code(computed)} on the ledger.")
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
    minimum_calls = column_3.number_input("Minimum resolved calls", min_value=config.MIN_CALLS_FOR_HIT_RATE,
                                          value=config.MIN_CALLS_FOR_HIT_RATE)

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
            "hit_rate_ci_95": [round(float(row["CI low"]), 3), round(float(row["CI high"]), 3)],
            "resolved_calls": int(row["Resolved calls"]),
            "expired_or_invalid_calls": int(row["Expired"] + row["Invalid"]),
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

    st.caption("Business model: flat platform fee plus metered overage per request (see the pitch deck).")


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
