"""
yfinance data fetching with simple in-memory + SQLite caching.
All public functions return plain pandas DataFrames or scalars.
"""
import datetime
import functools
import time
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

DB_PATH = Path(__file__).parent.parent / "data" / "puts_dashboard.db"
DB_PATH.parent.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS iv_snapshots (
            date TEXT, ticker TEXT, atm_iv REAL,
            PRIMARY KEY (date, ticker)
        );
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_opened TEXT, ticker TEXT, strategy TEXT, track TEXT,
            strike REAL, expiry TEXT, dte_open INTEGER,
            contracts INTEGER, premium_per_ct REAL,
            status TEXT DEFAULT 'open',
            realized_pnl REAL DEFAULT 0,
            signal_tag TEXT, notes TEXT
        );
        CREATE TABLE IF NOT EXISTS watchlist (
            ticker TEXT PRIMARY KEY,
            company TEXT, sector TEXT, bucket TEXT,
            conviction INTEGER DEFAULT 3,
            target_delta_band TEXT DEFAULT 'Income'
        );
        CREATE TABLE IF NOT EXISTS income (
            month TEXT PRIMARY KEY,
            premium REAL DEFAULT 0,
            closed_pnl REAL DEFAULT 0,
            assignment REAL DEFAULT 0,
            hedge_cost REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, ticker TEXT, source TEXT,
            signal_type TEXT, timeframe TEXT
        );
        """)


# ---------------------------------------------------------------------------
# Simple TTL cache (avoids hammering yfinance)
# ---------------------------------------------------------------------------

_cache: dict = {}
_CACHE_TTL = 300  # seconds


def _cached(key: str, fn, ttl: int = _CACHE_TTL):
    now = time.time()
    if key in _cache:
        val, ts = _cache[key]
        if now - ts < ttl:
            return val
    val = fn()
    _cache[key] = (val, now)
    return val


# ---------------------------------------------------------------------------
# Price / fundamentals
# ---------------------------------------------------------------------------

def get_spot(ticker: str) -> float:
    def _fetch():
        t = yf.Ticker(ticker)
        info = t.fast_info
        price = getattr(info, "last_price", None) or getattr(info, "regularMarketPrice", None)
        if price is None:
            hist = t.history(period="2d")
            price = float(hist["Close"].iloc[-1]) if not hist.empty else float("nan")
        return float(price)
    return _cached(f"spot_{ticker}", _fetch)


def get_info(ticker: str) -> dict:
    return _cached(f"info_{ticker}", lambda: yf.Ticker(ticker).info, ttl=3600)


def get_history(ticker: str, period: str = "1y") -> pd.DataFrame:
    return _cached(f"hist_{ticker}_{period}",
                   lambda: yf.Ticker(ticker).history(period=period), ttl=600)


# ---------------------------------------------------------------------------
# Earnings
# ---------------------------------------------------------------------------

def days_to_earnings(ticker: str) -> int | None:
    """Returns calendar days to next earnings, or None if unknown."""
    try:
        t = yf.Ticker(ticker)
        cal = t.calendar
        if cal is not None and not cal.empty:
            # calendar is a DataFrame with columns as dates
            cols = [c for c in cal.columns if isinstance(c, datetime.datetime)]
            if cols:
                nxt = min(cols)
                delta = (nxt.date() - datetime.date.today()).days
                return max(delta, 0)
        # fallback: earnings_dates
        ed = t.earnings_dates
        if ed is not None and not ed.empty:
            future = ed[ed.index.date > datetime.date.today()]  # type: ignore[attr-defined]
            if not future.empty:
                return (future.index[0].date() - datetime.date.today()).days
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Option chains
# ---------------------------------------------------------------------------

def get_expirations(ticker: str) -> list[str]:
    return _cached(f"exps_{ticker}", lambda: list(yf.Ticker(ticker).options), ttl=300)


def get_option_chain(ticker: str, expiry: str) -> pd.DataFrame:
    """Returns the puts DataFrame for the given expiry with extra columns."""
    def _fetch():
        chain = yf.Ticker(ticker).option_chain(expiry)
        df = chain.puts.copy()
        df["expiry"] = expiry
        exp_dt = datetime.datetime.strptime(expiry, "%Y-%m-%d").date()
        df["dte"] = (exp_dt - datetime.date.today()).days
        df["mid"] = (df["bid"] + df["ask"]) / 2
        df["spread_pct"] = (df["ask"] - df["bid"]) / df["mid"].replace(0, np.nan)
        return df
    return _cached(f"chain_{ticker}_{expiry}", _fetch)


def best_expiry_for_tenor(expirations: list[str], target_dte: int,
                           tolerance: int = 10) -> str | None:
    """Pick the expiry closest to target_dte within ±tolerance days."""
    today = datetime.date.today()
    best, best_diff = None, 9999
    for exp in expirations:
        dte = (datetime.datetime.strptime(exp, "%Y-%m-%d").date() - today).days
        diff = abs(dte - target_dte)
        if diff < best_diff:
            best, best_diff = exp, diff
    return best if best_diff <= tolerance + 10 else best  # always return closest


# ---------------------------------------------------------------------------
# ATM IV (for IV Rank snapshots)
# ---------------------------------------------------------------------------

def get_atm_iv(ticker: str) -> float:
    """Approximate ATM IV from the nearest expiry ~30-DTE chain."""
    try:
        spot = get_spot(ticker)
        exps = get_expirations(ticker)
        expiry = best_expiry_for_tenor(exps, 30)
        if expiry is None:
            return float("nan")
        chain = get_option_chain(ticker, expiry)
        chain = chain[chain["impliedVolatility"] > 0]
        if chain.empty:
            return float("nan")
        chain = chain.copy()
        chain["strike_dist"] = (chain["strike"] - spot).abs()
        atm_row = chain.loc[chain["strike_dist"].idxmin()]
        return float(atm_row["impliedVolatility"])
    except Exception:
        return float("nan")


def snapshot_iv(ticker: str):
    """Store today's ATM IV for this ticker."""
    iv = get_atm_iv(ticker)
    if np.isnan(iv):
        return
    date_str = datetime.date.today().isoformat()
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO iv_snapshots(date, ticker, atm_iv) VALUES(?,?,?)",
            (date_str, ticker, iv)
        )


