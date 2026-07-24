# ITAKA FUND — Single-Beneficiary Put-Selling Tracker — Build Handoff

Purpose: a **simpler** version of the existing put-selling dashboard for the
**Itaka Fund** — ONE beneficiary — with **cash flows (deposits +
withdrawals)** and **time-weighted return (TWR)**, and **no screeners**.
Wherever the app shows a fund name / page title, use "ITAKA FUND".

Give this file to a fresh Claude Code session working in the NEW repo. Follow
it top to bottom.

---

## 0. THE ONE IDEA THAT MATTERS (read first)

**NAV-per-unit IS time-weighted return.** Do NOT build a separate TWR
calculator. The unit accounting already gives TWR for free:

- Deposit of $D at NAV/unit U → issues `+D/U` units.
- Withdrawal of $W at NAV/unit U → redeems `−W/U` units.
- `net_contributed = Σ cash-flow amounts` (deposits +, withdrawals −).
- `NAV = net_contributed + realized_pnl + unrealized_pnl`.
- `NAV/unit = NAV / total_units`.

Because units move *proportionally* to each flow, NAV/unit is unaffected by
flow timing/size — it moves ONLY with performance. So **NAV/unit indexed to
100 = the TWR line.** That's the headline metric.

(Optional extra: a money-weighted return / IRR on the dated cash flows tells
the owner their actual dollar return given *when* they added money. Nice to
have for a single owner, but TWR is the ask.)

---

## ISOLATION (do this so the two apps can never affect each other)

This app MUST live in its **own directory, own git repo, own Supabase
project, own Streamlit app** — nothing shared with the original fund app.
- The code files below were **manually copied in by the owner** before this
  session started. This session works ONLY inside this directory. Do NOT
  reference, read, or write anything in the original fund's folder/repo — you
  should not even have a path to it.
- This app uses its OWN Supabase keys (a different project), so it can only
  read/write its OWN database. A mistake here cannot touch the fund's data.

## 1. START FROM THE EXISTING APP — DON'T REBUILD

The base files (listed below) were **copied in manually** from the original
app — they're battle-tested. Trim them per sections 2–4. (Do not go fetch
them from the other repo; they're already here.)

```
app.py
bbg_style.py
db.py
shared.py
massive.py
ticket.py                (optional — keep if you want the order ticket)
pages/0_Home.py
pages/5_Trade_Log.py
pages/6_Portfolio.py
pages/7_Fund.py          -> becomes the Performance page
pages/8_Order_Ticket.py  (optional)
scripts/daily_snapshot.py
requirements.txt
.streamlit/config.toml
supabase_schema.sql      (see section 5 for the trimmed version)
```

⚠️ **DO NOT re-implement the money logic from scratch** — you'd reintroduce
bugs that took many iterations to fix. Preserve these (already in the code):
- `db._clean` coerces whole-number floats → int (Postgres integer columns
  reject `32.0`). Keep it.
- Saves are **upsert-only**; deletes are **targeted** (`delete_trades`). Keep.
- `shared.py` marking ladder: manual mark → Massive (quote-mid else day close)
  → Yahoo, time-aware (Yahoo mid during US market hours, Massive close after).
  Failures are **never cached** (raise-inside-cached pattern). Keep all of it.
- Contributions are priced at the **flow-date** NAV/unit (snapshot on/before
  the date), not today's. Keep — and it applies to withdrawals too.
