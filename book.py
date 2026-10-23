"""
Position book — the ONE place open positions are priced and P&L is computed.

Every consumer goes through build_book():
  • the app, via shared.build_book (live, cached price feeds): Portfolio page,
    Fund-page headline NAV, Option Finder pre-trade check;
  • scripts/daily_snapshot.py and scripts/alerts.py (end-of-day prices);
  • risk.history (model prices, day by day over the trade log).
So the headline NAV, the Portfolio page and the nightly snapshot apply the same
rules and can't drift apart — only the price SOURCE differs.

Pure Python (numpy / pandas / scipy) — no Streamlit, so the scripts can import it.
"""
import datetime
import math
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy.stats import norm

ET = ZoneInfo("America/New_York")


def today_et() -> datetime.date:
    """US trading date. Streamlit Cloud and GitHub runners are on UTC, where
    date.today() already reads 'tomorrow' from 8pm ET."""
    return datetime.datetime.now(ET).date()


# ── Strategies (single source of truth) ───────────────────────────────────────
STRATEGIES = {
    "Short Put":                {"legs": "single", "type": "put",   "short": True},
    "Cash-Secured Put (Wheel)": {"legs": "single", "type": "put",   "short": True},
    "Bull Put Spread":          {"legs": "spread", "type": "put",   "short": True},
    "Covered Call":             {"legs": "single", "type": "call",  "short": True},
    "Bear Call Spread":         {"legs": "spread", "type": "call",  "short": True},
    "Long Put (Hedge)":         {"legs": "single", "type": "put",   "short": False},
    "Long Call":                {"legs": "single", "type": "call",  "short": False},
    # Stock: CONTRACTS = shares, PREMIUM / CREDIT = entry price/share, multiplier 1
    "Long Stock":               {"legs": "stock",  "type": "stock", "short": False},
}
STRAT_NAMES = list(STRATEGIES)


# ── Trade columns (app names <-> DB names) — shared by db.py and the scripts ──
TRADE_COLUMNS = [
    "ID", "DATE OPENED", "TICKER", "STRATEGY",
    "SHORT STRIKE", "LONG STRIKE", "EXPIRY", "DTE OPEN",
    "CONTRACTS", "PREMIUM / CREDIT", "CASH SECURED", "MAX LOSS",
    "STATUS", "DATE CLOSED", "CLOSE PRICE", "REALIZED PNL", "SIGNAL",
    "RECOMMENDED BY", "CONSENSUS", "MANUAL MARK", "NET CREDIT BASIS", "NOTES",
]
COL2DB = {
    "ID": "id", "DATE OPENED": "date_opened", "TICKER": "ticker", "STRATEGY": "strategy",
    "SHORT STRIKE": "short_strike", "LONG STRIKE": "long_strike", "EXPIRY": "expiry",
    "DTE OPEN": "dte_open", "CONTRACTS": "contracts", "PREMIUM / CREDIT": "premium",
    "CASH SECURED": "cash_secured", "MAX LOSS": "max_loss", "STATUS": "status",
    "DATE CLOSED": "date_closed", "CLOSE PRICE": "close_price",
    "REALIZED PNL": "realized_pnl", "SIGNAL": "signal",
    "RECOMMENDED BY": "recommended_by", "CONSENSUS": "consensus",
    "MANUAL MARK": "manual_mark", "NET CREDIT BASIS": "net_credit_basis", "NOTES": "notes",
}
DB2COL = {v: k for k, v in COL2DB.items()}


def trades_from_rows(rows) -> pd.DataFrame:
    """DB rows (PostgREST JSON) -> trades DataFrame with the app's column names."""
    df = pd.DataFrame(rows or [])
    if df.empty:
        return pd.DataFrame(columns=TRADE_COLUMNS)
    df = df.rename(columns=DB2COL)
    for c in TRADE_COLUMNS:
        if c not in df.columns:
            df[c] = None
    return df[TRADE_COLUMNS]


def is_stock(strategy) -> bool:
    return STRATEGIES.get(str(strategy), {}).get("legs") == "stock"


def is_short(strategy) -> bool:
    s = str(strategy)
    if s in STRATEGIES:
        return STRATEGIES[s]["short"]
    return not is_stock(s) and "Long" not in s      # unknown option -> short (conservative)


def option_kind(strategy) -> str:
    t = STRATEGIES.get(str(strategy), {}).get("type")
    return t if t in ("put", "call") else ("put" if "Put" in str(strategy) else "call")


def strat_mult(strategy) -> int:
    """P&L multiplier: 1 for stock (per share), 100 for option contracts."""
    return 1 if is_stock(strategy) else 100