def get_iv_history(ticker: str, days: int = 252) -> list[float]:
    with _conn() as c:
        rows = c.execute(
            "SELECT atm_iv FROM iv_snapshots WHERE ticker=? ORDER BY date DESC LIMIT ?",
            (ticker, days)
        ).fetchall()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Watchlist helpers
# ---------------------------------------------------------------------------

DEFAULT_WATCHLIST = [
    ("IREN",  "IREN Ltd",               "AI data center",         "Growth",      5, "Wheel"),
    ("CIFR",  "Cipher Digital",         "Crypto / HPC",           "Speculative", 3, "Income"),
    ("NBIS",  "Nebius Group",           "AI data center",         "Growth",      3, "Income"),
    ("CRWV",  "CoreWeave",              "AI data center",         "Growth",      3, "Income"),
    ("CEG",   "Constellation Energy",   "Power / nuclear",        "Core",        5, "Wheel"),
    ("DGXX",  "Digi Power X",           "Energy / AI data center","Speculative", 3, "Income"),
    ("VRT",   "Vertiv",                 "Power / DC equip",       "Core",        5, "Wheel"),
    ("GEV",   "GE Vernova",             "Power / grid equip",     "Core",        5, "Wheel"),
    ("NVDA",  "NVIDIA",                 "AI compute / semis",     "Core",        5, "Wheel"),
    ("MU",    "Micron",                 "AI compute / semis",     "Core",        5, "Wheel"),
    ("AMD",   "Advanced Micro Devices", "AI compute / semis",     "Growth",      4, "Wheel"),
    ("GOOG",  "Alphabet",               "Comm services",          "Core",        3, "Income"),
    ("BB",    "BlackBerry",             "Software / security",    "Growth",      4, "Wheel"),
    ("LLY",   "Eli Lilly",              "Healthcare / peptides",  "Core",        5, "Wheel"),
    ("NVO",   "Novo Nordisk",           "Healthcare / peptides",  "Core",        5, "Wheel"),
    ("AMGN",  "Amgen",                  "Healthcare / pharma",    "Core",        3, "Income"),
    ("HIMS",  "Hims & Hers",            "Healthcare / telehealth","Growth",      3, "Income"),
    ("VKTX",  "Viking Therapeutics",    "Healthcare / peptides",  "Speculative", 2, "Income"),
    ("IBRX",  "ImmunityBio",            "Healthcare / biotech",   "Speculative", 1, "Income"),
]


