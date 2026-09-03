"""
Daily snapshot job — run by GitHub Actions after US close (or manually).

Writes to Supabase:
  snapshots            one row per watchlist ticker (spot, 21d realized vol, vol rank)
  portfolio_snapshots  one row per day (open positions, credits, unreal/realized P&L)

Needs env vars: SUPABASE_URL, SUPABASE_KEY.
Self-contained on purpose — no streamlit import (shared.py needs a Streamlit runtime).
"""
import datetime
import os
import sys
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import yfinance as yf

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_KEY", "")
MASSIVE_KEY = os.environ.get("MASSIVE_API_KEY", "")

if not URL or not KEY:
    sys.exit("SUPABASE_URL / SUPABASE_KEY not set")

# ── Massive marking (same price ladder as the app: quote-mid else day close) ──
_mchain_cache = {}

def massive_mid(tkr, strike, expiry, opt_type):
    """Mid for one contract from Massive's chain snapshot; None if unavailable.
    Chains are cached per (ticker, expiry, type) so N positions = 1 call."""
    if not MASSIVE_KEY:
        return None
    ck = (tkr, expiry, opt_type)
    if ck not in _mchain_cache:
        m = {}
        try:
            r = requests.get(f"https://api.massive.com/v3/snapshot/options/{tkr.upper()}",
                             params={"expiration_date": expiry, "contract_type": opt_type,
                                     "limit": 250, "apiKey": MASSIVE_KEY}, timeout=10)
            r.raise_for_status()
            for c in r.json().get("results", []):
                k    = (c.get("details") or {}).get("strike_price")
                q    = c.get("last_quote") or {}
                day  = c.get("day") or {}
                bid  = float(q.get("bid") or 0)
                ask  = float(q.get("ask") or 0)
                close = float(day.get("close") or 0)
                mid = (bid + ask) / 2 if (bid > 0 and ask > 0) else (close if close > 0 else None)
                if k is not None and mid:
                    m[round(float(k), 2)] = mid
        except Exception as e:
            print(f"  massive chain {tkr} {expiry}: {e}")
        _mchain_cache[ck] = m
    return _mchain_cache[ck].get(round(float(strike), 2))

def yahoo_mid(tkr, strike, expiry, opt_type):
    """Two-sided bid/ask mid from Yahoo; None if strike unlisted or one-sided."""
    try:
        raw = yf.Ticker(tkr).option_chain(expiry)
        chain = raw.puts if opt_type == "put" else raw.calls
        if chain is None or chain.empty:
            return None
        chain = chain.copy()
        chain["dist"] = (chain["strike"] - strike).abs()
        row = chain.loc[chain["dist"].idxmin()]
        if float(row["dist"]) > max(0.015 * strike, 0.50):
            return None
        bid, ask = float(row["bid"]), float(row["ask"])
        return (bid + ask) / 2 if (bid > 0 and ask > 0) else None
    except Exception:
        return None

def mark_mid(tkr, strike, expiry, opt_type):
    """Mirror the app's time-aware ladder EXACTLY so header and snapshot agree:
    market hours -> Yahoo mid first (Massive fallback); closed -> Massive close
    first (Yahoo fallback)."""
    if US_RTH:
        return yahoo_mid(tkr, strike, expiry, opt_type) or massive_mid(tkr, strike, expiry, opt_type)
    return massive_mid(tkr, strike, expiry, opt_type) or yahoo_mid(tkr, strike, expiry, opt_type)

HDRS = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

# Optional table namespace so several funds can share one Supabase project.
# Set TABLE_PREFIX in this job's env (e.g. "messi_"); empty = plain names (Itaka).
TABLE_PREFIX = os.environ.get("TABLE_PREFIX", "")

def rest(method, table, params=None, json=None, prefer=None):
    h = dict(HDRS)
    if prefer:
        h["Prefer"] = prefer
    r = requests.request(method, f"{URL}/rest/v1/{TABLE_PREFIX}{table}",
                         headers=h, params=params, json=json, timeout=20)
    r.raise_for_status()
    return r.json() if r.text else None

