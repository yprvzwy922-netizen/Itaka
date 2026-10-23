"""
Daily snapshot job — run by GitHub Actions after the US close (or by hand).

Writes to Supabase:
  snapshots            one row per ticker per day (spot, 21d realized vol, vol rank)
                       for the watchlist, every name ever traded and QQQ; plus any
                       missing past closes for traded names + QQQ (feeds betas and
                       the Portfolio's breach history)
  portfolio_snapshots  one row per day (open positions, credits, unreal/realized P&L)
  fund_snapshots       one row per day (NAV, units, NAV per unit, QQQ close)
TABLE_PREFIX (e.g. "messi_") writes the same tables under that fund's prefix.

Positions are priced by public_app/book.py (via eod_feeds.book_now) — the same
engine as the app. Public repo -> Actions logs are public: never print dollar
values or position tickers.
"""
import math
import os
import sys

import numpy as np
import pandas as pd

from eod_feeds import bk, book_now, history, load_trades, rest, risk, trading_date

# Dated by the last trading session. On a trading day that's TODAY even intraday
# (the later run at close overwrites it), so a run never rewrites a completed day.
TODAY = trading_date().isoformat()
TODAY_ET = bk.today_et().isoformat()
# Hand the session date to the workflow — it keys the once-a-day alert email.
if os.environ.get("GITHUB_OUTPUT"):
    with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
        fh.write(f"trade_date={TODAY}\n")
# A snapshot dated before the current ET date is a COMPLETED past session — never
# overwrite it. Only the live day may be rewritten (intraday -> close).
IS_PAST_DAY = TODAY < TODAY_ET
print(f"snapshot date: {TODAY}  (today ET: {TODAY_ET}, past-day lock: {IS_PAST_DAY})")

def should_skip(table):
    if not IS_PAST_DAY:
        return False
    try:
        stored = bool(rest("GET", table, params={"select": "snap_date", "snap_date": f"eq.{TODAY}"}))
    except Exception:
        stored = False
    if stored:
        print(f"{table} {TODAY} already stored (completed day) — NOT overwriting")
    return stored

trades = load_trades()
traded = set(trades["TICKER"].dropna().astype(str))

# ── Per-ticker snapshots ──────────────────────────────────────────────────────
# Watchlist + every traded name + QQQ (the fund-vs-Nasdaq benchmark and the
# beta reference) — the app reads these from the DB instead of a live Yahoo call.
wl = {w["ticker"] for w in (rest("GET", "watchlist", params={"select": "ticker"}) or [])}
tickers = sorted(wl | traded | {risk.BENCH})
print(f"tickers: {len(tickers)} (watchlist + traded + QQQ)")

ticker_rows = []
for tkr in tickers:
    close = history(tkr)
    if close.empty:
        continue
    ret = close.pct_change().dropna()
    rv = (ret.rolling(21).std() * np.sqrt(252)).dropna()
    rv21 = float(rv.iloc[-1]) if len(rv) else None
    rv_rank = (float(np.clip((rv.iloc[-1] - rv.min()) / (rv.max() - rv.min()), 0, 1))
               if len(rv) > 10 and rv.max() > rv.min() else None)
    ticker_rows.append({"snap_date": TODAY, "ticker": tkr, "spot": round(float(close.iloc[-1]), 4),
                        "rv21": rv21, "rv_rank": rv_rank})
if ticker_rows:
    rest("POST", "snapshots", json=ticker_rows, prefer="resolution=merge-duplicates,return=minimal")
    print(f"snapshots written: {len(ticker_rows)}")

# ── Fill missing past closes for traded names + QQQ ───────────────────────────
# Betas and the breach history need a continuous daily price record. Only dates
# not already stored are written, so after the first run this is ~0 rows/day.
try:
    need = sorted(traded | {risk.BENCH})
    have = risk.fetch_closes(lambda p: rest("GET", "snapshots", params=p), need)
    rows = []
    for t in need:
        got = set(have.index[have[t].notna()]) if t in have.columns else set()
        rows += [{"snap_date": d.date().isoformat(), "ticker": t, "spot": round(float(v), 4)}
                 for d, v in history(t).items() if d.date() not in got]
    for i in range(0, len(rows), 1000):
        rest("POST", "snapshots", json=rows[i:i + 1000], prefer="resolution=merge-duplicates,return=minimal")
    if rows:
        print(f"history backfilled: {len(rows)} close(s) across {len({r['ticker'] for r in rows})} ticker(s)")
