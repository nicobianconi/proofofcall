# ProofOfCall – verified track records for finfluencers

Financial influencers can delete their wrong calls and repost only the winners.
ProofOfCall makes every call permanent: the influencer **commits** a hash of the
prediction before posting it, **reveals** it after the deadline, and the app
scores it against the real market price. A call that is not revealed in time
**counts as wrong**, so losers cannot be hidden.

## How to run

```bash
pip install -r requirements.txt
streamlit run app.py
```

The app opens in the browser at http://localhost:8501.
On the first launch, the ledger is filled with demo data (4 fictional influencers).

## Files

| File | What it does |
|---|---|
| `app.py` | Streamlit interface (all the pages) |
| `services.py` | Business logic: register, commit, reveal, expire, verified badge, leaderboard |
| `commitments.py` | Commit-reveal cryptography: `sha256(handle\|ticker\|direction\|target\|deadline\|nonce)` |
| `ledger.py` | Hash-chained, append-only ledger saved in `ledger.json`, plus integrity check |
| `prices.py` | Market prices: live from Yahoo Finance, or a simulated offline market |
| `config.py` | All the settings (reveal window, prices of the plans, tickers...) |
| `seed_data.py` | Script that regenerates the demo history (`seed_ledger.json`) |
| `seed_ledger.json` | Demo history, copied to `ledger.json` on the first launch |

## Rules

- **Commit:** only the hash, the handle and the deadline are public. Ticker, direction,
  target and nonce stay secret in the influencer's receipt.
- **Reveal:** allowed from the deadline until `REVEAL_WINDOW_MINUTES` later
  (15 minutes for the demo, set in `config.py`). The app recomputes the hash: any change is rejected.
- **Scoring:** UP is correct if the price at the deadline is ≥ target; DOWN is correct if it is ≤ target.
- **Anti-cheating:** a call not revealed within the window gets an EXPIRE block and counts as wrong.
- **Tamper evidence:** each block stores the hash of the previous one, and `verify_chain()` detects any edit.

## Live demo tips

- Use **BTC-USD** or other crypto: it trades 24/7, so 5-minute deadlines resolve during class.
- If there is no internet, switch off **Live prices** in the sidebar to use the simulated market.
- To let classmates commit from their phones, everyone must open the **same running app**:
  deploy it on Streamlit Community Cloud, or run it on one laptop and share its Network URL
  (same Wi-Fi).
- **Demo tools → Reset demo data** in the sidebar restores the initial history.

## Limitations (and roadmap)

- The ledger is a simulated blockchain on one server. Next step: anchor block hashes on a
  public chain (e.g. Ethereum/Polygon) so not even the operator can rewrite history.
- No user authentication: in production each influencer would sign commits with their own key.
- The demo history and offline mode use **simulated prices**, not real market data.
- Payments for the Verified plan are simulated.
