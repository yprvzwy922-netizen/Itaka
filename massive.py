"""
Massive.com (formerly Polygon.io) data adapter — options chains, IV, Greeks.

Used automatically by shared.py when MASSIVE_API_KEY exists in st.secrets;
everything falls back to yfinance otherwise. Functions RAISE on failure so
callers' no-failure-caching pattern works unchanged.
"""
import time

import numpy as np
import pandas as pd
import requests
import streamlit as st

BASE = "https://api.massive.com"

# Circuit breaker: after a few consecutive network failures, stop trying
# Massive for a cooldown so pages don't grind through serial timeouts.
_FAILS = 0
_MUTE_UNTIL = 0.0


def _key() -> str:
    try:
        return str(st.secrets.get("MASSIVE_API_KEY", "") or "")
    except Exception:
        return ""


def configured() -> bool:
    return bool(_key())


def available() -> bool:
    """Configured AND not in the failure cooldown — use this before calls."""
    return configured() and time.time() >= _MUTE_UNTIL


def _get(path_or_url, params=None):
    global _FAILS, _MUTE_UNTIL
    p = dict(params or {})
    p["apiKey"] = _key()
    url = path_or_url if path_or_url.startswith("http") else f"{BASE}{path_or_url}"
    try:
        r = requests.get(url, params=p, timeout=6)
        r.raise_for_status()
    except Exception:
        _FAILS += 1
        if _FAILS >= 3:
            _MUTE_UNTIL = time.time() + 120     # mute Massive for 2 minutes
        raise
    _FAILS = 0
    return r.json()


def _snapshot_results(tkr, params, max_pages=8):
    """Paginated option-chain snapshot for an underlying. Hard page cap: one
    expiry+type fits in 1-2 pages of 250 — anything more means runaway
    pagination (a limit=1 request returns a next_url for EVERY contract)."""
    data = _get(f"/v3/snapshot/options/{tkr.upper()}", params)
    results = list(data.get("results", []))
    pages = 1
    while data.get("next_url") and pages < max_pages:
        data = _get(data["next_url"])
        results += data.get("results", [])
        pages += 1
    return results


def chain(tkr: str, expiry: str, option_type: str = "put"):
    """DataFrame in the same shape the yfinance chains use:
    strike / bid / ask / mid / lastPrice / impliedVolatility / openInterest /
    volume / spread_pct — plus real greeks_delta when the plan provides it.
    Returns (df, underlying_spot)."""
    results = _snapshot_results(tkr, {
        "expiration_date": expiry,
        "contract_type": "put" if str(option_type).lower().startswith("p") else "call",
        "limit": 250,
    })
    if not results:
        raise RuntimeError("empty chain")
    rows, spot = [], float("nan")
    for c in results:
        det = c.get("details") or {}
        q   = c.get("last_quote") or {}
        day = c.get("day") or {}
        g   = c.get("greeks") or {}
        ua  = c.get("underlying_asset") or {}
        if ua.get("price") is not None:
            spot = float(ua["price"])
        bid   = float(q.get("bid") or 0)
        ask   = float(q.get("ask") or 0)
        close = float(day.get("close") or 0)
        # Price ladder: NBBO mid (quotes-entitled plans) -> day close (all
        # plans, 15-min delayed; also the official close when markets are shut)
        if bid > 0 and ask > 0:
            mid, px_source, spread = (bid + ask) / 2, "quote", np.nan
        elif close > 0:
            mid, px_source, spread = close, "close", np.nan
        else:
            mid, px_source, spread = np.nan, "none", np.nan
        if px_source == "quote":
            spread = (ask - bid) / mid
        rows.append({
            "strike":            float(det.get("strike_price") or np.nan),
            "bid":               bid,
            "ask":               ask,
            "mid":               mid,
            "px_source":         px_source,
            "lastPrice":         close,
            "spread_pct":        spread,
            "impliedVolatility": float(c.get("implied_volatility") or 0),
            "openInterest":      int(c.get("open_interest") or 0),
            "volume":            int(day.get("volume") or 0),
            "greeks_delta":      float(g["delta"]) if g.get("delta") is not None else np.nan,
        })
    df = pd.DataFrame(rows).dropna(subset=["strike"]).sort_values("strike").reset_index(drop=True)
    if df.empty:
        raise RuntimeError("empty chain")
    return df, spot


def expirations(tkr: str):
    """Sorted unique expiration dates (YYYY-MM-DD) for listed, unexpired contracts."""
    data = _get("/v3/reference/options/contracts", {
        "underlying_ticker": tkr.upper(), "expired": "false",
        "limit": 1000, "sort": "expiration_date", "order": "asc",
    })
    exps, results = set(), list(data.get("results", []))
    while data.get("next_url"):
        data = _get(data["next_url"])
        results += data.get("results", [])
    for c in results:
        e = c.get("expiration_date")
        if e:
            exps.add(e)
    if not exps:
        raise RuntimeError("no expirations")
    return sorted(exps)


def spot(tkr: str) -> float:
    """Underlying price via a 1-contract chain snapshot (no Stocks plan needed).
    SINGLE request — never follow pagination here (limit=1 offers a next_url
    for every contract on the underlying; following it = thousands of calls)."""
    data = _get(f"/v3/snapshot/options/{tkr.upper()}", {"limit": 1})
    for c in data.get("results", []):
        ua = c.get("underlying_asset") or {}
        if ua.get("price") is not None:
            return float(ua["price"])
    raise RuntimeError("no underlying price")


def self_test(tkr: str = "AAPL"):
    """What does this key actually deliver? Shown in the app's status panel."""
    out = {"configured": configured()}
    if not out["configured"]:
        return out
    try:
        exps = expirations(tkr)
        out["expirations"] = len(exps)
        df, s = chain(tkr, exps[0], "put")
        out["contracts"]      = len(df)
        out["underlying_spot"] = s
        out["has_bid_ask"]    = bool((df["bid"] > 0).any() and (df["ask"] > 0).any())
        out["has_iv"]         = bool((df["impliedVolatility"] > 0).any())
        out["has_greeks"]     = bool(df["greeks_delta"].notna().any())
        out["ok"] = True
    except Exception as e:
        out["ok"] = False
        out["error"] = f"{type(e).__name__}: {e}"
    return out
