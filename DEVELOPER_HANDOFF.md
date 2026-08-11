# Developer Handoff — Itaka / Messi Fund Tracker

A Streamlit + Supabase app that tracks single-beneficiary, put-selling funds:
trade log, portfolio & risk, and unitized NAV performance (NAV/unit = time-weighted
return). **One codebase runs multiple funds** — each fund is a separate Streamlit
deployment pointed at its own data via secrets.

- **GitHub:** https://github.com/yprvzwy922-netizen/Itaka
- **Live apps:** two Streamlit Community Cloud deployments (Itaka, Messi) — URLs from the owner.
- **Secrets (Supabase URL/key, Massive key, app password):** sent separately/securely — see "Secrets" below.

---

## 1. Architecture at a glance

| Concern | How it works |
|---|---|
| Frontend/backend | **Streamlit** (Python). Multi-page via `st.navigation` in `app.py`. |
| Database | **Supabase** (Postgres) accessed over **PostgREST** with plain `requests` in `db.py` — no ORM/SDK. |
| Market data | `shared.py` marking ladder: **Massive** API first (bid/ask or day close + IV/Greeks) → **yfinance** fallback. Time-aware (quotes in RTH, close after hours). Failures are never cached. |
| Auth | Single shared password gate (`SCREENER_PASSWORD`), **fails closed**. Every page calls `bbg_style.inject()`, which blocks unauthenticated render. Not Supabase RLS. |
| Charts | Plotly (in-app) + inline SVG (reports). |

### Multi-fund design (important)
The **same repo** powers every fund. A fund's identity comes entirely from **its
Streamlit deployment's secrets** — no code fork:

- `FUND_NAME` — display name (title/login/home). Defaults to "ITAKA FUND".
- `TABLE_PREFIX` — namespaces the Postgres tables so multiple funds share ONE
  Supabase project. Empty = Itaka (`trades`, `cash_flows`, …). `messi_` = Messi
  (`messi_trades`, `messi_cash_flows`, …). Applied centrally in `db._rest`.
- Each fund has its own `SUPABASE_*`, `SCREENER_PASSWORD`.

Streamlit identifies an app by **(repo, branch, main-file)**, so a second app on the
same repo+branch needs a **distinct entry file**:

| Fund | Streamlit main file | Tables |
|---|---|---|
| Itaka | `app.py` | `trades`, `cash_flows`, `watchlist`, `*_snapshots` |
| Messi | `messi.py` (thin wrapper that runs `app.py`) | `messi_*` |

A third fund = new entry file (`fundX.py`, copy `messi.py`) + `TABLE_PREFIX=fundx_`
+ its own tables + secrets. No new repo, no new Supabase project required.

---

## 2. Repo layout

```
app.py                    Entry/router: password gate + st.navigation. Reads FUND_NAME.
messi.py                  2nd-fund entry point (runpy-runs app.py fresh each rerun).
db.py                     Supabase/PostgREST layer. TABLE_PREFIX, _clean (int coercion),
                          upsert-only saves, targeted deletes, cash_flows, snapshots.
shared.py                 Market data + marking ladder (Massive→Yahoo), BS greeks,
                          watchlist defaults, screener/scoring helpers.
massive.py                Massive API client.
bbg_style.py              Bloomberg-dark theme + the auth guard (inject()).
ticket.py                 Order-ticket session cart + broker-message formatter.
pages/
  0_Home.py               Tiles + data-feed status.
  4_Option_Finder.py      Per-ticker chain deep-dive, scoring, payoff, add-to-ticket.
  5_Trade_Log.py          Add/close/modify trades; CSV import/export.
  6_Portfolio.py          Marking, delta/sector/bucket exposure, risk gauges, stress test,
                          held-stock covered-call capacity.
  7_Fund.py               "Performance" — cash flows (deposits/withdrawals), NAV/unit (TWR),
                          tear sheet, benchmark vs Nasdaq.
  8_Order_Ticket.py       Broker-ready message builder.
  9_Roll_Finder.py        Scored roll candidates for open shorts.
scripts/daily_snapshot.py Writes daily snapshots/portfolio_snapshots/fund_snapshots.
                          Self-contained (no Streamlit). Honors TABLE_PREFIX env.
.github/workflows/        Manual (workflow_dispatch) snapshot jobs, one per fund.
supabase_schema.sql       Itaka table DDL + RLS-disable.
requirements.txt          Python deps.
.streamlit/config.toml    Dark theme.
HANDOFF.md                Original build spec (context/history).
```