- Daily snapshots: past days are **immutable** (only today's row is rewritten).
- Auth **fails closed**; every page calls `bbg_style.inject()` which blocks
  unauthenticated render. Keep.

---

## 2. REMOVE — the screeners and their nav

Delete these pages:
```
pages/1_Short_Puts.py
pages/2_Covered_Calls.py
pages/3_Call_Spreads.py
pages/4_Option_Finder.py
pages/9_Roll_Finder.py
```
In `app.py` `st.navigation({...})`, delete the SCREENERS group and the
Option/Roll Finder entries. Final nav:
```python
nav = st.navigation({
    "HOME":    [st.Page("pages/0_Home.py",     title="Home", default=True)],
    "TRADING": [st.Page("pages/5_Trade_Log.py", title="Trade Log")],
    "FUND":    [st.Page("pages/6_Portfolio.py", title="Portfolio & Risk"),
                st.Page("pages/7_Fund.py",      title="Performance")],
})
```
In `pages/0_Home.py`, remove the screener/finder tiles; keep Trade Log,
Portfolio, Performance (and Order Ticket if kept). Keep the DATA FEED STATUS
panel.

`shared.py` — the screener helpers (`best_put`, `best_call`,
`best_bear_call_spread`, `score_strikes`, `score_put`, `prefetch`,
`trend_label_score`, `rv_percentile`) become unused. You may leave them (dead
but harmless) or delete them. **Keep** `fetch_spot`, `fetch_hist`,
`fetch_expirations`, `fetch_chain`, `fetch_chain_exact`, `fetch_option_live`,
`compute_book_pnl`, `us_market_open_now`, `bs_*`, `DEFAULT_WATCHLIST`,
`get_watchlist`, and the Massive integration.

The watchlist is still needed (Portfolio marks + Trade Log ticker helper), so
keep `DEFAULT_WATCHLIST` / `get_watchlist` / the watchlist table.

---

## 3. CHANGE — Fund page → single-beneficiary "Performance" with withdrawals

Base file: `pages/7_Fund.py`. Changes:

**a) One beneficiary — drop the multi-investor UI.** Remove the "ADD
INVESTOR" / investor list / ownership-% table. There is exactly one owner;
you don't need an investors table or ownership split.

**b) Cash flows allow withdrawals.** Rename "LOG A CONTRIBUTION" →
"LOG A CASH FLOW". The AMOUNT input must accept **negative** values
(withdrawal). Keep the flow-date NAV pricing already in the code. Units logic:
```python
use_nav   = <NAV/unit on the flow date>      # already computed in current code
units_delta = amount / use_nav               # amount<0 (withdrawal) -> redeems units
db.add_cash_flow(date, amount, units_delta, use_nav)
```
For a withdrawal the caption should read e.g. "Redeems 402.6 units at
$95.63/unit". Guard: don't let a withdrawal redeem more units than exist.

**c) NAV uses net contributed.** `net_contributed = Σ amounts` (deposits
positive, withdrawals negative). `NAV = net_contributed + realized +
unrealized`. `total_units = Σ units_delta`. `NAV/unit = NAV/total_units`.
This is a rename of the existing `contributed`/`units_issued` sums — the math
is identical, negatives just flow through.

**d) Headline = TWR.** Keep the NAV/UNIT history chart (that IS the TWR).
Above it, show:
- **TWR since inception** = `NAV/unit − 100` (seed = 100).
- **Current NAV** ($), **net capital in** ($), **total P&L** ($).
- Keep the PERFORMANCE tear sheet (Sharpe/Sortino/DD/Calmar) — still valid
  for one owner; keep the "PRELIMINARY / short track record" banner.
- Keep the FUND-vs-Nasdaq chart (fund line = NAV/unit, matches history).
- Cash-flow markers on the value chart: deposits up, withdrawals down.

**e) Optional:** add a money-weighted return (IRR) using
`numpy_financial.irr` or `scipy` on the dated flows + current NAV as the
terminal value — labels the owner's *actual* dollar return. Skip if you want
it minimal.

---

## 4. KEEP AS-IS

- `pages/5_Trade_Log.py` — the whole thing (add/close/modify, partial close,
  assignment → Long Stock, MANUAL MARK, NET CREDIT BASIS, per-trade
  annualized return, accountability). It's account-agnostic.
- `pages/6_Portfolio.py` — marking, delta/sector/bucket exposure, risk gauges,
  cash & dry powder, naked-call check, stress test. Account-agnostic.
- `db.py`, `massive.py`, `bbg_style.py`, `scripts/daily_snapshot.py`,
  `.streamlit/config.toml`, `requirements.txt`.