except Exception as e:
    print(f"history backfill skipped: {e}")

# ── Portfolio snapshot ────────────────────────────────────────────────────────
num = lambda s: pd.to_numeric(s, errors="coerce").fillna(0)
open_t = trades[trades["STATUS"] == "OPEN"]
realized = float(num(trades["REALIZED PNL"]).sum())
shorts = trades[trades["STRATEGY"].map(lambda s: bk.is_short(s) and not bk.is_stock(s))]
credits = float((num(shorts["PREMIUM / CREDIT"]) * 100 * num(shorts["CONTRACTS"])).sum())   # premium received
cash_sec = float(num(open_t["CASH SECURED"]).sum())

book = book_now(trades)
n_unpriced = len(bk.unpriced(book))
if n_unpriced:
    print(f"  no price for {n_unpriced} position(s) — held flat at entry")
unreal = float(pd.to_numeric(book["UNREAL PNL"], errors="coerce").sum()) if not book.empty else 0.0

# A NaN can't be stored and would poison NAV — fail loudly rather than write it.
if not math.isfinite(unreal):
    sys.exit("unrealized P&L came out non-finite — not writing portfolio/fund snapshots")

if not should_skip("portfolio_snapshots"):
    rest("POST", "portfolio_snapshots", json=[{
        "snap_date": TODAY,
        "open_positions": len(open_t),
        "total_credits": round(credits, 2),
        "unreal_pnl": round(unreal, 2),
        "realized_pnl": round(realized, 2),
        "cash_secured": round(cash_sec, 2),
    }], prefer="resolution=merge-duplicates,return=minimal")
    print(f"portfolio snapshot {TODAY}: open={len(open_t)} — written (values redacted)")

# ── Fund NAV snapshot (unitized, from cash flows) ─────────────────────────────
if not should_skip("fund_snapshots"):
    try:
        flows = rest("GET", "cash_flows", params={"select": "*"}) or []
        contributed = sum(float(c["amount"] or 0) for c in flows)       # net: deposits − withdrawals
        units = sum(float(c["units_delta"] or 0) for c in flows)
        nav = contributed + realized + unreal

        # QQQ benchmark stored on the fund snapshot (optional column — skipped
        # cleanly if the ALTER hasn't been run), so the Performance page never
        # needs a live Yahoo call at render.
        try:
            rest("GET", "fund_snapshots", params={"select": "qqq_close", "limit": 1})
            has_qqq_col = True
        except Exception:
            has_qqq_col = False
        qqq_closes = ({d.date().isoformat(): round(float(c), 4) for d, c in history(risk.BENCH).items()}
                      if has_qqq_col else {})

        row = {
            "snap_date": TODAY,
            "nav": round(nav, 2),
            "units": round(units, 4),
            "nav_per_unit": round(nav / units if units > 0 else 100.0, 4),
            "contributed": round(contributed, 2),
            "realized_pnl": round(realized, 2),
            "unreal_pnl": round(unreal, 2),
        }
        if has_qqq_col:
            row["qqq_close"] = qqq_closes.get(TODAY)   # None if the session's bar isn't in yet
        rest("POST", "fund_snapshots", json=[row], prefer="resolution=merge-duplicates,return=minimal")
        print(f"fund snapshot {TODAY}: written (values redacted)")

        # Backfill QQQ close on past rows that lack it — self-heals the history.
        if has_qqq_col and qqq_closes:
            try:
                filled = 0
                for r in rest("GET", "fund_snapshots", params={"select": "snap_date,qqq_close"}) or []:
                    c = qqq_closes.get(str(r["snap_date"])) if r.get("qqq_close") is None else None
                    if c is not None:
                        rest("PATCH", "fund_snapshots", params={"snap_date": f"eq.{r['snap_date']}"},
                             json={"qqq_close": c}, prefer="return=minimal")
                        filled += 1
                if filled:
                    print(f"  QQQ backfilled on {filled} past snapshot(s)")
            except Exception as e:
                print(f"  QQQ backfill skipped: {e}")
    except Exception as e:
        print(f"fund snapshot skipped: {e}")
