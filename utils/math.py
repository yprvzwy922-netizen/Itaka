"""
Core option math — Black-Scholes, annualized metrics, IV Rank.
All per-share unless noted.
"""
import numpy as np
from scipy.stats import norm


def bs_put_delta(spot: float, strike: float, iv: float, dte: int,
                 risk_free: float = 0.053) -> float:
    """
    Black-Scholes European put delta.
    Returns absolute value (positive number between 0 and 1).
    """
    if dte <= 0 or iv <= 0 or spot <= 0 or strike <= 0:
        return float("nan")
    T = dte / 365.0
    d1 = (np.log(spot / strike) + (risk_free + 0.5 * iv**2) * T) / (iv * np.sqrt(T))
    put_delta = norm.cdf(d1) - 1  # negative
    return abs(put_delta)


def moneyness(spot: float, strike: float, band_pct: float = 0.01) -> str:
    band = band_pct * spot
    if strike < spot - band:
        return "OTM"
    if strike > spot + band:
        return "ITM"
    return "ATM"


def cash_secured(strike: float, contracts: int = 1) -> float:
    return strike * 100 * contracts


def premium_income(premium: float, contracts: int = 1) -> float:
    return premium * 100 * contracts


def static_yield(premium: float, strike: float) -> float:
    if strike == 0:
        return float("nan")
    return premium / strike


def annualized_yield(premium: float, strike: float, dte: int) -> float:
    if strike == 0 or dte == 0:
        return float("nan")
    return (premium / strike) * (365 / dte)


def downside_cushion(spot: float, strike: float) -> float:
    if spot == 0:
        return float("nan")
    return (spot - strike) / spot


def breakeven(strike: float, premium: float) -> float:
    return strike - premium


def effective_entry_vs_spot(strike: float, premium: float, spot: float) -> float:
    if spot == 0:
        return float("nan")
    return (strike - premium) / spot - 1


def annualized_roll(net_credit: float, strike_new: float, added_dte: int) -> float:
    """
    net_credit   = premium_new - premium_buyback  (per share)
    added_dte    = DTE_new - DTE_remaining_current
    """
    if strike_new == 0 or added_dte == 0:
        return float("nan")
    return (net_credit / strike_new) * (365 / added_dte)


def iv_rank(current_iv: float, iv_series) -> float:
    """
    iv_series: iterable of historical ATM IVs (float).
    Returns 0..1, or nan if insufficient data.
    """
    vals = [v for v in iv_series if v and not np.isnan(v)]
    if len(vals) < 5:
        return float("nan")
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return float("nan")
    return (current_iv - lo) / (hi - lo)


def screening_score(ivrank_s: float, yield_s: float, liquidity_s: float,
                    earnings_clear_s: float, technical_s: float,
                    conviction_s: float) -> float:
    """
    Each sub-score is 1..5.  Weights match the playbook.
    Returns composite 1..5.
    """
    return (0.30 * ivrank_s
            + 0.25 * yield_s
            + 0.15 * liquidity_s
            + 0.10 * earnings_clear_s
            + 0.10 * technical_s
            + 0.10 * conviction_s)


def verdict(score: float) -> str:
    if score >= 4:
        return "TRADE"
    if score >= 3:
        return "Watch"
    return "Pass"