def last_trading_day():
    """The trading day to stamp the snapshot with. Uses SPY's last daily bar,
    which handles weekends AND holidays for free. On a trading day this is TODAY
    (even intraday — we capture a current snapshot for today and overwrite it
    later at close), so a run NEVER rewrites a completed past day. Only weekends/
    holidays roll back to the prior session (SPY has no bar for those)."""
    now_et = datetime.datetime.now(ZoneInfo("America/New_York"))
    try:
        h = yf.Ticker("SPY").history(period="7d")
        if not h.empty:
            return h.index[-1].date()
    except Exception:
        pass
    d = now_et.date()
    while d.weekday() >= 5:        # weekend -> roll back to Friday
        d -= datetime.timedelta(days=1)
    return d

TODAY = last_trading_day().isoformat()
TODAY_ET = datetime.datetime.now(ZoneInfo("America/New_York")).date().isoformat()
# A snapshot dated before the actual current ET date is a COMPLETED past
# session — never overwrite it. Only the live (current) day may be rewritten
# (intraday -> close). This keeps stored history immutable.
IS_PAST_DAY = TODAY < TODAY_ET
_now_et = datetime.datetime.now(ZoneInfo("America/New_York"))
US_RTH = _now_et.weekday() < 5 and datetime.time(9, 30) <= _now_et.time() < datetime.time(16, 0)
print(f"snapshot date: {TODAY}  (today ET: {TODAY_ET}, past-day lock: {IS_PAST_DAY})")

def already_stored(table):
    try:
        rows = rest("GET", table, params={"select": "snap_date", "snap_date": f"eq.{TODAY}"})
        return bool(rows)
    except Exception:
        return False

def should_skip(table):
    if IS_PAST_DAY and already_stored(table):
        print(f"{table} {TODAY} already stored (completed day) — NOT overwriting")
        return True
    return False

# ── Per-ticker snapshots ──────────────────────────────────────────────────────
wl = rest("GET", "watchlist", params={"select": "ticker"}) or []
tickers = sorted({w["ticker"] for w in wl})
print(f"watchlist: {len(tickers)} tickers")

ticker_rows = []
for tkr in tickers:
    try:
        t = yf.Ticker(tkr)
        hist = t.history(period="1y")
        if hist.empty:
            continue
        spot = float(hist["Close"].iloc[-1])
        ret = hist["Close"].pct_change().dropna()
        rv = (ret.rolling(21).std() * np.sqrt(252)).dropna()
        rv21 = float(rv.iloc[-1]) if len(rv) else None
        rv_rank = (float(np.clip((rv.iloc[-1] - rv.min()) / (rv.max() - rv.min()), 0, 1))
                   if len(rv) > 10 and rv.max() > rv.min() else None)
        ticker_rows.append({"snap_date": TODAY, "ticker": tkr, "spot": round(spot, 4),
                            "rv21": rv21, "rv_rank": rv_rank})
    except Exception as e:
        print(f"  {tkr}: {e}")

if ticker_rows:
    rest("POST", "snapshots", json=ticker_rows,
         prefer="resolution=merge-duplicates,return=minimal")
    print(f"snapshots written: {len(ticker_rows)}")

# ── Portfolio snapshot ────────────────────────────────────────────────────────
trades = rest("GET", "trades", params={"select": "*"}) or []
open_t = [t for t in trades if t.get("status") == "OPEN"]

realized = sum(float(t["realized_pnl"]) for t in trades if t.get("realized_pnl") is not None)
credits  = sum(float(t["premium"] or 0) * 100 * int(t["contracts"] or 0) for t in trades)
cash_sec = sum(float(t["cash_secured"] or 0) for t in open_t)

