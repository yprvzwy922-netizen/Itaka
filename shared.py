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
import book as bk
# Black-Scholes + the US trading date live in book.py (shared with the scripts);
# re-exported here so `from shared import bs_price` etc. keeps working.
from book import _bs_delta, bs_put_delta, bs_call_delta, bs_price, today_et  # noqa: F401

from watchlist import DEFAULT_WATCHLIST, SECTORS  # noqa: E402,F401  (one shared copy)
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
    """Coerce datetime.date / datetime.datetime / pandas.Timestamp / str -> date.
    IMPORTANT: datetime.datetime AND pd.Timestamp are subclasses of datetime.date,
    so check datetime FIRST and call .date() — otherwise a Timestamp falls through
    unchanged and a later `Timestamp >= date` comparison raises under modern
    pandas ('Cannot compare Timestamp with datetime.date')."""
    if d is None:
        return None
    if isinstance(d, datetime.datetime):    # datetime.datetime AND pd.Timestamp
        return d.date()
    if isinstance(d, datetime.date):        # a pure date already
        return d
    try:
        return pd.Timestamp(d).date()       # strings, numpy datetimes, etc.
    except Exception:
        return None

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_earnings(tkr):
    """Days until the next earnings date (>=0), or None if unavailable."""
    today = today_et()
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
    today = today_et()

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


def sector_map():
    """ticker -> watchlist entry (sector / bucket): the live DB list over the
    code's defaults, so names not yet synced to the DB still resolve."""
    m = {w["ticker"]: w for w in DEFAULT_WATCHLIST}
    m.update({w["ticker"]: w for w in get_watchlist()})
    return m


def build_book(trades):
    """The open book priced with the live, cached feeds (book.build_book) —
    the same pricing the Portfolio page, the Performance headline and the
    pre-trade check all use. Warms every spot + chain concurrently first."""
    if trades is None or trades.empty:
        return pd.DataFrame()
    open_t = trades[trades["STATUS"] == "OPEN"]
    keys = [(str(t["TICKER"]), str(t["EXPIRY"]), bk.option_kind(t["STRATEGY"]))
            for _, t in open_t.iterrows()
            if not bk.is_stock(t["STRATEGY"]) and pd.notna(t["SHORT STRIKE"])
            and str(t["EXPIRY"]) not in ("nan", "None", "")]
    prefetch_marks(open_t["TICKER"].astype(str).tolist(), keys)
    return bk.build_book(open_t, fetch_spot, fetch_option_live, fetch_earnings, sector_map())


def fund_nav(trades, book):
    """NAV = net cash flows (deposits − withdrawals) + realized + unrealized,
    and NAV per unit (units from the cash flows' units_delta)."""
    flows = db.load_cash_flows()
    num = lambda c: pd.to_numeric(flows[c], errors="coerce").sum() if not flows.empty else 0.0
    contributed, units = float(num("amount")), float(num("units_delta"))
    realized = float(pd.to_numeric(trades["REALIZED PNL"], errors="coerce").fillna(0).sum()) if not trades.empty else 0.0
    unreal = float(pd.to_numeric(book["UNREAL PNL"], errors="coerce").sum()) if not book.empty else 0.0
    nav = contributed + realized + unreal
    return {"contributed": contributed, "units": units, "realized": realized, "unreal": unreal,
            "nav": nav, "npu": nav / units if units > 0 else None}


def compute_book_pnl(trades):
    """(realized, unrealized) P&L across the whole book — powers the NAV on the
    Performance page. Same pricing as the Portfolio page (one shared book)."""
    if trades is None or trades.empty:
        return 0.0, 0.0
    realized = pd.to_numeric(trades.get("REALIZED PNL"), errors="coerce").fillna(0).sum()
    b = build_book(trades)
    unreal = pd.to_numeric(b["UNREAL PNL"], errors="coerce").sum() if not b.empty else 0.0
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
