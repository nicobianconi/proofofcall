# ProofOfCall – verified track records for finfluencers

Financial influencers can delete their wrong calls and repost only the winners.
ProofOfCall makes every call permanent: the influencer **commits** a hash of the
prediction before posting it, **reveals** it after the deadline, and the app
scores it against the real market price. Calls that are not revealed in time,
or that are invalid, **count as wrong**, so losers cannot be hidden.

Live app: https://proofofcall.streamlit.app

## How to run on your computer

```bash
pip install -r requirements.txt
streamlit run app.py
```

(On a Mac with Python from python.org: `python3.14 -m pip install -r requirements.txt`
and `python3.14 -m streamlit run app.py`.)

The app opens in the browser at http://localhost:8501.
On the first launch, the ledger database (`ledger.db`) is filled with demo data
(4 fictional influencers).

## Files

| File | What it does |
|---|---|
| `app.py` | Streamlit interface (all the pages) |
| `services.py` | Business logic: register, commit, reveal, expire, verified plans, leaderboard, confidence intervals |
| `commitments.py` | Commit-reveal cryptography: `sha256(handle\|ticker\|direction\|target\|deadline\|nonce)` |
| `ledger.py` | Append-only, hash-chained ledger stored in SQLite (`ledger.db`), plus integrity check |
| `prices.py` | Market prices: live from Yahoo Finance (yfinance), or a simulated offline market |
| `config.py` | All the settings (rules, plans, tickers...) |
| `seed_data.py` | Script that regenerates the demo history (`seed_ledger.json`) |
| `seed_ledger.json` | Demo history, loaded into the database on the first launch |

## Scoring rule

- **UP** is a hit if the price at the deadline is ≥ target; **DOWN** if it is ≤ target.
- **Standard calls** settle at the **close of the deadline day** (last price before 22:00 Italian
  time, i.e. after the US close). The target must be **at least 2% away** from the price at commit
  time, in the predicted direction. 24 hours to reveal.
- **Live demo calls** use the same logic shrunk to minutes (target ≥ 0.1% away, 15 minutes to reveal),
  so the product can be demonstrated in class.
- **Unrevealed or invalid calls count as wrong.** The 2% rule is checked at commit time and again at
  reveal time with the official price at commit time.
- A hit rate is shown only from **20 resolved calls**, with a **95% confidence interval** (Wilson).

## Admin password (Demo tools)

The "Reset demo data" button is protected by a password that is **not** in the code
(the repository is public). It is read from Streamlit secrets as `ADMIN_PASSWORD`:

- **Streamlit Cloud:** app menu → Settings → Secrets → add the line
  `ADMIN_PASSWORD = "your-password"` and save.
- **On your computer:** create the file `.streamlit/secrets.toml` in the project folder with the same
  line. Never upload this file to GitHub.

Without a password, the Demo tools are disabled.

## Live demo tips

- Use **BTC-USD** or other crypto with a **Live demo** call: it trades 24/7, so 10-minute deadlines
  resolve during class.
- If there is no internet, switch off **Live prices** in the sidebar to use the simulated market.
- Before presenting: open the app 10 minutes earlier (it sleeps when unused) and use
  **Demo tools → Reset demo data** to remove test calls.

## Limitations (and roadmap)

- The ledger is a simulated blockchain on one server. Next step: anchor block hashes on a
  public chain (e.g. Ethereum/Polygon) so not even the operator can rewrite history.
- No user authentication: in production each influencer would sign commits with their own key.
- On Streamlit Cloud the database resets when the app restarts. Production: PostgreSQL.
- The demo history and offline mode use **simulated prices**, not real market data.
- Payments for the Verified plans are simulated. The broker API is shown as a preview (FastAPI in production).
- ProofOfCall is not investment advice.