# ── Black-Scholes ─────────────────────────────────────────────────────────────
def _bs_delta(spot, strike, iv, dte, rf, kind):
    """Vectorized Black-Scholes delta. `strike`/`iv` may be scalars or arrays.
    Returns a float for scalar input, a numpy array otherwise."""
    strike = np.asarray(strike, dtype=float)
    iv     = np.asarray(iv, dtype=float)
    scalar = strike.ndim == 0 and iv.ndim == 0
    T = dte / 365.0
    with np.errstate(divide="ignore", invalid="ignore"):
        d1  = (np.log(spot / strike) + (rf + 0.5 * iv**2) * T) / (iv * np.sqrt(T))
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


# ── The book ──────────────────────────────────────────────────────────────────
def _num(v, default=0.0):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(f) else f


def _missing(v):
    return v is None or (isinstance(v, float) and math.isnan(v))


def build_book(open_trades, spot_fn, mark_fn, earnings_fn=None, sector_map=None, today=None):
    """Price every OPEN position — one row each (display columns + hidden "_"
    fields used by the stress test, cash accounting and the risk engine).

      spot_fn(ticker)                      -> price (NaN if unknown)
      mark_fn(ticker, strike, expiry, kind) -> (mid, iv), NaN when unpriced
      earnings_fn(ticker)                  -> days to next earnings, or None
      sector_map: {ticker: {"sector", "bucket"}}
    A manual mark (typed from the broker) beats the feed. Unpriced positions
    are kept (P&L left flat) and flagged in _PRICED so the page can say so.
    """
    today = today or today_et()
    sector_map = sector_map or {}
    if open_trades is None or open_trades.empty:
        return pd.DataFrame()
    # Covered calls on names held as their own Long Stock row are just the short
    # call leg — the stock's +1 delta is already counted by that row.
    stock_tickers = set(open_trades.loc[open_trades["STRATEGY"].map(is_stock), "TICKER"].astype(str))

    rows = []
    for _, t in open_trades.iterrows():
        tkr   = str(t["TICKER"])
        strat = str(t["STRATEGY"])
        stk   = is_stock(strat)
        cc    = strat == "Covered Call"
        cc_standalone = cc and tkr not in stock_tickers   # no stock row -> stock + call combined
        short = is_short(strat)
        kind  = None if stk else option_kind(strat)
        is_put, spread = kind == "put", STRATEGIES.get(strat, {}).get("legs") == "spread" or "Spread" in strat
        mult  = strat_mult(strat)
        k     = _num(t.get("SHORT STRIKE"))
        kl    = _num(t.get("LONG STRIKE"))
        ctrs  = int(_num(t.get("CONTRACTS")))
        prem  = _num(t.get("PREMIUM / CREDIT"))
        expiry = str(t.get("EXPIRY"))
        has_exp = expiry not in ("nan", "None", "", "NaT")

        try:
            spot = float(spot_fn(tkr))
        except Exception:
            spot = float("nan")

        dte = None
        if not stk:
            try:
                dte = max((datetime.date.fromisoformat(expiry[:10]) - today).days, 0)
            except Exception:
                dte = 0

        mid, iv = float("nan"), float("nan")
        if not stk and k > 0 and has_exp:
            try:
                mid, iv = mark_fn(tkr, k, expiry, kind)
            except Exception:
                pass
        mmark = _num(t.get("MANUAL MARK"))
        if mmark > 0:
            if stk:
                spot = mmark
            else:
                mid = mmark
        iv_used = float("nan") if stk else (iv if not math.isnan(iv) else 0.35)

        # Delta — short put +d | short call -d | long stock +1 | covered call -d when
        # shares are a separate row, else 1-d | long put -d | long call +d
        delta = dollar_delta = float("nan")
        try:
            if stk:
                delta = 1.0
            elif k > 0 and not math.isnan(spot):
                d = abs(_bs_delta(spot, k, iv_used, dte, 0.053, kind))
                if cc:
                    delta = (1.0 - d) if cc_standalone else -d
                elif is_put:
                    delta = d if short else -d
                else:
                    delta = -d if short else d
                if spread and kl > 0:
                    d_long = abs(_bs_delta(spot, kl, iv_used, dte, 0.053, kind))
                    delta = delta - d_long if is_put else delta + d_long
            if not math.isnan(delta) and not math.isnan(spot):
                dollar_delta = delta * ctrs * mult * spot
        except Exception:
            pass

        # Unrealized P&L vs entry
        if stk and not math.isnan(spot) and prem > 0:
            unreal = (spot - prem) * ctrs
        elif not stk and not math.isnan(mid) and prem > 0:
            unreal = ((prem - mid) if short else (mid - prem)) * 100 * ctrs
        else:
            unreal = float("nan")

        # Profit-take tracker (manual §5.1) — options only
        pct_max_profit = yield_left = float("nan")
        action, tenor = "", "STK"
        if not stk:
            dte_open  = int(_num(t.get("DTE OPEN"), 35))
            tenor     = "3M" if dte_open > 60 else "1M"
            manage_at = 45 if tenor == "3M" else 21
            # A ROLLED position measures profit against the campaign's cumulative
            # net credit (NET CREDIT BASIS), not the new leg's premium.
            ncb = _num(t.get("NET CREDIT BASIS"))
            basis, tag = (ncb, " · CAMPAIGN") if ncb > 0 else (prem, "")
            if short and basis > 0 and not math.isnan(mid):
                pct_max_profit = (basis - mid) / basis
            if short and k > 0 and dte and not math.isnan(mid):
                yield_left = (mid / k) * (365.0 / dte)
            p = pct_max_profit
            if not math.isnan(p) and p >= 0.90:
                action = "CLOSE (90%+)" + tag
            elif not math.isnan(p) and p >= 0.50 and not math.isnan(yield_left) and yield_left < 0.15:
                action = "CLOSE (YIELD LEFT < 15%)" + tag
            elif not math.isnan(p) and p >= 0.75:
                action = "TAKE 75% TIER" + tag
            elif not math.isnan(p) and p >= 0.50:
                action = "TAKE 50% TIER" + tag
            elif dte is not None and dte <= manage_at:
                action = f"MANAGE ({tenor} @ {manage_at} DTE)"

        # Earnings: report before this option expires (gap risk), or within two
        # weeks for held stock.
        earn = None
        if earnings_fn is not None:
            try:
                ed = earnings_fn(tkr)
            except Exception:
                ed = None
            if ed is not None and ed >= 0 and (ed <= dte if not stk else ed <= 14):
                earn = int(ed)

        # Cash at risk / max loss — stored values first, else derived per strategy
        # (never strike×100 for spreads / covered calls / long options).
        stored_cash = None if _missing(t.get("CASH SECURED")) else _num(t.get("CASH SECURED"))
        stored_loss = None if _missing(t.get("MAX LOSS")) else _num(t.get("MAX LOSS"))
        if stk:
            cash_sec = stored_cash if stored_cash is not None else prem * ctrs
            max_loss = stored_loss if stored_loss is not None else cash_sec
        elif spread:
            if stored_loss is not None:
                max_loss = stored_loss
            elif kl > 0 and k > 0:
                max_loss = max((abs(kl - k) - prem) * 100 * ctrs, 0)
            else:
                max_loss = 0.0
            cash_sec = max_loss
        elif cc:
            cash_sec = 0.0                       # stock-secured, not cash-secured
            max_loss = stored_loss if stored_loss is not None else 0.0
        elif not short:
            cash_sec = stored_cash if stored_cash is not None else prem * 100 * ctrs
            max_loss = stored_loss if stored_loss is not None else cash_sec
        else:
            cash_sec = stored_cash if stored_cash is not None else (k * 100 * ctrs if k > 0 else 0)
            max_loss = stored_loss if stored_loss is not None else cash_sec

        if stk:
            breakeven = prem if prem > 0 else None
        elif k > 0:
            breakeven = (k - prem) if is_put else (k + prem)
        else:
            breakeven = None

        info = sector_map.get(tkr, {})
        r2 = lambda v, n=2: round(v, n) if not math.isnan(v) else None
        rows.append({
            "ID":            t.get("ID"),
            "TICKER":        tkr,
            "STRATEGY":      strat,
            "SECTOR":        info.get("sector", "Unknown"),
            "BUCKET":        info.get("bucket", "Unknown"),
            "SPOT":          r2(spot),
            "SHORT STRIKE":  k if k > 0 else None,
            "BREAKEVEN":     round(breakeven, 2) if breakeven is not None else None,
            "EXPIRY":        t.get("EXPIRY"),
            "TENOR":         tenor,
            "DTE LEFT":      dte,
            "EARNINGS":      earn,
            "CONTRACTS":     ctrs,
            "CURRENT MID":   r2(mid),
            "PREM RECEIVED": prem,
            "TOTAL $ PREM RECEIVED": round(prem * 100 * ctrs, 0) if (short and not stk) else None,
            "UNREAL PNL":    r2(unreal),
            "IV USED":       r2(iv_used, 4),
            "DELTA":         r2(delta, 3),
            "$ DELTA":       r2(dollar_delta, 0),
            "% MAX PROFIT":  r2(pct_max_profit, 4),
            "YIELD LEFT":    r2(yield_left, 4),
            "ACTION":        action,
            "CASH AT RISK":  cash_sec,
            "MAX LOSS":      max_loss,
            # hidden fields (dropped before display)
            "_LONG_STRIKE":   kl,
            "_IS_PUT":        is_put,
            "_IS_SHORT":      short,
            "_IS_SPREAD":     spread,
            "_IS_STOCK":      stk,
            "_IS_CC":         cc,
            "_CC_STANDALONE": cc_standalone,
            "_PREM":          prem,
            "_MULT":          mult,
            "_IV":            iv_used,
            "_DTE_REM":       dte if dte is not None else 0,
            "_PRICED":        (not math.isnan(spot)) if stk else (not math.isnan(mid)),
        })
    return pd.DataFrame(rows)