---

## 3. Local development

```bash
git clone https://github.com/yprvzwy922-netizen/Itaka.git
cd Itaka
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Create `.streamlit/secrets.toml` (git-ignored) with the values from the owner:

```toml
FUND_NAME = "ITAKA FUND"          # or "Messi se toma una pesi"
TABLE_PREFIX = ""                 # "" for Itaka, "messi_" for Messi
SCREENER_PASSWORD = "..."
SUPABASE_URL = "https://<ref>.supabase.co"
SUPABASE_KEY = "eyJ..."           # anon key
MASSIVE_API_KEY = "..."           # optional; yfinance works without it
```

Run:
```bash
streamlit run app.py        # Itaka
streamlit run messi.py      # Messi
```

⚠️ Use a **dev/staging Supabase** (or a throwaway `TABLE_PREFIX` like `dev_`) for
local testing so you don't write into a live fund's tables.

---

## 4. Supabase

- One Postgres project holds all funds' tables; funds are separated by table prefix.
- Access is the **anon key used server-side** by Streamlit. **RLS is disabled** on all
  tables (the app's own password gate is the access control, not Supabase RLS). If a
  table shows a `42501 / row-level security` error, run
  `alter table <name> disable row level security;`.
- Create a new fund's tables by running `supabase_schema.sql` with a prefix search/replace
  (see the `messi_` block history), followed by the `disable row level security` lines.
- Key tables: `trades`, `cash_flows` (deposits +, withdrawals −, unit-priced at flow date),
  `watchlist`, `snapshots`, `portfolio_snapshots`, `fund_snapshots`.

## 5. Deployment (Streamlit Community Cloud)

- One app per fund. Repo `yprvzwy922-netizen/Itaka`, branch `main`, main file `app.py`
  (Itaka) or `messi.py` (Messi). Each app's **Secrets** = the block in §3.
- Pushing to `main` redeploys **all** funds (shared code — fix once).

## 6. Scheduled data (GitHub Actions)

- `.github/workflows/*.yml` — **manual** (`workflow_dispatch`) snapshot jobs, one per fund
  (Itaka; Messi sets `TABLE_PREFIX=messi_`). Cron was removed (GitHub schedules were
  unreliable). Run each trading day from the Actions tab to append that day's NAV point.
- Needs repo **Actions secrets**: `SUPABASE_URL`, `SUPABASE_KEY`, `MASSIVE_API_KEY`
  (shared across funds since they share one Supabase project).

---

## 7. Money logic — do NOT re-implement from scratch (hard-won)

- `db._clean` coerces whole-number floats → int (Postgres integer cols reject `32.0`).
- Saves are **upsert-only**; deletes are **targeted** (`delete_trades`) — safe for concurrent tabs.
- Marking ladder in `shared.py`: manual mark → Massive (quote-mid else day close) → Yahoo,
  time-aware. **Failures are never cached** (raise-inside-cached pattern).
- Cash flows are priced at the **flow-date** NAV/unit (snapshot on/before the date).
- Daily snapshots: past days are **immutable**; only today's row is rewritten.
- **NAV = net_contributed + realized + unrealized. NAV/unit indexed to 100 = TWR.**
- Auth **fails closed**; keep `bbg_style.inject()` on every page.

## 8. Secrets (sent separately — never commit real values)

The owner will send the real values through a secure channel. They map 1:1 to the
`secrets.toml` block in §3, per fund:

| Key | What | Sensitivity |
|---|---|---|
| `SUPABASE_URL` | Project URL (`https://<ref>.supabase.co`) | low (not secret alone) |
| `SUPABASE_KEY` | anon key — with RLS off, this is full DB read/write | **high** |
| `MASSIVE_API_KEY` | paid options data feed | **high** |
| `SCREENER_PASSWORD` | app login gate | **high** |
| `FUND_NAME` / `TABLE_PREFIX` | per-fund identity (not secret) | none |

Rotate `SUPABASE_KEY` / `MASSIVE_API_KEY` if they are ever exposed.