def seed_watchlist():
    with _conn() as c:
        existing = c.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
        if existing == 0:
            for row in DEFAULT_WATCHLIST:
                c.execute(
                    """INSERT OR IGNORE INTO watchlist
                       (ticker, company, sector, bucket, conviction, target_delta_band)
                       VALUES (?,?,?,?,?,?)""",
                    row
                )


def reset_watchlist():
    """Wipe the watchlist and re-seed with the current defaults."""
    with _conn() as c:
        c.execute("DELETE FROM watchlist")
        for row in DEFAULT_WATCHLIST:
            c.execute(
                """INSERT INTO watchlist
                   (ticker, company, sector, bucket, conviction, target_delta_band)
                   VALUES (?,?,?,?,?,?)""",
                row
            )


def get_watchlist() -> pd.DataFrame:
    with _conn() as c:
        return pd.read_sql("SELECT * FROM watchlist ORDER BY ticker", c)


def upsert_watchlist_row(ticker, company, sector, bucket, conviction, delta_band):
    with _conn() as c:
        c.execute(
            """INSERT OR REPLACE INTO watchlist
               (ticker,company,sector,bucket,conviction,target_delta_band)
               VALUES(?,?,?,?,?,?)""",
            (ticker.upper(), company, sector, bucket, conviction, delta_band)
        )


def delete_watchlist_row(ticker: str):
    with _conn() as c:
        c.execute("DELETE FROM watchlist WHERE ticker=?", (ticker.upper(),))


# ---------------------------------------------------------------------------
# Positions helpers
# ---------------------------------------------------------------------------

def get_positions(status: str = "open") -> pd.DataFrame:
    with _conn() as c:
        return pd.read_sql(
            "SELECT * FROM positions WHERE status=? ORDER BY date_opened DESC",
            c, params=(status,)
        )


def add_position(date_opened, ticker, strategy, track, strike, expiry,
                 dte_open, contracts, premium_per_ct, signal_tag="", notes=""):
    with _conn() as c:
        c.execute(
            """INSERT INTO positions
               (date_opened,ticker,strategy,track,strike,expiry,dte_open,
                contracts,premium_per_ct,signal_tag,notes)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (date_opened, ticker.upper(), strategy, track, strike, expiry,
             dte_open, contracts, premium_per_ct, signal_tag, notes)
        )


def close_position(pos_id: int, realized_pnl: float):
    with _conn() as c:
        c.execute(
            "UPDATE positions SET status='closed', realized_pnl=? WHERE id=?",
            (realized_pnl, pos_id)
        )


# ---------------------------------------------------------------------------
# Income helpers
# ---------------------------------------------------------------------------

def get_income() -> pd.DataFrame:
    with _conn() as c:
        return pd.read_sql("SELECT * FROM income ORDER BY month", c)


def upsert_income(month: str, premium: float, closed_pnl: float,
                  assignment: float, hedge_cost: float):
    with _conn() as c:
        c.execute(
            """INSERT OR REPLACE INTO income(month,premium,closed_pnl,assignment,hedge_cost)
               VALUES(?,?,?,?,?)""",
            (month, premium, closed_pnl, assignment, hedge_cost)
        )


# ---------------------------------------------------------------------------
# Signals helpers
# ---------------------------------------------------------------------------

def add_signal(ticker: str, source: str, signal_type: str, timeframe: str):
    ts = datetime.datetime.utcnow().isoformat()
    with _conn() as c:
        c.execute(
            "INSERT INTO signals(ts,ticker,source,signal_type,timeframe) VALUES(?,?,?,?,?)",
            (ts, ticker.upper(), source, signal_type, timeframe)
        )


def get_signals(days: int = 30) -> pd.DataFrame:
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    with _conn() as c:
        return pd.read_sql(
            "SELECT * FROM signals WHERE ts >= ? ORDER BY ts DESC",
            c, params=(cutoff,)
        )
