"""
Shared data-fetching helpers for the public app.
All functions are @st.cache_data decorated.
No DB dependency — pure yfinance + session_state watchlist.
"""
import datetime
import sys, os
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf
from scipy.stats import norm

# ── Default watchlist ─────────────────────────────────────────────────────────
DEFAULT_WATCHLIST = [
    {"ticker": "IREN",  "company": "IREN Ltd",               "sector": "Data Centers & AI",    "bucket": "Growth",      "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "CIFR",  "company": "Cipher Digital",          "sector": "Data Centers & AI",    "bucket": "Speculative", "conviction": 3, "delta_band": "Income"},
    {"ticker": "NBIS",  "company": "Nebius Group",            "sector": "Data Centers & AI",    "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "CRWV",  "company": "CoreWeave",               "sector": "Data Centers & AI",    "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "CEG",   "company": "Constellation Energy",    "sector": "Energy & Power",       "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "DGXX",  "company": "Digi Power X",            "sector": "Energy & Power",       "bucket": "Speculative", "conviction": 3, "delta_band": "Income"},
    {"ticker": "VRT",   "company": "Vertiv",                  "sector": "Energy & Power",       "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "GEV",   "company": "GE Vernova",              "sector": "Energy & Power",       "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "NVDA",  "company": "NVIDIA",                  "sector": "Semiconductors",       "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "MU",    "company": "Micron",                  "sector": "Semiconductors",       "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "AMD",   "company": "Advanced Micro Devices",  "sector": "Semiconductors",       "bucket": "Core",        "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "GOOG",  "company": "Alphabet",                "sector": "Technology",           "bucket": "Core",        "conviction": 3, "delta_band": "Income"},
    {"ticker": "BB",    "company": "BlackBerry",              "sector": "Technology",           "bucket": "Growth",      "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "UBER",  "company": "Uber Technologies",       "sector": "Technology",           "bucket": "Core",        "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "LLY",   "company": "Eli Lilly",               "sector": "Healthcare",           "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "NVO",   "company": "Novo Nordisk",            "sector": "Healthcare",           "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "AMGN",  "company": "Amgen",                   "sector": "Healthcare",           "bucket": "Core",        "conviction": 3, "delta_band": "Income"},
    {"ticker": "HIMS",  "company": "Hims & Hers",             "sector": "Healthcare",           "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "VKTX",  "company": "Viking Therapeutics",     "sector": "Healthcare",           "bucket": "Speculative", "conviction": 2, "delta_band": "Income"},
    {"ticker": "IBRX",  "company": "ImmunityBio",             "sector": "Healthcare",           "bucket": "Speculative", "conviction": 1, "delta_band": "Income"},
    # ── Added 2026-06-18 from broker "Cash secured Puts" list ──────────────────
    # AI compute / semis
    {"ticker": "AVGO",  "company": "Broadcom",                "sector": "Semiconductors",       "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "MRVL",  "company": "Marvell Technology",      "sector": "Semiconductors",       "bucket": "Core",        "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "AXTI",  "company": "AXT Inc",                 "sector": "Semiconductors",       "bucket": "Speculative", "conviction": 2, "delta_band": "Income"},
    # Data centers / AI
    {"ticker": "PENG",  "company": "Penguin Solutions",       "sector": "Data Centers & AI",    "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "NUAI",  "company": "New Era Energy & Digital", "sector": "Data Centers & AI",    "bucket": "Speculative", "conviction": 2, "delta_band": "Income"},
    {"ticker": "OSS",   "company": "One Stop Systems",        "sector": "Data Centers & AI",    "bucket": "Speculative", "conviction": 1, "delta_band": "Income"},
    # Power / energy
    {"ticker": "VST",   "company": "Vistra",                  "sector": "Energy & Power",       "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "UUUU",  "company": "Energy Fuels (uranium)",  "sector": "Energy & Power",       "bucket": "Speculative", "conviction": 2, "delta_band": "Income"},
    {"ticker": "FLNC",  "company": "Fluence Energy",          "sector": "Energy & Power",       "bucket": "Speculative", "conviction": 2, "delta_band": "Income"},
    {"ticker": "TE",    "company": "T1 Energy (VERIFY)",      "sector": "Energy & Power",       "bucket": "Speculative", "conviction": 1, "delta_band": "Income"},
    # Big tech / software
    {"ticker": "AAPL",  "company": "Apple",                   "sector": "Technology",           "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "NOW",   "company": "ServiceNow (VERIFY PX)",  "sector": "Technology",           "bucket": "Core",        "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "RDDT",  "company": "Reddit",                  "sector": "Technology",           "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "ZETA",  "company": "Zeta Global",             "sector": "Technology",           "bucket": "Growth",      "conviction": 2, "delta_band": "Income"},
    {"ticker": "ADEA",  "company": "Adeia",                   "sector": "Technology",           "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "MGNI",  "company": "Magnite",                 "sector": "Technology",           "bucket": "Speculative", "conviction": 2, "delta_band": "Income"},
    {"ticker": "OPEN",  "company": "Opendoor Technologies",   "sector": "Technology",           "bucket": "Speculative", "conviction": 1, "delta_band": "Income"},
    {"ticker": "ONDS",  "company": "Ondas Holdings",          "sector": "Technology",           "bucket": "Speculative", "conviction": 1, "delta_band": "Income"},
    {"ticker": "OUST",  "company": "Ouster (lidar)",          "sector": "Technology",           "bucket": "Speculative", "conviction": 1, "delta_band": "Income"},
    {"ticker": "KEEL",  "company": "KEEL (VERIFY)",           "sector": "Technology",           "bucket": "Speculative", "conviction": 1, "delta_band": "Income"},
    # Quantum (binary, very high IV)
    {"ticker": "QBTS",  "company": "D-Wave Quantum",          "sector": "Quantum",              "bucket": "Speculative", "conviction": 2, "delta_band": "Income"},
    {"ticker": "RGTI",  "company": "Rigetti Computing",       "sector": "Quantum",              "bucket": "Speculative", "conviction": 2, "delta_band": "Income"},
    {"ticker": "QUBT",  "company": "Quantum Computing Inc",   "sector": "Quantum",              "bucket": "Speculative", "conviction": 1, "delta_band": "Income"},
    # Space & defense
    {"ticker": "KTOS",  "company": "Kratos Defense",          "sector": "Space & Defense",      "bucket": "Growth",      "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "RKLB",  "company": "Rocket Lab",              "sector": "Space & Defense",      "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "ASTS",  "company": "AST SpaceMobile",         "sector": "Space & Defense",      "bucket": "Speculative", "conviction": 2, "delta_band": "Income"},
    {"ticker": "SPCX",  "company": "SpaceX",                  "sector": "Space & Defense",      "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    # Financials
    {"ticker": "ICE",   "company": "Intercontinental Exch.",  "sector": "Financials",           "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "PLMR",  "company": "Palomar Holdings",        "sector": "Financials",           "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "INTR",  "company": "Inter & Co",              "sector": "Financials",           "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "PGY",   "company": "Pagaya Technologies",     "sector": "Financials",           "bucket": "Speculative", "conviction": 2, "delta_band": "Income"},
    {"ticker": "QXO",   "company": "QXO Inc",                 "sector": "Industrials",          "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    # Healthcare
    {"ticker": "HALO",  "company": "Halozyme Therapeutics",   "sector": "Healthcare",           "bucket": "Growth",      "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "OSCR",  "company": "Oscar Health",            "sector": "Healthcare",           "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "ARDX",  "company": "Ardelyx",                 "sector": "Healthcare",           "bucket": "Speculative", "conviction": 1, "delta_band": "Income"},
    # Crypto & digital assets (ETFs/proxies — selling puts = bullish crypto)
    {"ticker": "IBIT",  "company": "iShares Bitcoin Trust",   "sector": "Crypto & Digital",     "bucket": "Speculative", "conviction": 3, "delta_band": "Income"},
    {"ticker": "ETHA",  "company": "iShares Ethereum Trust",  "sector": "Crypto & Digital",     "bucket": "Speculative", "conviction": 2, "delta_band": "Income"},
    {"ticker": "GLXY",  "company": "Galaxy Digital",          "sector": "Crypto & Digital",     "bucket": "Speculative", "conviction": 2, "delta_band": "Income"},
    # ── Added 2026-06-25: CORE anchors to broaden tradable setups (on-theme,
    #    mega-cap, deep options) — addresses being under the Core target ──────────
    {"ticker": "MSFT",  "company": "Microsoft",               "sector": "Technology",           "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "META",  "company": "Meta Platforms",          "sector": "Technology",           "bucket": "Core",        "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "AMZN",  "company": "Amazon",                  "sector": "Technology",           "bucket": "Core",        "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "TSM",   "company": "Taiwan Semiconductor",    "sector": "Semiconductors",       "bucket": "Core",        "conviction": 5, "delta_band": "Wheel"},
    {"ticker": "ANET",  "company": "Arista Networks",         "sector": "Data Centers & AI",    "bucket": "Core",        "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "ORCL",  "company": "Oracle",                  "sector": "Data Centers & AI",    "bucket": "Core",        "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "ETN",   "company": "Eaton",                   "sector": "Energy & Power",       "bucket": "Core",        "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "ABBV",  "company": "AbbVie",                  "sector": "Healthcare",           "bucket": "Core",        "conviction": 4, "delta_band": "Wheel"},
    # ── Growth complements: liquid, on-theme, frequent setups ──────────────────
    {"ticker": "PLTR",  "company": "Palantir",                "sector": "Technology",           "bucket": "Core",        "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "DELL",  "company": "Dell Technologies",       "sector": "Data Centers & AI",    "bucket": "Growth",      "conviction": 3, "delta_band": "Wheel"},
    {"ticker": "SMCI",  "company": "Super Micro Computer",    "sector": "Data Centers & AI",    "bucket": "Growth",      "conviction": 2, "delta_band": "Income"},
    # ── Added 2026-06-25: premium machines + diversifiers (lower AI correlation) ─
    {"ticker": "TSLA",  "company": "Tesla",                   "sector": "Consumer",             "bucket": "Core",        "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "CRWD",  "company": "CrowdStrike",             "sector": "Technology",           "bucket": "Core",        "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "APP",   "company": "AppLovin",                "sector": "Technology",           "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "COIN",  "company": "Coinbase",                "sector": "Crypto & Digital",     "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "MA",    "company": "Mastercard",             "sector": "Financials",           "bucket": "Core",        "conviction": 4, "delta_band": "Income"},
    {"ticker": "JPM",   "company": "JPMorgan Chase",          "sector": "Financials",           "bucket": "Core",        "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "CAT",   "company": "Caterpillar",             "sector": "Industrials",          "bucket": "Core",        "conviction": 3, "delta_band": "Wheel"},
    {"ticker": "UNH",   "company": "UnitedHealth",            "sector": "Healthcare",           "bucket": "Core",        "conviction": 4, "delta_band": "Wheel"},
    {"ticker": "HOOD",  "company": "Robinhood",               "sector": "Financials",           "bucket": "Growth",      "conviction": 3, "delta_band": "Income"},
    {"ticker": "SOFI",  "company": "SoFi Technologies",       "sector": "Financials",           "bucket": "Growth",      "conviction": 2, "delta_band": "Income"},
    {"ticker": "XOM",   "company": "ExxonMobil",              "sector": "Energy & Power",       "bucket": "Core",        "conviction": 4, "delta_band": "Income"},
]

SECTORS = sorted(set(w["sector"] for w in DEFAULT_WATCHLIST))
TICKERS = [w["ticker"] for w in DEFAULT_WATCHLIST]

import db
import massive

def get_watchlist():
    """DB-backed when Supabase is configured (shared across PCs); else session.
    First DB run seeds the table from DEFAULT_WATCHLIST."""
    if db.configured():
        wl = db.load_watchlist()
        if wl:
            return wl
        try:
            db.seed_watchlist(DEFAULT_WATCHLIST)
        except Exception:
            pass
        return DEFAULT_WATCHLIST
    if "watchlist" not in st.session_state:
        st.session_state["watchlist"] = {w["ticker"]: w for w in DEFAULT_WATCHLIST}
    return list(st.session_state["watchlist"].values())

def add_to_watchlist(ticker, company="", sector="Technology", bucket="Growth", conviction=3, delta_band="Income"):
    item = {"ticker": ticker.upper(), "company": company, "sector": sector,
            "bucket": bucket, "conviction": conviction, "delta_band": delta_band}
    if db.configured():
        try:
            db.upsert_watchlist_item(item)
            return
        except Exception as e:
            st.warning(f"DB write failed — added for this session only. ({e})")
    if "watchlist" not in st.session_state:
        st.session_state["watchlist"] = {w["ticker"]: w for w in DEFAULT_WATCHLIST}
    st.session_state["watchlist"][ticker.upper()] = item

def remove_from_watchlist(ticker):
    if db.configured():
        try:
            db.delete_watchlist_item(ticker)
            return
        except Exception as e:
            st.warning(f"DB delete failed. ({e})")
    if "watchlist" in st.session_state:
        st.session_state["watchlist"].pop(ticker.upper(), None)

# ── Math ──────────────────────────────────────────────────────────────────────
def _bs_delta(spot, strike, iv, dte, rf, kind):
    """Vectorized Black-Scholes delta. `strike`/`iv` may be scalars or arrays.
    Returns a float for scalar input, a numpy array otherwise."""
    strike = np.asarray(strike, dtype=float)
    iv     = np.asarray(iv, dtype=float)
    scalar = strike.ndim == 0 and iv.ndim == 0
    T = dte / 365.0
    with np.errstate(divide="ignore", invalid="ignore"):
        d1  = (np.log(spot/strike) + (rf + 0.5*iv**2)*T) / (iv*np.sqrt(T))
        out = np.abs(norm.cdf(d1) - 1) if kind == "put" else norm.cdf(d1)
    invalid = (dte <= 0) | (iv <= 0) | (spot <= 0) | (strike <= 0)
    out = np.where(invalid, np.nan, out)
    return float(out) if scalar else out

def bs_put_delta(spot, strike, iv, dte, rf=0.053):
    return _bs_delta(spot, strike, iv, dte, rf, "put")

def bs_call_delta(spot, strike, iv, dte, rf=0.053):
    return _bs_delta(spot, strike, iv, dte, rf, "call")

def bs_price(spot, strike, iv, dte, rf=0.053, kind="put"):
    """Black-Scholes European option price (scalar).
    Falls back to intrinsic value when expired or IV is unusable."""
    if spot <= 0 or strike <= 0:
        return float("nan")
    if dte <= 0 or iv <= 0:
        return max(strike - spot, 0) if kind == "put" else max(spot - strike, 0)
    T  = dte / 365.0
    sq = iv * np.sqrt(T)
    d1 = (np.log(spot / strike) + (rf + 0.5 * iv * iv) * T) / sq
    d2 = d1 - sq
    if kind == "put":
        return float(strike * np.exp(-rf * T) * norm.cdf(-d2) - spot * norm.cdf(-d1))
    return float(spot * norm.cdf(d1) - strike * np.exp(-rf * T) * norm.cdf(d2))

def moneyness(spot, strike, is_put=True):
    b = 0.01 * spot
    if is_put:
        if strike < spot - b: return "OTM"
        if strike > spot + b: return "ITM"
    else:
        if strike > spot + b: return "OTM"
        if strike < spot - b: return "ITM"
    return "ATM"

def ann_yield(prem, strike, dte):
    return (prem/strike)*(365/dte) if strike and dte else float("nan")

def ann_roll(net_credit, strike_new, added_dte):
    return (net_credit/strike_new)*(365/added_dte) if strike_new and added_dte else float("nan")

# ── Realized vol percentile (IV Rank proxy) ───────────────────────────────────
def rv_percentile(hist):
    """Use 1-year realized vol percentile as IV Rank proxy."""
    if hist.empty or len(hist) < 60: return 0.5
    ret = hist["Close"].pct_change().dropna()
    rv = ret.rolling(21).std() * np.sqrt(252)
    rv = rv.dropna()
    if len(rv) < 10: return 0.5
    lo, hi = rv.min(), rv.max()
    if hi == lo: return 0.5
    return float(np.clip((rv.iloc[-1] - lo) / (hi - lo), 0, 1))

# ── Data fetching ─────────────────────────────────────────────────────────────
# NOTE on the caching pattern below: the cached inner function RAISES on
# failure (exceptions are never cached by st.cache_data), and the thin outer
# wrapper converts that to NaN/None. A transient Yahoo block therefore isn't
# stored for the TTL — the next call retries immediately after recovery.
@st.cache_data(ttl=300, show_spinner=False)
def _spot_cached(tkr):
    if massive.available():
        try:
            return massive.spot(tkr)
        except Exception:
            pass                                # fall back to Yahoo
    t = yf.Ticker(tkr)
    info = t.fast_info
    p = getattr(info, "last_price", None) or getattr(info, "regularMarketPrice", None)
    if p is None:
        h = t.history(period="2d")
        if h.empty:
            raise RuntimeError("no spot data")
        p = float(h["Close"].iloc[-1])
    p = float(p)
    if np.isnan(p):
        raise RuntimeError("no spot data")
    return p

def fetch_spot(tkr):
    try:
        return _spot_cached(tkr)
    except Exception:
        return float("nan")

@st.cache_data(ttl=600, show_spinner=False)
def _hist_cached(tkr):
    h = yf.Ticker(tkr).history(period="1y")
    if h is None or h.empty:
        raise RuntimeError("no history")     # failures are never cached
    return h

def fetch_hist(tkr):
    try:
        return _hist_cached(tkr)
    except Exception:
        return pd.DataFrame()

def _as_date(d):
    """Coerce datetime.date / datetime.datetime / pandas.Timestamp -> date."""
    if d is None:
        return None
    if hasattr(d, "date") and not isinstance(d, datetime.date):
        return d.date()                 # datetime / Timestamp
    if isinstance(d, datetime.date):
        return d                        # already a date
    try:
        return pd.Timestamp(d).date()   # strings, numpy datetimes, etc.
    except Exception:
        return None

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_earnings(tkr):
    """Days until the next earnings date (>=0), or None if unavailable."""
    today = datetime.date.today()
    candidates = []
    try:
        t = yf.Ticker(tkr)

        # 1) calendar (dict in modern yfinance, sometimes a DataFrame)
        try:
            cal = t.calendar
            if isinstance(cal, dict):
                for d in cal.get("Earnings Date", []) or []:
                    dd = _as_date(d)
                    if dd: candidates.append(dd)
            elif cal is not None and hasattr(cal, "columns"):
                for col in cal.columns:
                    dd = _as_date(col)
                    if dd: candidates.append(dd)
        except Exception:
            pass

        # 2) earnings_dates table (covers past + future)
        try:
            ed = t.earnings_dates
            if ed is not None and not ed.empty:
                for ts in ed.index:
                    dd = _as_date(ts)
                    if dd: candidates.append(dd)
        except Exception:
            pass

        # 3) get_earnings_dates fallback
        if not candidates:
            try:
                ed2 = t.get_earnings_dates(limit=8)
                if ed2 is not None and not ed2.empty:
                    for ts in ed2.index:
                        dd = _as_date(ts)
                        if dd: candidates.append(dd)
            except Exception:
                pass
    except Exception:
        return None

    # Nearest future date (today counts as 0)
    future = sorted(d for d in candidates if d >= today)
    if future:
        return (future[0] - today).days
    return None

@st.cache_data(ttl=3600, show_spinner=False)   # expiry lists barely change intraday
def _expirations_cached(tkr):
    if massive.available():
        try:
            return massive.expirations(tkr)
        except Exception:
            pass                                # fall back to Yahoo
    exps = list(yf.Ticker(tkr).options)
    if not exps:
        raise RuntimeError("no expirations")   # failures are never cached
    return exps

def fetch_expirations(tkr):
    try:
        return _expirations_cached(tkr)
    except Exception:
        return []

def is_third_friday(d: datetime.date) -> bool:
    """True if date is the 3rd Friday of its month (standard monthly option expiry)."""
    return d.weekday() == 4 and 15 <= d.day <= 21

@st.cache_data(ttl=300, show_spinner=False)
def _chain_cached(tkr, target_dte, option_type, monthly_only, prefer_quotes=False):
    exps = _expirations_cached(tkr)             # Massive when configured, else Yahoo
    today = datetime.date.today()

    # For longer tenors, restrict to standard monthly contracts (3rd Friday),
    # which carry the deepest liquidity. Fall back to all if none qualify.
    candidates = exps
    if monthly_only:
        monthlies = [e for e in exps
                     if is_third_friday(datetime.datetime.strptime(e, "%Y-%m-%d").date())]
        if monthlies:
            candidates = monthlies

    best = min(candidates, key=lambda e: abs(
        (datetime.datetime.strptime(e, "%Y-%m-%d").date() - today).days - target_dte))
    dte = (datetime.datetime.strptime(best, "%Y-%m-%d").date() - today).days

    chain = _get_chain_any(tkr, best, option_type, prefer_quotes)
    chain = chain.copy()
    chain["dte"] = dte
    return chain, best, dte

def fetch_chain(tkr, target_dte, option_type="put", monthly_only=False, prefer_quotes=False):
    try:
        return _chain_cached(tkr, target_dte, option_type, monthly_only, prefer_quotes)
    except Exception:
        return None, None, None

def us_market_open_now() -> bool:
    """US options RTH (Mon-Fri 9:30-16:00 ET). Holidays aren't special-cased:
    on a holiday Yahoo quotes are 0/0, so marking falls through to Massive's
    close anyway — self-healing."""
    now = datetime.datetime.now(ZoneInfo("America/New_York"))
    return now.weekday() < 5 and datetime.time(9, 30) <= now.time() < datetime.time(16, 0)

def _massive_chain_or_none(tkr, expiry, option_type):
    if not massive.available():
        return None
    try:
        m, _spot = massive.chain(tkr, expiry, option_type)
        return m if m["mid"].notna().any() else None
    except Exception:
        return None

def _yahoo_chain(tkr, expiry, option_type):
    raw = yf.Ticker(tkr).option_chain(expiry)
    y = (raw.puts if option_type == "put" else raw.calls).copy()
    if y is None or y.empty:
        raise RuntimeError("empty chain")
    y["mid"] = (y["bid"] + y["ask"]) / 2
    y.loc[y["mid"] <= 0, "mid"] = np.nan
    y["spread_pct"] = (y["ask"] - y["bid"]) / y["mid"]
    return y

def _get_chain_any(tkr, expiry, option_type, prefer_quotes=False):
    """One chain, one fetch, source by purpose:
    - prefer_quotes=False (Portfolio marks, screeners): Massive first — day
      close pricing (works after hours) + real IV/Greeks; Yahoo fallback.
    - prefer_quotes=True (Option Finder, Roll Finder — pages that PRICE
      ORDERS and need bid/ask): Yahoo first; Massive close as fallback so
      the tools still work when Yahoo is down or after hours.
    Raises when nothing usable (never cached as failure)."""
    if prefer_quotes:
        try:
            return _yahoo_chain(tkr, expiry, option_type)
        except Exception:
            m = _massive_chain_or_none(tkr, expiry, option_type)
            if m is not None:
                return m
            raise
    m = _massive_chain_or_none(tkr, expiry, option_type)
    if m is not None:
        return m
    return _yahoo_chain(tkr, expiry, option_type)

@st.cache_data(ttl=120, show_spinner=False)
def _chain_exact_cached(tkr, expiry, option_type, prefer_quotes=False):
    return _get_chain_any(tkr, expiry, option_type, prefer_quotes)

def fetch_chain_exact(tkr, expiry, option_type="put", prefer_quotes=False):
    """Chain for one EXACT expiry (unlike fetch_chain, which snaps to a target
    DTE). Used by the Roll Finder, where the current leg's expiry is fixed."""
    try:
        return _chain_exact_cached(tkr, expiry, option_type, prefer_quotes)
    except Exception:
        return None

def prefetch(tickers, dtes=(35,), option_type="put"):
    """Warm the per-ticker caches concurrently so the screener's main loop
    hits warm caches instead of blocking on sequential network I/O.
    st.cache_data is process-wide and thread-safe, so threads populate the
    same cache the main thread reads."""
    def warm(tkr):
        try:
            fetch_spot(tkr)
            fetch_hist(tkr)
            fetch_earnings(tkr)
            for d in dtes:
                fetch_chain(tkr, d, option_type)
        except Exception:
            pass
    if not tickers:
        return
    with ThreadPoolExecutor(max_workers=min(8, len(tickers))) as ex:
        list(ex.map(warm, tickers))

def prefetch_marks(tickers, chain_keys):
    """Warm the Portfolio's caches concurrently: spots for `tickers` and
    per-(tkr, expiry, opt_type) chains for `chain_keys`. The marking loop then
    reads warm caches instead of doing serial network calls."""
    def warm_spot(t):
        try: fetch_spot(t)
        except Exception: pass
    mkt_open = us_market_open_now()
    def warm_chain(k):
        try: fetch_chain_exact(*k, prefer_quotes=mkt_open)
        except Exception: pass
    jobs = [(warm_spot, t) for t in set(tickers)] + \
           [(warm_chain, k) for k in set(chain_keys)]
    if not jobs:
        return
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda j: j[0](j[1]), jobs))

def trend_label_score(hist):
    if hist.empty or len(hist) < 20: return "N/A", 2.5
    c = hist["Close"]
    e50 = c.ewm(span=50, adjust=False).mean().iloc[-1]
    e200 = c.ewm(span=200, adjust=False).mean().iloc[-1]
    p = c.iloc[-1]
    if p > e50 > e200: return "UP", 5.0
    if p > e200:       return "UP (WEAK)", 3.5
    if p < e50 < e200: return "DOWN", 1.0
    return "NEUTRAL", 2.5

def score_strikes(sub, target_delta, weights):
    """Add a 0-100 'score' column balancing yield, cushion, delta-fit, liquidity.
    Same logic the Option Finder uses. `sub` needs columns:
    ann_yield, cushion_pct, delta, spread_pct."""
    def _minmax(s):
        s = s.astype(float)
        rng = s.max() - s.min()
        if rng == 0 or np.isnan(rng):
            return pd.Series(1.0, index=s.index)
        return (s - s.min()) / rng
    sc_yield   = _minmax(sub["ann_yield"])
    sc_cushion = _minmax(sub["cushion_pct"])
    sc_delta   = 1 - _minmax((sub["delta"] - target_delta).abs())
    sc_liq     = 1 - _minmax(sub["spread_pct"].fillna(sub["spread_pct"].max()))
    return (weights["yield"]   * sc_yield   +
            weights["cushion"] * sc_cushion +
            weights["delta"]   * sc_delta   +
            weights["liq"]     * sc_liq) * 100

def best_put(tkr, delta_band, target_dte):
    # Band bounds + scoring weights match the Option Finder
    if delta_band == "Income":
        lo, hi, target = 0.15, 0.30, 0.225
        weights = {"yield":0.25, "cushion":0.35, "delta":0.25, "liq":0.15}
    else:  # Wheel
        lo, hi, target = 0.30, 0.45, 0.375
        weights = {"yield":0.40, "cushion":0.25, "delta":0.20, "liq":0.15}

    spot = fetch_spot(tkr)
    chain, expiry, dte = fetch_chain(tkr, target_dte, "put")
    if chain is None or chain.empty: return {}
    chain = chain[chain["impliedVolatility"] > 0].copy()
    chain["delta"] = bs_put_delta(spot, chain["strike"].values,
                                  chain["impliedVolatility"].values, dte)

    # Restrict to the band; fall back to a wider window only if empty
    sub = chain[(chain["delta"] >= lo) & (chain["delta"] <= hi)].copy()
    if sub.empty:
        sub = chain[(chain["delta"] >= lo*0.5) & (chain["delta"] <= hi*1.8)].copy()
    if sub.empty:
        sub = chain.copy()

    # Enrich for scoring (vectorized)
    sub["mid"]         = sub["mid"].fillna(sub["bid"])
    sub["ann_yield"]   = (sub["mid"] / sub["strike"]) * (365.0 / dte)
    sub["cushion_pct"] = (spot - sub["strike"]) / spot if spot else np.nan
    if "spread_pct" not in sub.columns:
        sub["spread_pct"] = (sub["ask"] - sub["bid"]) / sub["mid"].replace(0, np.nan)

    # Highest-scoring strike in the band
    sub["score"] = score_strikes(sub, target, weights)
    row = sub.loc[sub["score"].idxmax()]

    prem   = float(row["mid"]) if not np.isnan(row["mid"]) else float(row["bid"])
    strike = float(row["strike"])
    sp = float((row["ask"]-row["bid"])/row["mid"]) if row["mid"] > 0 else float("nan")
    return {"expiry": expiry, "dte": dte, "strike": strike,
            "delta": round(float(row["delta"]), 3),
            "iv": round(float(row["impliedVolatility"]), 4),
            "premium": round(prem, 2),
            "ann_yield": round(ann_yield(prem, strike, dte), 4),
            "cushion": round((spot-strike)/spot if spot else float("nan"), 4),
            "breakeven": round(strike - prem, 2),
            "oi": int(row.get("openInterest", 0) or 0),
            "spread_pct": round(sp, 3),
            "score": round(float(row["score"]), 1)}

def best_call(tkr, target_delta, target_dte):
    """Best covered call — scores OTM calls in a band around target_delta.
    Same scoring engine as puts: upside-room sits in the 'cushion' slot."""
    weights = {"yield":0.40, "cushion":0.20, "delta":0.25, "liq":0.15}
    spot = fetch_spot(tkr)
    chain, expiry, dte = fetch_chain(tkr, target_dte, "call")
    if chain is None or chain.empty: return {}
    chain = chain[chain["impliedVolatility"] > 0].copy()
    otm = chain[chain["strike"] > spot * 0.99].copy()
    if otm.empty: otm = chain.copy()
    otm["delta"] = bs_call_delta(spot, otm["strike"].values,
                                 otm["impliedVolatility"].values, dte)
    # Band around the track's target delta (±0.12); widen if empty
    band = otm[(otm["delta"] >= target_delta - 0.12) &
               (otm["delta"] <= target_delta + 0.12)].copy()
    if band.empty:
        band = otm.copy()

    band["mid"]         = band["mid"].fillna(band["bid"])
    band["ann_yield"]   = (band["mid"] / spot) * (365.0 / dte)   # yield on stock value
    band["cushion_pct"] = (band["strike"] - spot) / spot          # upside room
    if "spread_pct" not in band.columns:
        band["spread_pct"] = (band["ask"] - band["bid"]) / band["mid"].replace(0, np.nan)

    band["score"] = score_strikes(band, target_delta, weights)
    row = band.loc[band["score"].idxmax()]
    prem = float(row["mid"]) if not np.isnan(row["mid"]) else float(row["bid"])
    strike = float(row["strike"])
    sp = float((row["ask"]-row["bid"])/row["mid"]) if row["mid"] > 0 else float("nan")
    return {"expiry": expiry, "dte": dte, "strike": strike,
            "delta": round(float(row["delta"]), 3),
            "iv": round(float(row["impliedVolatility"]), 4),
            "premium": round(prem, 2),
            "ann_yield": round(ann_yield(prem, spot, dte), 4),  # yield on stock value
            "cushion": round((strike - spot)/spot, 4),          # upside cap (unified slot)
            "upside_cap": round((strike - spot)/spot, 4),
            "breakeven_up": round(spot + prem, 2),
            "oi": int(row.get("openInterest", 0) or 0),
            "spread_pct": round(sp, 3),
            "score": round(float(row["score"]), 1)}

def best_bear_call_spread(tkr, short_delta, spread_width_pct, target_dte):
    """
    Bear call spread: sell a call near short_delta, buy one ~spread_width_pct higher.
    Scores candidate short strikes by ROC / delta-fit / liquidity and picks best.
    """
    spot = fetch_spot(tkr)
    chain, expiry, dte = fetch_chain(tkr, target_dte, "call")
    if chain is None or chain.empty: return {}
    chain = chain[chain["impliedVolatility"] > 0].copy()
    chain["mid"] = chain["mid"].fillna(chain["bid"])
    otm = chain[chain["strike"] > spot * 0.99].copy()
    if otm.empty: return {}
    otm["delta"] = bs_call_delta(spot, otm["strike"].values,
                                 otm["impliedVolatility"].values, dte)
    band = otm[(otm["delta"] >= short_delta - 0.12) &
               (otm["delta"] <= short_delta + 0.12)].copy()
    if band.empty:
        band = otm.copy()

    cands = []
    for _, sr in band.iterrows():
        sk  = float(sr["strike"])
        sp_ = float(sr["mid"])
        lc  = chain[chain["strike"] >= sk * (1 + spread_width_pct)]
        if lc.empty:
            continue
        lr  = lc.iloc[0]
        lk  = float(lr["strike"]); lp = float(lr["mid"])
        net = sp_ - lp
        width = lk - sk
        ml  = width - net
        if ml <= 0:
            continue
        cands.append({
            "short_strike": sk, "long_strike": lk,
            "short_delta": float(sr["delta"]),
            "short_iv": float(sr["impliedVolatility"]),
            "net_credit": net, "spread_width": width, "max_loss": ml,
            "roc": net / ml,
            "spread_pct": float((sr["ask"]-sr["bid"])/sp_) if sp_ > 0 else np.nan,
            "oi": int(sr.get("openInterest", 0) or 0),
        })
    if not cands:
        return {}
    cdf = pd.DataFrame(cands)
    # Reuse the scoring engine: ROC in the yield slot, ROC again as "cushion"
    # (reward capital efficiency), delta-fit to the short target, liquidity.
    cdf["ann_yield"]   = cdf["roc"]
    cdf["cushion_pct"] = cdf["roc"]
    cdf["delta"]       = cdf["short_delta"]
    weights = {"yield":0.45, "cushion":0.15, "delta":0.25, "liq":0.15}
    cdf["score"] = score_strikes(cdf, short_delta, weights)
    row = cdf.loc[cdf["score"].idxmax()]

    net_credit = round(float(row["net_credit"]), 2)
    max_loss   = round(float(row["max_loss"]), 2)
    roc        = round(float(row["roc"]), 4)
    return {"expiry": expiry, "dte": dte,
            "short_strike": float(row["short_strike"]), "long_strike": float(row["long_strike"]),
            "short_delta": round(float(row["short_delta"]), 3),
            "short_iv": round(float(row["short_iv"]), 4),
            "net_credit": net_credit,
            "spread_width": round(float(row["spread_width"]), 2),
            "max_loss": max_loss,
            "breakeven": round(float(row["short_strike"]) + net_credit, 2),
            "roc": roc,
            "ann_roc": round(roc * 365/dte, 4) if dte > 0 else float("nan"),
            "oi": int(row["oi"]),
            "spread_pct": round(float(row["spread_pct"]), 3) if not np.isnan(row["spread_pct"]) else None,
            "score": round(float(row["score"]), 1)}

@st.cache_data(ttl=60, show_spinner=False)  # 1-min cache — live option prices
def _option_live_cached(tkr: str, strike: float, expiry: str, option_type: str,
                        market_open: bool = False):
    # Raises on FETCH failure (not cached); returns (nan, nan) for the
    # legitimate "no usable quote" states, which ARE cached for stability.
    # Reuses the 120s-cached per-expiry chain, so marking N positions on the
    # same ticker+expiry costs ONE chain fetch instead of N.
    # Market open -> prefer live quote-mids (Yahoo); closed -> Massive close.
    chain = fetch_chain_exact(tkr, expiry, option_type, prefer_quotes=market_open)
    if chain is None:
        raise RuntimeError("chain unavailable")     # fetch failed -> not cached
    if chain.empty:
        return float("nan"), float("nan")
    chain = chain.copy()
    chain["dist"] = (chain["strike"] - strike).abs()
    row = chain.loc[chain["dist"].idxmin()]
    # The exact strike we hold must actually be listed — don't snap to a far
    # strike (e.g. SPCX has no 150 put, lowest is 162.5). A bogus mark would
    # corrupt unrealized P&L and NAV. Reject if nearest strike is too far.
    tol = max(0.015 * strike, 0.50)
    if float(row["dist"]) > tol:
        return float("nan"), float("nan")
    # The chain's mid is already the best available price for its source:
    # NBBO midpoint (quote plans), Massive day close (Starter — valid after
    # hours too), or Yahoo bid/ask mid. No mid -> leave the position flat.
    mid = float(row["mid"]) if "mid" in row.index else float("nan")
    if np.isnan(mid) or mid <= 0:
        return float("nan"), float("nan")
    return mid, float(row["impliedVolatility"])

def fetch_option_live(tkr: str, strike: float, expiry: str, option_type: str = "put"):
    """(current_mid, current_iv) for a specific contract — marks the Portfolio."""
    try:
        return _option_live_cached(tkr, strike, expiry, option_type,
                                   us_market_open_now())
    except Exception:
        return float("nan"), float("nan")


def compute_book_pnl(trades):
    """(realized, unrealized) P&L across the whole book — powers NAV.
    Realized = Σ closed REALIZED PNL. Unrealized marks open positions at live
    mid (options) / spot (stock). Stock multiplier 1, options 100."""
    import pandas as _pd
    if trades is None or trades.empty:
        return 0.0, 0.0
    realized = _pd.to_numeric(trades.get("REALIZED PNL"), errors="coerce").fillna(0).sum()

    unreal = 0.0
    open_t = trades[trades["STATUS"] == "OPEN"]
    for _, t in open_t.iterrows():
        strat = str(t["STRATEGY"])
        ctrs  = int(t["CONTRACTS"]) if _pd.notna(t["CONTRACTS"]) else 0
        prem  = float(t["PREMIUM / CREDIT"]) if _pd.notna(t["PREMIUM / CREDIT"]) else 0.0
        tkr   = str(t["TICKER"])
        # Manual mark (typed from the broker) beats the live feed
        mmark = None
        if "MANUAL MARK" in t and _pd.notna(t.get("MANUAL MARK")) and t.get("MANUAL MARK"):
            mmark = float(t["MANUAL MARK"])
            if mmark <= 0:
                mmark = None
        if strat == "Long Stock":
            try:
                spot = mmark if mmark else fetch_spot(tkr)
                if not np.isnan(spot) and prem > 0:
                    unreal += (spot - prem) * ctrs
            except Exception:
                pass
            continue
        strike = float(t["SHORT STRIKE"]) if _pd.notna(t["SHORT STRIKE"]) else 0.0
        expiry = str(t["EXPIRY"])
        if strike <= 0 or expiry in ("nan", "None", ""):
            continue
        is_short = strat not in ("Long Put (Hedge)", "Long Call")
        opt = "put" if "Put" in strat else "call"
        if mmark:
            mid = mmark
        else:
            try:
                mid, _ = fetch_option_live(tkr, strike, expiry, opt)
            except Exception:
                mid = float("nan")
        if np.isnan(mid):
            continue
        unreal += (prem - mid) * 100 * ctrs if is_short else (mid - prem) * 100 * ctrs
    return float(realized), float(unreal)


def score_put(ivr, ann_y, oi, sp, earn, dte_t, tech_s, conv):
    ivr_s = 1 + ivr * 4
    yld_s = (5 if ann_y >= 0.40 else 4 if ann_y >= 0.25 else 3 if ann_y >= 0.15 else 2 if ann_y >= 0.08 else 1) if not np.isnan(ann_y) else 1
    liq_s = max(1, min(5, 3 + (1 if oi > 5000 else -1 if oi < 300 else 0) +
                       (1 if not np.isnan(sp) and sp < 0.03 else -1 if not np.isnan(sp) and sp > 0.10 else 0)))
    earn_s = 5 if earn is None or earn > dte_t+5 else 4 if earn > dte_t else 2 if earn > 7 else 1
    sc = 0.30*ivr_s + 0.25*yld_s + 0.15*liq_s + 0.10*earn_s + 0.10*tech_s + 0.10*float(conv)
    # Manual rule: trade only names scoring >= 4 (Put-Selling Prospect, OPS step 1)
    vd = "TRADE" if sc >= 4.0 else ("WATCH" if sc >= 3.0 else "PASS")
    return round(sc, 2), vd
