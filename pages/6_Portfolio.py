"""
Portfolio & Risk — open positions, delta exposure, sector exposure, risk limit gauges.
Reads from the Trade Log session state.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import bbg_style
import db
from shared import (get_watchlist, fetch_spot, bs_put_delta, bs_call_delta,
                    bs_price, fetch_option_live)
import datetime

bbg_style.inject()


c_nav1, _ = st.columns([1, 9])
with c_nav1:
    if st.button("HOME"): st.switch_page("pages/0_Home.py")

st.title("PORTFOLIO & RISK")
st.caption("OPEN POSITIONS FROM TRADE LOG | DELTA EXPOSURE | SECTOR LIMITS | RISK GAUGES")

# ── Risk limits (sidebar) ─────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### CAPITAL BASE")
    CAP_MODE = st.radio("RISK CAPS MEASURED AGAINST",
                        ["Auto — Fund NAV", "Manual"], index=0,
                        help="Auto = fund's contributions + realized + unrealized P&L "
                             "(the real money). Manual = a fixed number you type.")
    MANUAL_CAPITAL = st.number_input("MANUAL CAPITAL ($)", 10_000, 10_000_000, 1_000_000, 5_000,
                                     disabled=CAP_MODE.startswith("Auto"))
    st.markdown("---")
    st.markdown("### RISK LIMITS")
    st.caption("DEFAULTS = PUT-SELLING PROSPECT CAPS (OPS STEP 6)")
    MAX_SINGLE_NAME = st.slider("MAX SINGLE NAME %",      5,  30, 10) / 100   # <=10% per name
    MAX_PER_TRADE   = st.slider("MAX SINGLE TRADE %",     1,  10,  3) / 100   # <=2-3% per trade
    MAX_SPECULATIVE = st.slider("MAX SPECULATIVE %",     10,  50, 40) / 100   # <=40% spec bucket
    MIN_CORE        = st.slider("MIN CORE %",             0,  70, 40) / 100   # backbone target
    MAX_SECTOR      = st.slider("MAX SECTOR %",          10,  50, 30) / 100   # <=30% per sector
    MAX_STOCK_INV   = st.slider("MAX STOCK INVENTORY %", 10,  60, 40) / 100   # manual §8.3 ceiling
    MAX_DEPLOYED    = st.slider("MAX % DEPLOYED",        50, 100, 100) / 100  # 100% invested mandate
    MIN_CASH_BUFFER = st.slider("MIN CASH BUFFER %",      0,  40,  0) / 100   # no idle cash
    MAX_DELTA_TOTAL = st.number_input("MAX NET DELTA ($ notional)", 0, 10_000_000, 500_000, 5_000,
                                      help="Max total dollar-delta across all positions")
    st.markdown("---")
    st.markdown("### DELTA EXPLAINED")
    st.caption(
        "NET $ DELTA = Σ (delta × contracts × multiplier × spot)\n\n"
        "Shows total directional dollar exposure:\n"
        "• Short Put = +delta (bullish — you profit if stock rises)\n"
        "• Short Call = -delta (bearish)\n"
        "• Covered Call = stock + short call = 1 − call delta (bullish, capped)\n"
        "• Long Stock = +1.0 per share\n"
        "• Long Put = -delta | Long Call = +delta\n\n"
        "A net $ delta of +$50k means your P&L moves like you own $50k of stock."
    )

# ── Get open trades (DB-backed when configured) ───────────────────────────────
trades = db.get_trades_df()

if trades.empty or (trades["STATUS"] == "OPEN").sum() == 0:
    st.info("No open trades in the Trade Log. Add trades in the Trade Log page first.")
    st.markdown("---")
    if st.button("GO TO TRADE LOG", type="primary"):
        st.switch_page("pages/5_Trade_Log.py")
    st.stop()

open_trades = trades[trades["STATUS"] == "OPEN"].copy()
wl = get_watchlist()
wl_map = {w["ticker"]: w for w in wl}

# Tickers where we already hold the shares as their own Long Stock row — a
# covered call on these is just the SHORT CALL leg (the +1 stock delta is
# already counted by the stock row, so don't double-count it here).
stock_tickers = set(open_trades[open_trades["STRATEGY"] == "Long Stock"]["TICKER"].astype(str))

# ── Enrich with live data ─────────────────────────────────────────────────────
# Warm all spots + chains in parallel first: the loop then reads warm caches
# (N serial network calls -> one concurrent burst).
from shared import prefetch_marks
_keys = []
for _, t in open_trades.iterrows():
    if str(t["STRATEGY"]) != "Long Stock" and pd.notna(t["SHORT STRIKE"]) \
       and str(t["EXPIRY"]) not in ("nan", "None", ""):
        _keys.append((str(t["TICKER"]), str(t["EXPIRY"]),
                      "put" if "Put" in str(t["STRATEGY"]) else "call"))
with st.spinner("FETCHING MARKET DATA..."):
    prefetch_marks(open_trades["TICKER"].astype(str).tolist(), _keys)

rows = []
_n = len(open_trades)
_prog = st.progress(0, text="MARKING POSITIONS...")
for _i, (_, t) in enumerate(open_trades.iterrows()):
    _prog.progress((_i + 1) / _n, text=f"MARKING {t['TICKER']} ({_i + 1}/{_n})...")
    tkr = str(t["TICKER"])
    try:
        spot = fetch_spot(tkr)
    except Exception:
        spot = float("nan")

    strat        = str(t["STRATEGY"])
    is_stock     = strat == "Long Stock"
    is_cc        = strat == "Covered Call"
    # Standalone CC = covered call with no separately-logged stock -> treat as
    # the combined position (stock + short call). Otherwise = short call only.
    cc_standalone = is_cc and tkr not in stock_tickers
    mult         = 1 if is_stock else 100            # stock P&L is per share
    short_strike = float(t["SHORT STRIKE"]) if pd.notna(t["SHORT STRIKE"]) else 0.0
    long_strike  = float(t["LONG STRIKE"])  if pd.notna(t["LONG STRIKE"])  else 0.0
    ctrs         = int(t["CONTRACTS"])
    prem         = float(t["PREMIUM / CREDIT"]) if pd.notna(t["PREMIUM / CREDIT"]) else 0.0
    expiry_str   = str(t["EXPIRY"])

    # DTE remaining (stock has no expiry)
    dte_rem = None
    if not is_stock:
        try:
            exp_dt  = datetime.datetime.strptime(expiry_str, "%Y-%m-%d").date()
            dte_rem = max((exp_dt - datetime.date.today()).days, 0)
        except Exception:
            dte_rem = 0

    # ── Live IV + current mid (options only) ──────────────────────────────────
    is_put  = "Put" in strat
    is_call = "Call" in strat
    is_short = not is_stock and strat not in ("Long Put (Hedge)", "Long Call")

    curr_mid, live_iv = float("nan"), float("nan")
    if not is_stock and short_strike > 0 and expiry_str and expiry_str not in ("nan", "None", ""):
        try:
            curr_mid, live_iv = fetch_option_live(
                tkr, short_strike, expiry_str, "put" if is_put else "call")
        except Exception:
            pass

    # Manual mark (typed from the broker in the Trade Log) beats the live feed —
    # the fix for thin names Yahoo can't quote (SPCX/NUAI-type strikes).
    mmark = float(t["MANUAL MARK"]) if pd.notna(t.get("MANUAL MARK")) and t.get("MANUAL MARK") else None
    if mmark and mmark > 0:
        if is_stock:
            spot = mmark            # manual share price
        else:
            curr_mid = mmark        # manual option mid

    iv_used = float("nan") if is_stock else (live_iv if not np.isnan(live_iv) else 0.35)

    # ── Delta (live IV via Black-Scholes) ──────────────────────────────────────
    # Sign convention:
    #   Long Stock   = +1.0 per share
    #   Short Put    = +delta (bullish) | Short Call (naked) = -delta
    #   Covered Call = short call leg = -call_delta IF stock is logged separately;
    #                  combined (1 - call_delta) only when stock is NOT logged
    #   Long Put     = -delta | Long Call = +delta
    delta        = float("nan")
    dollar_delta = float("nan")
    try:
        if is_stock:
            delta = 1.0
        elif is_cc and short_strike > 0:
            d = abs(bs_call_delta(spot, short_strike, iv_used, dte_rem))
            delta = (1.0 - d) if cc_standalone else (-d)   # avoid double-counting stock
        elif is_put and short_strike > 0:
            d = abs(bs_put_delta(spot, short_strike, iv_used, dte_rem))
            delta = +d if is_short else -d     # short put = +delta
        elif is_call and short_strike > 0:
            d = abs(bs_call_delta(spot, short_strike, iv_used, dte_rem))
            delta = -d if is_short else +d     # short (naked) call = -delta

        # Spread: long leg offsets
        if "Spread" in strat and long_strike > 0:
            if is_put:
                d_long = abs(bs_put_delta(spot, long_strike, iv_used, dte_rem))
                delta = delta - d_long
            elif is_call:
                d_long = abs(bs_call_delta(spot, long_strike, iv_used, dte_rem))
                delta = delta + d_long

        if not np.isnan(delta) and not np.isnan(spot):
            dollar_delta = delta * ctrs * mult * spot
    except Exception:
        pass

    # ── Unrealized P&L ────────────────────────────────────────────────────────
    if is_stock and not np.isnan(spot) and prem > 0:
        unreal = (spot - prem) * ctrs              # vs entry price, per share
    elif not np.isnan(curr_mid) and prem > 0:
        if is_short:
            unreal = (prem - curr_mid) * 100 * ctrs   # option leg only for covered calls
        else:
            unreal = (curr_mid - prem) * 100 * ctrs
    else:
        unreal = float("nan")

    # ── Profit-take tracker (manual §5.1) — options only ──────────────────────
    pct_max_profit = float("nan")
    yield_left     = float("nan")
    action         = ""
    if is_stock:
        tenor = "STK"
    else:
        dte_open  = int(t["DTE OPEN"]) if pd.notna(t.get("DTE OPEN")) else 35
        tenor     = "3M" if dte_open > 60 else "1M"
        manage_at = 45 if tenor == "3M" else 21

        # For a ROLLED position, profit-take is measured against the CAMPAIGN's
        # cumulative net credit (NET CREDIT BASIS), not the new leg's premium —
        # otherwise "50%" fires at campaign breakeven (see NUAI). Falls back to
        # the leg premium when no basis is set.
        ncb = float(t["NET CREDIT BASIS"]) if ("NET CREDIT BASIS" in t and
              pd.notna(t.get("NET CREDIT BASIS")) and t.get("NET CREDIT BASIS")) else None
        profit_basis = ncb if (ncb and ncb > 0) else prem
        rolled = ncb is not None and ncb > 0

        if is_short and profit_basis > 0 and not np.isnan(curr_mid):
            pct_max_profit = (profit_basis - curr_mid) / profit_basis
        if is_short and short_strike > 0 and dte_rem and dte_rem > 0 and not np.isnan(curr_mid):
            yield_left = (curr_mid / short_strike) * (365.0 / dte_rem)

        _tag = " · CAMPAIGN" if rolled else ""
        if not np.isnan(pct_max_profit) and pct_max_profit >= 0.90:
            action = "CLOSE (90%+)" + _tag
        elif not np.isnan(pct_max_profit) and pct_max_profit >= 0.50 and \
             not np.isnan(yield_left) and yield_left < 0.15:
            action = "CLOSE (YIELD LEFT < 15%)" + _tag
        elif not np.isnan(pct_max_profit) and pct_max_profit >= 0.75:
            action = "TAKE 75% TIER" + _tag
        elif not np.isnan(pct_max_profit) and pct_max_profit >= 0.50:
            action = "TAKE 50% TIER" + _tag
        elif dte_rem is not None and dte_rem <= manage_at:
            action = f"MANAGE ({tenor} @ {manage_at} DTE)"

    # ── Cash at risk / max loss (strategy-aware) ───────────────────────────────
    # Use the Trade Log's stored values when present, otherwise derive correctly
    # per strategy — NEVER fall back to strike*100 for spreads/covered calls,
    # which would massively overstate deployed capital.
    is_spread = "Spread" in strat
    is_covered_call = is_cc

    stored_cash = float(t["CASH SECURED"]) if pd.notna(t.get("CASH SECURED")) else None
    stored_loss = float(t["MAX LOSS"])     if pd.notna(t.get("MAX LOSS"))     else None

    if is_stock:
        # Long stock: capital deployed = cost basis; worst case stock -> $0
        cash_sec = stored_cash if stored_cash is not None else prem * ctrs
        max_loss = stored_loss if stored_loss is not None else cash_sec
    elif is_spread:
        # Defined-risk: capital at risk = max loss = (width - net credit) * 100
        if stored_loss is not None:
            max_loss = stored_loss
        elif long_strike > 0 and short_strike > 0:
            max_loss = max((abs(long_strike - short_strike) - prem) * 100 * ctrs, 0)
        else:
            max_loss = 0.0
        cash_sec = max_loss                      # margin held = max loss
    elif is_covered_call:
        # Stock-secured, not cash-secured — no separate cash deployed here
        cash_sec = 0.0
        max_loss = stored_loss if stored_loss is not None else 0.0
    else:
        # Cash-secured put / wheel (and long single legs): strike * 100 is correct
        cash_sec = stored_cash if stored_cash is not None else (
            short_strike * 100 * ctrs if short_strike > 0 else 0)
        max_loss = stored_loss if stored_loss is not None else cash_sec

    # Breakeven price: short put = strike − premium; call = strike + premium;
    # stock = entry price. The price at which the position turns from profit to loss.
    if is_stock:
        breakeven = prem if prem > 0 else None
    elif short_strike > 0:
        breakeven = (short_strike - prem) if is_put else (short_strike + prem)
    else:
        breakeven = None

    wl_info = wl_map.get(tkr, {})
    rows.append({
        "ID":            t["ID"],
        "TICKER":        tkr,
        "STRATEGY":      strat,
        "SECTOR":        wl_info.get("sector", "Unknown"),
        "BUCKET":        wl_info.get("bucket", "Unknown"),
        "SPOT":          round(spot, 2)          if not np.isnan(spot)        else None,
        "SHORT STRIKE":  short_strike            if short_strike > 0          else None,
        "BREAKEVEN":     round(breakeven, 2)     if breakeven is not None      else None,
        "EXPIRY":        t["EXPIRY"],
        "TENOR":         tenor,
        "DTE LEFT":      dte_rem,
        "CONTRACTS":     ctrs,
        "CURRENT MID":   round(curr_mid, 2)      if not np.isnan(curr_mid)    else None,
        "PREM RECEIVED": prem,
        "TOTAL $ PREM RECEIVED": round(prem * 100 * ctrs, 0) if (is_short and not is_stock) else None,
        "UNREAL PNL":    round(unreal, 2)          if not np.isnan(unreal)    else None,
        "IV USED":       round(iv_used, 4)       if not np.isnan(iv_used)     else None,
        "DELTA":         round(delta, 3)          if not np.isnan(delta)      else None,
        "$ DELTA":       round(dollar_delta, 0)   if not np.isnan(dollar_delta) else None,
        "% MAX PROFIT":  round(pct_max_profit, 4)  if not np.isnan(pct_max_profit) else None,
        "YIELD LEFT":    round(yield_left, 4)      if not np.isnan(yield_left) else None,
        "ACTION":        action,
        "CASH AT RISK":  cash_sec,
        "MAX LOSS":      max_loss,
        # hidden fields for the stress test (dropped before display)
        "_LONG_STRIKE":  long_strike,
        "_IS_PUT":       is_put,
        "_IS_SHORT":     is_short,
        "_IS_SPREAD":    is_spread,
        "_IS_STOCK":     is_stock,
        "_IS_CC":        is_cc,
        "_CC_STANDALONE": cc_standalone,
        "_PREM":         prem,
        "_MULT":         mult,
        "_IV":           iv_used,
        "_DTE_REM":      dte_rem if dte_rem is not None else 0,
    })

_prog.empty()
book = pd.DataFrame(rows)

# ── Capital base = the actual fund (contributions + realized + unrealized) ─────
total_unreal   = pd.to_numeric(book["UNREAL PNL"], errors="coerce").sum()
realized_all   = pd.to_numeric(trades["REALIZED PNL"], errors="coerce").fillna(0).sum()
flows          = db.load_cash_flows()
contributed    = float(pd.to_numeric(flows["amount"], errors="coerce").sum()) if not flows.empty else 0.0
fund_nav       = contributed + realized_all + total_unreal

if CAP_MODE.startswith("Auto") and contributed > 0:
    TOTAL_CAPITAL = fund_nav
    cap_note = (f"AUTO = FUND NAV  →  contributed ${contributed:,.0f} + realized ${realized_all:,.0f} "
                f"+ unrealized ${total_unreal:,.0f} = ${fund_nav:,.0f}")
else:
    TOTAL_CAPITAL = MANUAL_CAPITAL
    cap_note = (f"MANUAL = ${MANUAL_CAPITAL:,.0f}"
                + ("  (no cash flows logged yet — add them on the Performance page to use Auto)"
                   if CAP_MODE.startswith("Auto") else ""))

# ── Portfolio KPIs (single row, cash included) ────────────────────────────────
total_deployed = book["CASH AT RISK"].sum()
total_max_loss = book["MAX LOSS"].sum()
total_ddelta   = pd.to_numeric(book["$ DELTA"], errors="coerce").sum()   # used by risk checks
short_opt      = book[(~book["_IS_STOCK"]) & (book["_IS_SHORT"])]
total_premium  = (pd.to_numeric(short_opt["PREM RECEIVED"], errors="coerce") *
                  pd.to_numeric(short_opt["CONTRACTS"], errors="coerce") * 100).sum()

# Cash & dry powder: total cash = NAV − stock held + cost-to-close open shorts.
# IMPORTANT: unmarked positions must use the same assumption NAV uses (flat at
# entry), otherwise cash is understated by their premium / entry value.
stock_mv = 0.0
short_liab = 0.0
for _, r in book.iterrows():
    if r["_IS_STOCK"]:
        s = r["SPOT"]
        if s is None or (isinstance(s, float) and np.isnan(s)):
            s = r["_PREM"] or 0            # no spot -> NAV assumes entry price
        stock_mv += s * r["CONTRACTS"]
    elif r["_IS_SHORT"]:
        cm = r["CURRENT MID"]
        if cm is None or (isinstance(cm, float) and np.isnan(cm)):
            cm = r["_PREM"] or 0           # unmarked -> NAV assumes flat (mid = premium)
        short_liab += cm * 100 * r["CONTRACTS"]
acct_cash      = TOTAL_CAPITAL - stock_mv + short_liab
reserved_cash  = book.loc[~book["_IS_STOCK"], "CASH AT RISK"].sum()
available_cash = acct_cash - reserved_cash

# % deployed is measured against CASH (puts are cash-secured), NOT NAV — NAV
# understates the base by the open short-put liability, which would falsely
# show >100% even when you hold more than enough cash to secure every put.
pct_deployed   = reserved_cash / acct_cash if acct_cash else 0
cash_buffer    = 1 - pct_deployed

k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("TOTAL CAPITAL",     f"${TOTAL_CAPITAL:,.0f}",
          help="The base all risk caps are measured against. " + cap_note)
k2.metric("TOTAL CASH (T-BILLS)", f"${acct_cash:,.0f}",
          help="Fund value − stock held + premium cash collected. The actual cash in the account.")
k3.metric("CAPITAL DEPLOYED",  f"${total_deployed:,.0f}", f"{pct_deployed:.1%}",
          help="Collateral securing open puts = the max capital at risk (cash-secured = strike×100; "
               "spreads = max loss; covered calls = $0). Same figure as total max loss.")
k4.metric("AVAILABLE CASH",    f"${available_cash:,.0f}",
          help="Dry powder free to deploy into new cash-secured puts (total cash − collateral reserved).")
k5.metric("PREMIUM RECEIVED",  f"${total_premium:,.0f}",
          help="Σ premium × 100 × contracts on open short options (credit collected up front)")
k6.metric("UNREAL PNL (MID)",  f"${total_unreal:,.0f}",
          help="(Premium received − current mid) × 100 × contracts")

st.caption(f"CAPITAL BASE — {cap_note}  |  OPEN POSITIONS: {len(book)}  |  NET $ DELTA: ${total_ddelta:,.0f} "
           f"(both detailed below)")

st.markdown("---")

# ── Position table ────────────────────────────────────────────────────────────
st.markdown("### OPEN POSITIONS")

def color_dte(v):
    try: return "color:#ff4444;font-weight:600" if int(v) < 14 else "color:#ff9900" if int(v) < 21 else ""
    except: return ""

def color_pnl(v):
    try: return "color:#00e676" if float(v) > 0 else "color:#ff4444" if float(v) < 0 else ""
    except: return ""

def color_delta(v):
    try:
        f = float(v)
        return "color:#00e676" if f > 0 else "color:#ff4444" if f < 0 else ""
    except: return ""

def color_pct_profit(v):
    try:
        f = float(v)
        if f >= 0.50: return "color:#00e676;font-weight:700"   # at/past the GTC level
        if f >= 0.25: return "color:#00c8ff"
        if f < 0:     return "color:#ff4444"
        return ""
    except: return ""

def color_action(v):
    s = str(v)
    if s.startswith("CLOSE"):  return "color:#00e676;font-weight:700"
    if s.startswith("TAKE"):   return "color:#00c8ff;font-weight:600"
    if s.startswith("MANAGE"): return "color:#ff9900;font-weight:600"
    return ""

fmt = {
    "SPOT":          "${:.2f}",
    "DTE LEFT":      "{:.0f}",      # stock rows have no expiry (NaN -> "—"); options show whole days
    "CONTRACTS":     "{:.0f}",
    "SHORT STRIKE":  "${:.2f}",
    "BREAKEVEN":     "${:.2f}",
    "PREM RECEIVED": "${:.2f}",
    "CURRENT MID":   "${:.2f}",
    "TOTAL $ PREM RECEIVED": "${:,.0f}",
    "IV USED":       "{:.1%}",
    "DELTA":         "{:+.3f}",
    "$ DELTA":       "${:,.0f}",
    "CASH AT RISK":  "${:,.0f}",
    "MAX LOSS":      "${:,.0f}",
    "UNREAL PNL":    "${:,.0f}",
    "% MAX PROFIT":  "{:.0%}",
    "YIELD LEFT":    "{:.1%}",
}
disp_book = book[[c for c in book.columns if not c.startswith("_") and c != "ID"]]
styled_book = (disp_book.style
    .map(color_dte,        subset=["DTE LEFT"])
    .map(color_pnl,        subset=["UNREAL PNL"])
    .map(color_delta,      subset=["DELTA"])
    .map(color_pct_profit, subset=["% MAX PROFIT"])
    .map(color_action,     subset=["ACTION"])
    .format(fmt, na_rep="—"))

st.dataframe(styled_book, use_container_width=True, hide_index=True,
             column_config={"TICKER": st.column_config.Column(pinned=True)})
st.caption("DELTA: short put = +d | short call = -d | long stock = +1 | covered call = -d when shares are a separate "
           "LONG STOCK row, else 1-d (combined)  |  IV from live option chain, fallback 35%  |  "
           "COVERED CALL UNREAL PNL = option leg only")
st.caption("PROFIT-TAKE PROCEDURE (MANUAL §5.1): GTC BUY-TO-CLOSE AT 50% ON ENTRY → CLOSE 1/2 AT 50%, 1/4 AT 75%, REST BY 90% OR MANAGE-BY DATE (1M @ 21 DTE, 3M @ 45 DTE). "
           "YIELD LEFT = ANNUALIZED YIELD OF PREMIUM STILL ON THE TABLE — IF < 15% AFTER THE 50% TIER, CLOSE AND REDEPLOY.")

# ── Held stock — covered-call capacity (consolidated per ticker) ─────────────
# Multiple Long Stock lots per name are possible (each assignment adds a row),
# so aggregate by ticker. Shows what shares you hold, the call already written,
# and how many MORE covered calls you could sell (free shares // 100).
_stock = book[book["_IS_STOCK"]]
if not _stock.empty:
    st.markdown("### HELD STOCK — COVERED-CALL CAPACITY")
    _cc = book[book["_IS_CC"]]
    hs_rows = []
    for tkr, grp in _stock.groupby("TICKER"):
        sh_qty = pd.to_numeric(grp["CONTRACTS"], errors="coerce").fillna(0)
        shares = int(sh_qty.sum())
        basis  = pd.to_numeric(grp["PREM RECEIVED"], errors="coerce")   # entry px/share
        avg_cost = float((basis * sh_qty).sum() / sh_qty.sum()) if sh_qty.sum() else float("nan")
        spot_s = pd.to_numeric(grp["SPOT"], errors="coerce").dropna()
        spot_v = float(spot_s.iloc[0]) if len(spot_s) else float("nan")
        unreal = (spot_v - avg_cost) * shares if not (np.isnan(spot_v) or np.isnan(avg_cost)) else float("nan")

        cgrp = _cc[_cc["TICKER"] == tkr]
        call_cts = int(pd.to_numeric(cgrp["CONTRACTS"], errors="coerce").fillna(0).sum()) if not cgrp.empty else 0
        if not cgrp.empty:
            call_desc = " | ".join(
                f"{int(r['CONTRACTS'])}×${r['SHORT STRIKE']:g} {str(r['EXPIRY'])[5:] or ''}".strip()
                for _, r in cgrp.iterrows())
        else:
            call_desc = "—"
        covered_sh = call_cts * 100
        free_sh    = shares - covered_sh
        calls_avail = free_sh // 100

        hs_rows.append({
            "TICKER": tkr, "SHARES": shares, "AVG COST": round(avg_cost, 2) if not np.isnan(avg_cost) else None,
            "SPOT": round(spot_v, 2) if not np.isnan(spot_v) else None,
            "UNREAL $": round(unreal, 0) if not np.isnan(unreal) else None,
            "CALL": call_desc, "COVERED SH": covered_sh, "FREE SH": free_sh, "CALLS AVAIL": int(calls_avail),
        })
    hs = pd.DataFrame(hs_rows)

    def _c_avail(v):
        try:
            f = float(v)
            if f >= 1: return "color:#00e676;font-weight:700"   # free shares -> can write more calls
            if f < 0:  return "color:#ff4444;font-weight:700"   # over-covered / naked
            return "color:#888888"
        except Exception:
            return ""

    st.dataframe(
        hs.style
          .map(color_pnl, subset=["UNREAL $"])
          .map(_c_avail, subset=["CALLS AVAIL"])
          .format({"AVG COST": "${:.2f}", "SPOT": "${:.2f}", "UNREAL $": "${:,.0f}",
                   "SHARES": "{:,.0f}", "COVERED SH": "{:,.0f}", "FREE SH": "{:,.0f}"}, na_rep="—"),
        use_container_width=True, hide_index=True,
        column_config={"TICKER": st.column_config.Column(pinned=True)})
    _avail = int(hs["CALLS AVAIL"].clip(lower=0).sum())
    st.caption(f"CALLS AVAILABLE = free shares ÷ 100 — how many more covered calls you can write "
               f"({_avail} total across the book). AVG COST is share-weighted across lots. "
               f"Green = free shares to write; red = over-covered (naked).")

# ── Tenor mix (manual: ~60-70% 1M / ~30-40% 3M) — options only ───────────────
st.markdown("### TENOR MIX")
tm = book[book["TENOR"].isin(["1M", "3M"])].groupby("TENOR")["CASH AT RISK"].sum()
cash_1m, cash_3m = float(tm.get("1M", 0)), float(tm.get("3M", 0))
tot_tm = cash_1m + cash_3m
if tot_tm > 0:
    pct_1m, pct_3m = cash_1m / tot_tm, cash_3m / tot_tm
    in_band = 0.60 <= pct_1m <= 0.70
    t1, t2, t3 = st.columns(3)
    t1.metric("1M SLEEVE", f"{pct_1m:.0%}", f"${cash_1m:,.0f}")
    t2.metric("3M SLEEVE", f"{pct_3m:.0%}", f"${cash_3m:,.0f}")
    t3.metric("TARGET", "60-70% / 30-40%", "IN BAND" if in_band else "OUT OF BAND")
    if not in_band:
        st.warning(f"TENOR MIX OUT OF BAND: 1M = {pct_1m:.0%} (target 60-70%). "
                   f"{'Shift new tranches to 3M.' if pct_1m > 0.70 else 'Shift new tranches to 1M.'}")

st.markdown("---")

# ── Stress test — basket shock, both directions (manual §9 on the live book) ──
st.markdown("### STRESS TEST — BASKET SHOCK")

sm1, sm2 = st.columns([3, 7])
stress_mode = sm1.radio("VALUATION MODE", ["HOLD TO EXPIRY", "INSTANT SHOCK"],
                        horizontal=True,
                        help="HOLD TO EXPIRY: each option valued at intrinsic on ITS OWN expiry "
                             "(P&L vs entry premium — matches the payoff diagrams). "
                             "INSTANT SHOCK: all positions repriced TODAY with Black-Scholes at "
                             "their own remaining DTE and live IV — one common horizon, which is "
                             "how a book with multiple expiries is stressed consistently.")

st.caption("Stock legs included: Long Stock P&L vs entry price; covered calls assume you own 100 sh/contract "
           "(stock leg measured from current spot — entry basis unknown). IV held constant in INSTANT mode "
           "(a real crash lifts IV, making short-option marks temporarily worse). T-bill interest not modeled.")

def book_pnl_at(shock: float, mode: str) -> float:
    total = 0.0
    for _, r in book.iterrows():
        spot_r = r["SPOT"]
        if spot_r is None or (isinstance(spot_r, float) and np.isnan(spot_r)):
            continue
        s    = spot_r * (1 + shock)
        ctrs = r["CONTRACTS"]
        prem = r["_PREM"] or 0

        # Pure stock position: P&L vs entry price, per share
        if r["_IS_STOCK"]:
            if prem > 0:
                total += (s - prem) * ctrs
            continue

        k, kl = r["SHORT STRIKE"] or 0, r["_LONG_STRIKE"] or 0
        if not k:
            continue

        # Covered call: add the owned-stock leg ONLY when the stock isn't logged
        # as its own Long Stock row (otherwise that row already carries it)
        if r["_IS_CC"] and r["_CC_STANDALONE"]:
            total += (s - spot_r) * 100 * ctrs

        kind = "put" if r["_IS_PUT"] else "call"
        if mode == "INSTANT SHOCK":
            v = bs_price(s, k, r["_IV"], r["_DTE_REM"], kind=kind)
            if r["_IS_SPREAD"] and kl:
                v -= bs_price(s, kl, r["_IV"], r["_DTE_REM"], kind=kind)
            # Anchor to the live mark: shift the BS curve so 0% shock reprices
            # to the actual current mid (removes BS-vs-market model gap). Single
            # options only — spreads don't store a long-leg mark.
            cm = r["CURRENT MID"]
            if not r["_IS_SPREAD"] and cm is not None and not (isinstance(cm, float) and np.isnan(cm)):
                v += cm - bs_price(spot_r, k, r["_IV"], r["_DTE_REM"], kind=kind)
        else:  # HOLD TO EXPIRY -> intrinsic
            v = max(k - s, 0) if r["_IS_PUT"] else max(s - k, 0)
            if r["_IS_SPREAD"] and kl:
                v -= max(kl - s, 0) if r["_IS_PUT"] else max(s - kl, 0)

        pnl = (prem - v) if r["_IS_SHORT"] else (v - prem)
        total += pnl * 100 * ctrs
    return total

shocks     = np.arange(-0.60, 0.605, 0.01)
curve      = [book_pnl_at(s, stress_mode) for s in shocks]
sel_shock  = st.slider("BASKET SHOCK %", -60, 60, 0, 1) / 100
pnl_at_sel = book_pnl_at(sel_shock, stress_mode)

s1, s2, s3 = st.columns(3)
s1.metric(f"P&L AT {sel_shock:+.0%}", f"${pnl_at_sel:,.0f}")
s2.metric("VS TOTAL CAPITAL", f"{pnl_at_sel/TOTAL_CAPITAL:+.1%}")
dd_ok = pnl_at_sel/TOTAL_CAPITAL > -0.30
s3.metric("DRAWDOWN TOLERANCE (20-30%)", "WITHIN" if dd_ok else "BREACHED")

fig_st = go.Figure()
fig_st.add_scatter(x=shocks*100, y=curve, mode="lines", name="P&L",
                   line=dict(color="#00c8ff", width=2))
fig_st.add_hline(y=0, line_color="#444444", line_width=1)
fig_st.add_hline(y=-0.20*TOTAL_CAPITAL, line_color="#ff9900", line_dash="dot",
                 annotation_text="-20% CAPITAL", annotation_font_color="#ff9900")
fig_st.add_hline(y=-0.30*TOTAL_CAPITAL, line_color="#ff4444", line_dash="dot",
                 annotation_text="-30% CAPITAL", annotation_font_color="#ff4444")
fig_st.add_vline(x=sel_shock*100, line_color="#00e676", line_dash="dash")
fig_st.update_layout(
    paper_bgcolor="#0a0a0a", plot_bgcolor="#0d0d0d",
    font=dict(family="IBM Plex Mono", color="#cccccc", size=11),
    margin=dict(l=40, r=20, t=20, b=40), height=380, showlegend=False,
    xaxis=dict(title="BASKET MOVE %", gridcolor="#1e1e1e", ticksuffix="%"),
    yaxis=dict(title=f"P&L ({stress_mode})", gridcolor="#1e1e1e", tickprefix="$"))
st.plotly_chart(fig_st, use_container_width=True)

st.markdown("---")

# ── Delta exposure by name ────────────────────────────────────────────────────
st.markdown("### DELTA EXPOSURE BY NAME")
delta_by_name = book.groupby("TICKER").agg(
    SECTOR=("SECTOR","first"),
    BUCKET=("BUCKET","first"),
    CASH_AT_RISK=("CASH AT RISK","sum"),
    DOLLAR_DELTA=("$ DELTA","sum"),
    CONTRACTS=("CONTRACTS","sum"),
).reset_index()
delta_by_name["% OF CAPITAL"] = delta_by_name["CASH_AT_RISK"] / TOTAL_CAPITAL
delta_by_name["OVER LIMIT"]   = delta_by_name["% OF CAPITAL"] > MAX_SINGLE_NAME

def color_over(v): return "color:#ff4444;font-weight:600" if v else "color:#00e676"

st.dataframe(
    delta_by_name.style
    .map(color_over, subset=["OVER LIMIT"])
    .format({
        "CASH_AT_RISK":  "${:,.0f}",
        "DOLLAR_DELTA":  "${:,.0f}",
        "% OF CAPITAL":  "{:.1%}",
    }, na_rep="—"),
    use_container_width=True, hide_index=True
)

# ── Exposure by sector ────────────────────────────────────────────────────────
st.markdown("### EXPOSURE BY SECTOR")
by_sector = book.groupby("SECTOR").agg(
    CASH=("CASH AT RISK","sum"),
    DOLLAR_DELTA=("$ DELTA","sum"),
    POSITIONS=("ID","count"),
).reset_index()
by_sector["% OF CAPITAL"] = by_sector["CASH"] / TOTAL_CAPITAL
by_sector["OVER LIMIT"]   = by_sector["% OF CAPITAL"] > MAX_SECTOR

st.dataframe(
    by_sector.style
    .map(color_over, subset=["OVER LIMIT"])
    .format({
        "CASH":         "${:,.0f}",
        "DOLLAR_DELTA": "${:,.0f}",
        "% OF CAPITAL": "{:.1%}",
    }, na_rep="—"),
    use_container_width=True, hide_index=True
)

# ── Exposure by bucket (conviction / risk tier) ───────────────────────────────
st.markdown("### EXPOSURE BY BUCKET")
_ORDER = {"Core": 0, "Growth": 1, "Speculative": 2}
by_bucket = book.groupby("BUCKET").agg(
    CASH=("CASH AT RISK", "sum"),
    DOLLAR_DELTA=("$ DELTA", "sum"),
    POSITIONS=("ID", "count"),
).reset_index()
by_bucket["% OF CAPITAL"] = by_bucket["CASH"] / TOTAL_CAPITAL
def _bucket_target(b):
    if b == "Core":        return f"≥ {MIN_CORE:.0%}"
    if b == "Speculative": return f"≤ {MAX_SPECULATIVE:.0%}"
    return "residual"
def _bucket_status(row):
    b, p = row["BUCKET"], row["% OF CAPITAL"]
    if b == "Core":        return "OK" if p >= MIN_CORE else "UNDER TARGET"
    if b == "Speculative": return "OK" if p <= MAX_SPECULATIVE else "OVER LIMIT"
    return "OK"
by_bucket["TARGET"] = by_bucket["BUCKET"].map(_bucket_target)
by_bucket["STATUS"] = by_bucket.apply(_bucket_status, axis=1)
by_bucket = by_bucket.sort_values("BUCKET", key=lambda s: s.map(lambda b: _ORDER.get(b, 9)))
by_bucket = by_bucket[["BUCKET", "POSITIONS", "CASH", "% OF CAPITAL", "TARGET", "STATUS", "DOLLAR_DELTA"]]

def _status_color(v):
    return "color:#00e676;font-weight:600" if v == "OK" else "color:#ff4444;font-weight:600"

st.dataframe(
    by_bucket.style
    .map(_status_color, subset=["STATUS"])
    .format({"CASH": "${:,.0f}", "% OF CAPITAL": "{:.1%}", "DOLLAR_DELTA": "${:,.0f}"}, na_rep="—"),
    use_container_width=True, hide_index=True
)
st.caption(f"Targets: CORE ≥ {MIN_CORE:.0%} (backbone you want to own) · SPECULATIVE ≤ {MAX_SPECULATIVE:.0%} "
           f"(binary names, keep small) · GROWTH = residual. % measured against total capital.")

st.markdown("---")

# ── Risk limit gauges ─────────────────────────────────────────────────────────
st.markdown("### RISK LIMITS — PASS / FAIL")

spec_cash = book[book["BUCKET"] == "Speculative"]["CASH AT RISK"].sum()
spec_pct  = spec_cash / TOTAL_CAPITAL
core_cash = book[book["BUCKET"] == "Core"]["CASH AT RISK"].sum()
core_pct  = core_cash / TOTAL_CAPITAL

checks = [
    ("% DEPLOYED",         pct_deployed <= MAX_DEPLOYED,
     f"{pct_deployed:.1%}  vs  {MAX_DEPLOYED:.0%} limit",
     pct_deployed, MAX_DEPLOYED),
    ("CASH BUFFER",        cash_buffer >= MIN_CASH_BUFFER,
     f"{cash_buffer:.1%}  vs  {MIN_CASH_BUFFER:.0%} minimum",
     cash_buffer, MIN_CASH_BUFFER),
    ("CORE BUCKET",        core_pct >= MIN_CORE,
     f"{core_pct:.1%}  vs  {MIN_CORE:.0%} minimum",
     core_pct, MIN_CORE),
    ("SPECULATIVE BUCKET", spec_pct <= MAX_SPECULATIVE,
     f"{spec_pct:.1%}  vs  {MAX_SPECULATIVE:.0%} limit",
     spec_pct, MAX_SPECULATIVE),
    ("NET $ DELTA",        abs(total_ddelta) <= MAX_DELTA_TOTAL,
     f"${abs(total_ddelta):,.0f}  vs  ${MAX_DELTA_TOTAL:,.0f} limit",
     abs(total_ddelta), MAX_DELTA_TOTAL),
]

# Stock inventory ceiling (manual §8.3: keep assigned/held stock under ~40%
# so the program stays a put-selling engine). Long Stock at market value +
# covered-call stock legs (100 sh per contract).
stock_val = 0.0
for _, r in book.iterrows():
    spot_r = r["SPOT"]
    if spot_r is None or (isinstance(spot_r, float) and np.isnan(spot_r)):
        continue
    if r["_IS_STOCK"]:
        stock_val += spot_r * r["CONTRACTS"]
    elif r["_IS_CC"] and r["_CC_STANDALONE"]:
        stock_val += spot_r * 100 * r["CONTRACTS"]
stock_pct = stock_val / TOTAL_CAPITAL if TOTAL_CAPITAL else 0
checks.append(("STOCK INVENTORY", stock_pct <= MAX_STOCK_INV,
               f"${stock_val:,.0f} = {stock_pct:.1%}  vs  {MAX_STOCK_INV:.0%} ceiling",
               stock_pct, MAX_STOCK_INV))

# Calls backed by stock (no naked calls): each ticker's covered-call contracts
# need 100 shares apiece in a Long Stock row. Bear call spreads are excluded —
# they're backed by their long call, not stock.
shares_by_tkr = book[book["_IS_STOCK"]].groupby("TICKER")["CONTRACTS"].sum()
naked = []
for tkr, grp in book[book["_IS_CC"]].groupby("TICKER"):
    need = float(grp["CONTRACTS"].sum()) * 100      # shares required (100/contract)
    have = float(shares_by_tkr.get(tkr, 0))         # shares held
    if need > have + 1e-6:
        uncovered_cts = int(np.ceil((need - have) / 100))
        naked.append(f"{tkr}: {uncovered_cts} of {int(grp['CONTRACTS'].sum())} call(s) NAKED "
                     f"(need {int(need)} sh, have {int(have)})")
if naked:
    st.error("🚨 NAKED SHORT CALL — UNLIMITED UPSIDE RISK: " + "  |  ".join(naked) +
             ".  A short call not backed by stock loses without limit if the name rallies. "
             "Buy it back, or add the missing shares, before anything else.")
checks.append(("NO NAKED SHORT CALLS", len(naked) == 0,
               "ALL COVERED" if not naked else " | ".join(naked),
               None, None))

# Per-trade cap (manual: <=2-3% of capital per single trade)
trade_breaches = book[book["CASH AT RISK"] > MAX_PER_TRADE * TOTAL_CAPITAL]
checks.append(("PER-TRADE CAP", trade_breaches.empty,
    "ALL OK" if trade_breaches.empty else
    " | ".join(f"#{r['ID']} {r['TICKER']} ${r['CASH AT RISK']:,.0f} ({r['CASH AT RISK']/TOTAL_CAPITAL:.1%})"
               for _, r in trade_breaches.iterrows()),
    None, None))

name_breaches   = delta_by_name[delta_by_name["OVER LIMIT"]]
sector_breaches = by_sector[by_sector["OVER LIMIT"]]
checks.append(("SINGLE-NAME LIMITS", name_breaches.empty,
    "ALL OK" if name_breaches.empty else
    " | ".join(f"{r['TICKER']} {r['% OF CAPITAL']:.1%}" for _, r in name_breaches.iterrows()),
    None, None))
checks.append(("SECTOR LIMITS", sector_breaches.empty,
    "ALL OK" if sector_breaches.empty else
    " | ".join(f"{r['SECTOR']} {r['% OF CAPITAL']:.1%}" for _, r in sector_breaches.iterrows()),
    None, None))

all_pass = all(ok for _, ok, _, _, _ in checks)
if all_pass:
    st.success("ALL RISK LIMITS PASS")
else:
    st.error("ONE OR MORE RISK LIMITS BREACHED — REVIEW BELOW")

for label, ok, detail, val, lim in checks:
    c_icon, c_label, c_detail, c_bar = st.columns([0.5, 2, 3, 4])
    c_icon.markdown(
        "<span style='color:#00e676;font-size:1.1rem'>PASS</span>" if ok else
        "<span style='color:#ff4444;font-size:1.1rem;font-weight:600'>FAIL</span>",
        unsafe_allow_html=True)
    c_label.markdown(f"**{label}**")
    c_detail.markdown(f"`{detail}`")
    if val is not None and lim is not None and lim > 0:
        fill = min(val / lim, 1.5)
        bar_color = "#ff4444" if val > lim else "#ff9900" if val > lim * 0.85 else "#00c8ff"
        c_bar.markdown(
            f"""<div style='background:#1a1a1a;height:10px;border:1px solid #222;margin-top:6px'>
            <div style='background:{bar_color};height:100%;width:{fill/1.5*100:.0f}%;'></div>
            </div>""",
            unsafe_allow_html=True)

# ── Equity history (daily snapshots, written by the GitHub Actions job) ───────
if db.configured():
    snaps = db.load_portfolio_snapshots()
    if not snaps.empty and "snap_date" in snaps.columns:
        st.markdown("---")
        st.markdown("### P&L HISTORY (DAILY SNAPSHOTS)")
        snaps = snaps.sort_values("snap_date")
        total_line = (pd.to_numeric(snaps.get("realized_pnl"), errors="coerce").fillna(0) +
                      pd.to_numeric(snaps.get("unreal_pnl"),  errors="coerce").fillna(0))
        fig_eq = go.Figure()
        fig_eq.add_scatter(x=snaps["snap_date"], y=total_line, mode="lines+markers",
                           name="REALIZED + UNREALIZED",
                           line=dict(color="#00c8ff", width=2))
        fig_eq.update_layout(
            paper_bgcolor="#0a0a0a", plot_bgcolor="#0d0d0d",
            font=dict(family="IBM Plex Mono", color="#cccccc", size=11),
            margin=dict(l=40, r=20, t=20, b=40), height=320, showlegend=False,
            xaxis=dict(gridcolor="#1e1e1e"), yaxis=dict(gridcolor="#1e1e1e", tickprefix="$"))
        st.plotly_chart(fig_eq, use_container_width=True)
        st.caption("ONE POINT PER TRADING DAY — WRITTEN AUTOMATICALLY AFTER US CLOSE BY THE SNAPSHOT JOB")

st.markdown("---")
st.caption("IV FROM LIVE OPTION CHAIN (1-MIN CACHE) | DELTA USES BLACK-SCHOLES EUROPEAN APPROX | NOT EXECUTION READY")
