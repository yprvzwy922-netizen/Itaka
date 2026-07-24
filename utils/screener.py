"""
Builds the full screener row for one ticker.
Returns a dict ready to append into the watchlist DataFrame.
"""
import datetime
import numpy as np
import pandas as pd

from utils import data as D
from utils import math as M


DELTA_BANDS = {
    "Income": (0.15, 0.30),
    "Wheel":  (0.30, 0.45),
}

RISK_FREE = 0.053   # updated via .env ideally


def _score_ivrank(ivr: float) -> float:
    if np.isnan(ivr): return 2.5
    return 1 + ivr * 4  # 0→1, 1→5


def _score_yield(ann_y: float) -> float:
    if np.isnan(ann_y): return 1.0
    if ann_y >= 0.30: return 5.0
    if ann_y >= 0.20: return 4.0
    if ann_y >= 0.12: return 3.0
    if ann_y >= 0.06: return 2.0
    return 1.0


def _score_liquidity(oi: float, spread_pct: float) -> float:
    s = 3.0
    if oi > 5000: s += 1
    if oi < 500:  s -= 1
    if not np.isnan(spread_pct):
        if spread_pct < 0.03: s += 1
        if spread_pct > 0.10: s -= 1
    return max(1.0, min(5.0, s))


def _score_earnings(dte_to_earnings, dte_target: int) -> float:
    if dte_to_earnings is None: return 3.0
    if dte_to_earnings > dte_target + 5: return 5.0
    if dte_to_earnings > dte_target:     return 4.0
    if dte_to_earnings > 7:              return 2.0
    return 1.0  # earnings inside window — big penalty


def _trend_proxy(hist: pd.DataFrame) -> tuple[str, float]:
    """
    Simple proxy for macro trend: price vs 50/200 EMA.
    Returns (trend_label, technical_score 1..5).
    """
    if hist.empty or len(hist) < 20:
        return ("Unknown", 2.5)
    close = hist["Close"]
    ema50  = close.ewm(span=50,  adjust=False).mean().iloc[-1]
    ema200 = close.ewm(span=200, adjust=False).mean().iloc[-1]
    price  = close.iloc[-1]
    if price > ema50 > ema200:
        return ("Up", 5.0)
    if price > ema200:
        return ("Up (weak)", 3.5)
    if price < ema200:
        return ("Down", 1.5)
    return ("Neutral", 2.5)


def best_put_for_band(ticker: str, target_dte: int, delta_band: str,
                      risk_free: float = RISK_FREE) -> dict:
    """
    Find the put closest to the centre of delta_band for target_dte.
    Returns dict of option metrics, or empty dict on failure.
    """
    lo, hi = DELTA_BANDS.get(delta_band, (0.15, 0.30))
    target_delta = (lo + hi) / 2

    try:
        spot = D.get_spot(ticker)
        exps = D.get_expirations(ticker)
        expiry = D.best_expiry_for_tenor(exps, target_dte)
        if expiry is None:
            return {}
        chain = D.get_option_chain(ticker, expiry)
        chain = chain[chain["impliedVolatility"] > 0].copy()
        if chain.empty:
            return {}

        dte = chain["dte"].iloc[0]
        chain["delta"] = chain.apply(
            lambda r: M.bs_put_delta(spot, r["strike"], r["impliedVolatility"], dte, risk_free),
            axis=1
        )
        # filter to plausible range
        in_band = chain[(chain["delta"] >= lo * 0.7) & (chain["delta"] <= hi * 1.5)]
        if in_band.empty:
            in_band = chain

        in_band = in_band.copy()
        in_band["delta_dist"] = (in_band["delta"] - target_delta).abs()
        row = in_band.loc[in_band["delta_dist"].idxmin()]

        prem = float(row["mid"]) if not np.isnan(row["mid"]) else float(row["bid"])
        strike = float(row["strike"])
        iv = float(row["impliedVolatility"])

        return {
            "expiry": expiry,
            "dte": dte,
            "strike": strike,
            "delta": round(float(row["delta"]), 3),
            "iv": round(iv, 4),
            "premium": round(prem, 2),
            "ann_yield": round(M.annualized_yield(prem, strike, dte), 4),
            "cushion": round(M.downside_cushion(spot, strike), 4),
            "breakeven": round(M.breakeven(strike, prem), 2),
            "oi": int(row.get("openInterest", 0) or 0),
            "spread_pct": round(float(row["spread_pct"]) if not np.isnan(row.get("spread_pct", float("nan"))) else float("nan"), 4),
        }
    except Exception:
        return {}


def build_screener_row(ticker: str, wl_row: dict,
                       risk_free: float = RISK_FREE) -> dict:
    spot     = D.get_spot(ticker)
    hist     = D.get_history(ticker)
    dte_earn = D.days_to_earnings(ticker)
    iv_hist  = D.get_iv_history(ticker)
    atm_iv   = D.get_atm_iv(ticker)
    ivr      = M.iv_rank(atm_iv, iv_hist)

    trend_label, tech_score = _trend_proxy(hist)

    delta_band = wl_row.get("target_delta_band", "Income")
    conviction = int(wl_row.get("conviction", 3))

    put_1m = best_put_for_band(ticker, 30, delta_band, risk_free)
    put_3m = best_put_for_band(ticker, 90, delta_band, risk_free)

    # sub-scores
    ivrank_s  = _score_ivrank(ivr)
    yield_s   = _score_yield(put_1m.get("ann_yield", float("nan")))
    liq_s     = _score_liquidity(put_1m.get("oi", 0), put_1m.get("spread_pct", float("nan")))
    earn_s    = _score_earnings(dte_earn, put_1m.get("dte", 30) if put_1m else 30)
    conv_s    = float(conviction)

    score = M.screening_score(ivrank_s, yield_s, liq_s, earn_s, tech_score, conv_s)

    # SMA 50/200 labels
    ema50_val  = hist["Close"].ewm(span=50,  adjust=False).mean().iloc[-1] if not hist.empty else float("nan")
    ema200_val = hist["Close"].ewm(span=200, adjust=False).mean().iloc[-1] if not hist.empty else float("nan")

    return {
        "Ticker":           ticker,
        "Price":            round(spot, 2),
        "Bucket":           wl_row.get("bucket", ""),
        "Sector":           wl_row.get("sector", ""),
        "ATM IV":           round(atm_iv, 4) if not np.isnan(atm_iv) else None,
        "IV Rank":          round(ivr, 3) if not np.isnan(ivr) else None,
        "Trend":            trend_label,
        "EMA50":            round(ema50_val, 2) if not np.isnan(ema50_val) else None,
        "EMA200":           round(ema200_val, 2) if not np.isnan(ema200_val) else None,
        "Days to Earnings": dte_earn,
        # 1M best put
        "1M Strike":        put_1m.get("strike"),
        "1M Delta":         put_1m.get("delta"),
        "1M Ann Yield":     put_1m.get("ann_yield"),
        "1M Cushion":       put_1m.get("cushion"),
        "1M Premium":       put_1m.get("premium"),
        "1M Expiry":        put_1m.get("expiry"),
        "1M DTE":           put_1m.get("dte"),
        # 3M best put
        "3M Strike":        put_3m.get("strike"),
        "3M Delta":         put_3m.get("delta"),
        "3M Ann Yield":     put_3m.get("ann_yield"),
        "3M Cushion":       put_3m.get("cushion"),
        "3M Premium":       put_3m.get("premium"),
        "3M Expiry":        put_3m.get("expiry"),
        "3M DTE":           put_3m.get("dte"),
        # scoring
        "Score":            round(score, 2),
        "Verdict":          M.verdict(score),
    }