def unpriced(book) -> list:
    """Tickers of positions with no usable price (their P&L is left flat)."""
    if book.empty:
        return []
    return book.loc[~book["_PRICED"].astype(bool), "TICKER"].tolist()


def cash_summary(book, total_capital) -> dict:
    """Cash accounting on the book. Unmarked positions use the same assumption
    NAV uses (flat at entry), otherwise cash would be misstated.
      account cash = NAV − stock held − long options held + cost to close shorts
      reserved     = cash-secured collateral on SHORT options only
      available    = account cash − reserved (negative = puts on margin)"""
    stock_mv = short_liab = long_opt_mv = 0.0
    for _, r in book.iterrows():
        if r["_IS_STOCK"]:
            s = r["SPOT"] if not _missing(r["SPOT"]) else (r["_PREM"] or 0)
            stock_mv += s * r["CONTRACTS"]
        else:
            cm = r["CURRENT MID"] if not _missing(r["CURRENT MID"]) else (r["_PREM"] or 0)
            if r["_IS_SHORT"]:
                short_liab += cm * 100 * r["CONTRACTS"]
            else:
                long_opt_mv += cm * 100 * r["CONTRACTS"]
    acct_cash = total_capital - stock_mv - long_opt_mv + short_liab
    reserved = float(book.loc[(~book["_IS_STOCK"].astype(bool)) & (book["_IS_SHORT"].astype(bool)),
                              "CASH AT RISK"].sum()) if not book.empty else 0.0
    return {"stock_mv": stock_mv, "short_liab": short_liab, "long_opt_mv": long_opt_mv,
            "acct_cash": acct_cash, "reserved": reserved, "available": acct_cash - reserved}