unreal = 0.0
for t in open_t:
    try:
        strat = str(t["strategy"])
        prem, ctrs = float(t["premium"] or 0), int(t["contracts"] or 0)
        tkr = t["ticker"]
        # Manual mark (typed from the broker in the app) beats the live feed
        mmark = t.get("manual_mark")
        mmark = float(mmark) if mmark not in (None, "", 0) else None
        # Long Stock: mark vs entry price, per share
        if strat == "Long Stock":
            if mmark and prem > 0:
                unreal += (mmark - prem) * ctrs
                continue
            h = yf.Ticker(tkr).history(period="2d")
            if not h.empty and prem > 0:
                unreal += (float(h["Close"].iloc[-1]) - prem) * ctrs
            continue
        if mmark:
            is_short = strat not in ("Long Put (Hedge)", "Long Call")
            unreal += ((prem - mmark) if is_short else (mmark - prem)) * 100 * ctrs
            continue
        strike, expiry = float(t["short_strike"] or 0), t.get("expiry")
        if not strike or not expiry:
            continue
        opt_type = "put" if "Put" in strat else "call"
        is_short = strat not in ("Long Put (Hedge)", "Long Call")

        # Identical time-aware ladder to the live app header (mark_mid).
        mid = mark_mid(tkr, strike, expiry, opt_type)
        if mid is None:
            continue                               # no usable price -> leave flat
        unreal += ((prem - mid) if is_short else (mid - prem)) * 100 * ctrs
    except Exception as e:
        print(f"  mark {t.get('ticker')}: {e}")

if not should_skip("portfolio_snapshots"):
    rest("POST", "portfolio_snapshots", json=[{
        "snap_date": TODAY,
        "open_positions": len(open_t),
        "total_credits": round(credits, 2),
        "unreal_pnl": round(unreal, 2),
        "realized_pnl": round(realized, 2),
        "cash_secured": round(cash_sec, 2),
    }], prefer="resolution=merge-duplicates,return=minimal")
    # Public repo -> Actions logs are public. Never print dollar values.
    print(f"portfolio snapshot {TODAY}: open={len(open_t)} — written (values redacted)")

# ── Fund NAV snapshot (unitized) ──────────────────────────────────────────────
if not should_skip("fund_snapshots"):
    try:
        flows = rest("GET", "cash_flows", params={"select": "*"}) or []
        contributed = sum(float(c["amount"] or 0) for c in flows)       # net: deposits − withdrawals
        units       = sum(float(c["units_delta"] or 0) for c in flows)
        nav         = contributed + realized + unreal
        nav_per_unit = (nav / units) if units > 0 else 100.0

        # QQQ benchmark: capture the close HERE (yfinance is reliable in Actions)
        # and store it, so the app never depends on a live Yahoo call at render
        # (Streamlit Cloud's server is often blocked). Optional column — if the
        # ALTER hasn't been run yet, skip it cleanly and behave exactly as before.
        try:
            rest("GET", "fund_snapshots", params={"select": "qqq_close", "limit": 1})
            has_qqq_col = True
        except Exception:
            has_qqq_col = False

        qqq_closes = {}
        if has_qqq_col:
            try:
                qh = yf.Ticker("QQQ").history(period="1y")
                if not qh.empty:
                    qqq_closes = {d.isoformat(): round(float(c), 4)
                                  for d, c in zip(qh.index.date, qh["Close"])}
            except Exception as e:
                print(f"  QQQ history fetch failed: {e}")

        row = {
            "snap_date": TODAY,
            "nav": round(nav, 2),
            "units": round(units, 4),
            "nav_per_unit": round(nav_per_unit, 4),
            "contributed": round(contributed, 2),
            "realized_pnl": round(realized, 2),
            "unreal_pnl": round(unreal, 2),
        }
        if has_qqq_col:
            row["qqq_close"] = qqq_closes.get(TODAY)   # None if today's bar isn't in yet
        rest("POST", "fund_snapshots", json=[row],
             prefer="resolution=merge-duplicates,return=minimal")
        print(f"fund snapshot {TODAY}: written (values redacted)")

        # Backfill QQQ close on any past rows that lack it — self-heals the whole
        # history so the benchmark works from the first snapshot, not just today.
        if has_qqq_col and qqq_closes:
            try:
                rows = rest("GET", "fund_snapshots",
                            params={"select": "snap_date,qqq_close"}) or []
                filled = 0
                for r in rows:
                    if r.get("qqq_close") is None:
                        c = qqq_closes.get(str(r["snap_date"]))
                        if c is not None:
                            rest("PATCH", "fund_snapshots",
                                 params={"snap_date": f"eq.{r['snap_date']}"},
                                 json={"qqq_close": c}, prefer="return=minimal")
                            filled += 1
                if filled:
                    print(f"  QQQ backfilled on {filled} past snapshot(s)")
            except Exception as e:
                print(f"  QQQ backfill skipped: {e}")
    except Exception as e:
        print(f"fund snapshot skipped: {e}")
