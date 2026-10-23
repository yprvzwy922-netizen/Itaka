"""
End-of-day data for the GitHub Actions scripts (daily_snapshot.py, alerts.py):
Supabase REST, end-of-day spots and option marks — one copy, shared by both.

Positions are priced by public_app/book.py through book_now(), the same engine
the app uses; only the price source differs (end-of-day here, live in the app).
Needs env vars SUPABASE_URL, SUPABASE_KEY (MASSIVE_API_KEY optional). TABLE_PREFIX
(e.g. "messi_") points every table at that fund's own copy in the shared project.
"""
import datetime
import os
import sys

import pandas as pd
import requests
import yfinance as yf

# The app modules (book.py, risk.py, watchlist.py) live at the repo root here.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import book as bk                                   # noqa: E402
import risk                                         # noqa: E402,F401  (re-exported for the scripts)
from watchlist import DEFAULT_WATCHLIST             # noqa: E402

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_KEY", "")
MASSIVE_KEY = os.environ.get("MASSIVE_API_KEY", "")
# Per-fund table namespace: "" = ITAKA's tables, "messi_" = MESSI's.
TABLE_PREFIX = os.environ.get("TABLE_PREFIX", "")
if not URL or not KEY:
    sys.exit("SUPABASE_URL / SUPABASE_KEY not set")

HDRS = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}


def rest(method, table, params=None, json=None, prefer=None):
    h = dict(HDRS)
    if prefer:
        h["Prefer"] = prefer
    r = requests.request(method, f"{URL}/rest/v1/{TABLE_PREFIX}{table}", headers=h, params=params, json=json, timeout=20)
    r.raise_for_status()
    return r.json() if r.text else None


_now = datetime.datetime.now(bk.ET)
US_RTH = _now.weekday() < 5 and datetime.time(9, 30) <= _now.time() < datetime.time(16, 0)

# ── Prices ────────────────────────────────────────────────────────────────────
_hist = {}


def history(tkr) -> pd.Series:
    """1y of daily closes, Yahoo's NaN rows dropped. Downloaded once per run."""
    if tkr not in _hist:
        try:
            h = yf.Ticker(tkr).history(period="1y")
            _hist[tkr] = h["Close"].dropna() if not h.empty else pd.Series(dtype=float)
        except Exception as e:
            print(f"  {tkr}: {e}")
            _hist[tkr] = pd.Series(dtype=float)
    return _hist[tkr]


def spot(tkr) -> float:
    c = history(tkr)
    return float(c.iloc[-1]) if len(c) else float("nan")


def trading_date() -> datetime.date:
    """The last US trading session: SPY's last bar with a real close (handles
    weekends and holidays; Yahoo can append an all-NaN row), never a future date.
    A run at 12:46am Friday is still THURSDAY's session — the snapshot is dated
    by it and the once-a-day alert email is keyed on it."""
    now = bk.today_et()
    c = history("SPY")
    if len(c):
        return min(c.index[-1].date(), now)
    while now.weekday() >= 5:                       # weekend -> Friday
        now -= datetime.timedelta(days=1)
    return now


_mchain = {}


def massive_mid(tkr, strike, expiry, kind):
    """Mid for one contract from Massive's chain snapshot (quote mid, else day
    close); None if unavailable. One call per (ticker, expiry, type)."""
    if not MASSIVE_KEY:
        return None
    ck = (tkr, expiry, kind)
    if ck not in _mchain:
        m = {}
        try:
            r = requests.get(f"https://api.massive.com/v3/snapshot/options/{tkr.upper()}",
                             params={"expiration_date": expiry, "contract_type": kind,
                                     "limit": 250, "apiKey": MASSIVE_KEY}, timeout=10)
            r.raise_for_status()
            for c in r.json().get("results", []):
                k = (c.get("details") or {}).get("strike_price")
                q, day = c.get("last_quote") or {}, c.get("day") or {}
                bid, ask, close = float(q.get("bid") or 0), float(q.get("ask") or 0), float(day.get("close") or 0)
                mid = (bid + ask) / 2 if (bid > 0 and ask > 0) else (close if close > 0 else None)
                if k is not None and mid:
                    m[round(float(k), 2)] = mid
        except Exception as e:
            print(f"  massive chain {tkr} {expiry}: {e}")
        _mchain[ck] = m
    return _mchain[ck].get(round(float(strike), 2))


def yahoo_mid(tkr, strike, expiry, kind):
    """Two-sided bid/ask mid from Yahoo; None if the strike isn't listed or one-sided."""
    try:
        raw = yf.Ticker(tkr).option_chain(expiry)
        chain = raw.puts if kind == "put" else raw.calls
        if chain is None or chain.empty:
            return None
        chain = chain.assign(dist=(chain["strike"] - strike).abs())
        row = chain.loc[chain["dist"].idxmin()]
        if float(row["dist"]) > max(0.015 * strike, 0.50):
            return None
        bid, ask = float(row["bid"]), float(row["ask"])
        mid = (bid + ask) / 2 if (bid > 0 and ask > 0) else None
        return mid if mid == mid else None
    except Exception:
        return None


def mark(tkr, strike, expiry, kind):
    """(mid, iv) on the app's time-aware ladder: market hours -> Yahoo mid first
    (Massive fallback); closed -> Massive close first (Yahoo fallback)."""
    if US_RTH:
        mid = yahoo_mid(tkr, strike, expiry, kind) or massive_mid(tkr, strike, expiry, kind)
    else:
        mid = massive_mid(tkr, strike, expiry, kind) or yahoo_mid(tkr, strike, expiry, kind)
    return (float(mid), float("nan")) if mid else (float("nan"), float("nan"))


# ── Trades & the book ─────────────────────────────────────────────────────────
def load_trades() -> pd.DataFrame:
    return bk.trades_from_rows(rest("GET", "trades", params={"select": "*", "order": "id"}))


def sector_map() -> dict:
    """ticker -> sector / bucket: the live DB watchlist over the code's defaults."""
    m = {w["ticker"]: w for w in DEFAULT_WATCHLIST}
    m.update({r["ticker"]: r for r in (rest("GET", "watchlist", params={"select": "ticker,sector,bucket"}) or [])})
    return m


def book_now(trades) -> pd.DataFrame:
    """The open book at end-of-day prices (public_app/book.py)."""
    return bk.build_book(trades[trades["STATUS"] == "OPEN"], spot, mark, None, sector_map(), today=bk.today_et())