def scenario_pnl(book, shock, mode="INSTANT SHOCK", weeks=0) -> float:
    """Book P&L vs entry if the underlyings move by `shock` — a float (every
    name moves the same %) or {ticker: % move} (e.g. beta-scaled QQQ moves).
    INSTANT SHOCK: Black-Scholes at live IV on (remaining DTE − weeks); single
    options anchored to their live mark so the 0% point is today's unrealized.
    HOLD TO EXPIRY: each option at intrinsic on its own expiry."""
    total = 0.0
    for _, r in book.iterrows():
        spot0 = r["SPOT"]
        if _missing(spot0):
            continue
        move = shock.get(r["TICKER"], 0.0) if isinstance(shock, dict) else shock
        s = spot0 * (1 + move)
        ctrs, prem = r["CONTRACTS"], r["_PREM"] or 0
        if r["_IS_STOCK"]:
            if prem > 0:
                total += (s - prem) * ctrs
            continue
        k, kl = _num(r["SHORT STRIKE"]), _num(r["_LONG_STRIKE"])
        if not k:
            continue
        if r["_IS_CC"] and r["_CC_STANDALONE"]:
            total += (s - spot0) * 100 * ctrs           # stock leg not logged separately
        kind = "put" if r["_IS_PUT"] else "call"
        if mode == "INSTANT SHOCK":
            dte_eff = max(0.0, (r["_DTE_REM"] or 0) - weeks * 7)
            v = bs_price(s, k, r["_IV"], dte_eff, kind=kind)
            if r["_IS_SPREAD"] and kl:
                v -= bs_price(s, kl, r["_IV"], dte_eff, kind=kind)
            cm = r["CURRENT MID"]
            if not r["_IS_SPREAD"] and not _missing(cm):
                v += cm - bs_price(spot0, k, r["_IV"], r["_DTE_REM"], kind=kind)
        else:
            v = max(k - s, 0) if r["_IS_PUT"] else max(s - k, 0)
            if r["_IS_SPREAD"] and kl:
                v -= max(kl - s, 0) if r["_IS_PUT"] else max(s - kl, 0)
        total += ((prem - v) if r["_IS_SHORT"] else (v - prem)) * 100 * ctrs
    return total