`daily_snapshot.py` writes `snapshots` / `portfolio_snapshots` /
`fund_snapshots` — unchanged; it already builds the NAV/unit history the TWR
needs. Just make sure the new Supabase project has those tables.

---

## 5. SUPABASE SCHEMA (trimmed)

Rename `contributions` → `cash_flows` (semantically clearer; amount can be
negative). Drop the `investors` table. Everything else identical.

```sql
-- trades (identical to the main app; includes all the added columns)
create table if not exists trades (
  id             bigint primary key,
  date_opened    date,  ticker text,  strategy text,
  short_strike   double precision, long_strike double precision,
  expiry date,  dte_open integer,  contracts integer,
  premium        double precision, cash_secured double precision,
  max_loss       double precision, status text,
  date_closed    date, close_price double precision, realized_pnl double precision,
  signal text, recommended_by text, consensus boolean,
  manual_mark    double precision, net_credit_basis double precision, notes text
);

-- single-owner cash flows (deposits +, withdrawals −)
create table if not exists cash_flows (
  id            bigserial primary key,
  flow_date     date not null,
  amount        double precision not null,     -- negative = withdrawal
  units_delta   double precision not null,     -- amount / nav_per_unit_at_flow
  nav_per_unit  double precision not null
);

-- watchlist (still needed for marking + ticker helper)
create table if not exists watchlist (
  ticker text primary key, company text, sector text,
  bucket text, conviction integer, delta_band text
);

-- history (written by scripts/daily_snapshot.py)
create table if not exists snapshots (
  snap_date date, ticker text, spot double precision,
  rv21 double precision, rv_rank double precision,
  primary key (snap_date, ticker)
);
create table if not exists portfolio_snapshots (
  snap_date date primary key, open_positions integer,
  total_credits double precision, unreal_pnl double precision,
  realized_pnl double precision, cash_secured double precision
);
create table if not exists fund_snapshots (
  snap_date date primary key, nav double precision, units double precision,
  nav_per_unit double precision, contributed double precision,
  realized_pnl double precision, unreal_pnl double precision
);

alter table trades disable row level security;
alter table cash_flows disable row level security;
alter table watchlist disable row level security;
alter table snapshots disable row level security;
alter table portfolio_snapshots disable row level security;
alter table fund_snapshots disable row level security;
```

In `db.py`, rename the contribution functions to cash-flow equivalents
(`load_cash_flows`, `add_cash_flow`) pointing at the `cash_flows` table;
`fund_snapshots.contributed` = net contributed. Delete the investor
functions.

---

## 6. SETUP CHECKLIST (Charles / the new session)

1. **New GitHub repo** (private — the logs are public otherwise).
2. **New Supabase project** → SQL editor → run the schema above.
3. **Streamlit Cloud** → new app from the repo, main file `app.py`
   (or `public_app/app.py` if you keep that folder layout). Secrets:
   ```toml
   SCREENER_PASSWORD = "..."          # required — auth fails closed without it
   SUPABASE_URL = "https://xxx.supabase.co"
   SUPABASE_KEY = "eyJ..."            # anon key
   MASSIVE_API_KEY = "..."            # optional (Options Starter) — Yahoo fallback works without
   ```
4. **GitHub Actions** for the daily snapshot: copy
   `.github/workflows/daily_snapshot.yml`; add repo Actions secrets
   `SUPABASE_URL`, `SUPABASE_KEY`, `MASSIVE_API_KEY`.
5. Seed the watchlist (SYNC DEFAULT NAMES in the app, or let it seed on first
   load) so Portfolio marking works.

---

## 7. ACCEPTANCE CHECKS

- Log a deposit and a withdrawal on different dates → units go up then down;
  NAV/unit is unaffected by the flows (moves only with P&L).
- NAV = net contributed + realized + unrealized (reconciles to the dollar).
- A trade saves after an assignment creates a Long Stock (no `22P02` integer
  error — that's the `_clean` fix).
- Performance page shows TWR = NAV/unit − 100; tear sheet shows the
  PRELIMINARY banner until ~18 months of history.
- No screener pages; nav shows HOME / TRADING / FUND only.
```
