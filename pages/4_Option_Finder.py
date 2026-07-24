"""
Option Finder — per-ticker deep-dive on put strikes.

Adapted for the Itaka app: password-guarded (bbg_style.inject), uses the Supabase
watchlist and the same Massive→Yahoo data ladder as the rest of the app
(shared.fetch_chain with prefer_quotes=True, i.e. bid/ask first for order pricing,
Massive close as fallback). Strikes can be pushed straight to the Order Ticket.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
import streamlit as st
import bbg_style
import shared
import ticket
from utils import math as M

bbg_style.inject()

RISK_FREE = 0.053

# ── Nav ───────────────────────────────────────────────────────────────────────
c1, c2, _ = st.columns([1, 2, 7])
with c1:
    if st.button("HOME"): st.switch_page("pages/0_Home.py")
with c2:
    if st.button("→ ORDER TICKET"): st.switch_page("pages/8_Order_Ticket.py")

st.title("OPTION FINDER")
st.caption("Pick a ticker, tenor and delta band to see all matching put strikes. "
           "Decision support — reconcile with your broker before trading.")

# ── Controls ──────────────────────────────────────────────────────────────────
wl = shared.get_watchlist()
tickers = sorted({w["ticker"] for w in wl}) if wl else []

col1, col2, col3, col4 = st.columns(4)
with col1:
    custom = st.text_input("Type any ticker").strip().upper()
    pick   = st.selectbox("or watchlist ticker", tickers) if tickers else ""
    ticker = custom or (pick or "")
with col2:
    tenor = st.selectbox("Tenor", ["1M (30–45 DTE)", "3M (80–100 DTE)", "6M (~180 DTE)", "Custom DTE"])
    target_dte = {"1M (30–45 DTE)": 35, "3M (80–100 DTE)": 90, "6M (~180 DTE)": 180}.get(tenor)
    if tenor == "Custom DTE":
        target_dte = int(st.number_input("DTE", min_value=7, max_value=365, value=35))
with col3:
    band = st.selectbox("Delta band", ["Income (0.15–0.30)", "Wheel (0.30–0.45)", "All"])
    delta_lo = {"Income (0.15–0.30)": 0.05, "Wheel (0.30–0.45)": 0.20}.get(band, 0.0)
    delta_hi = {"Income (0.15–0.30)": 0.45, "Wheel (0.30–0.45)": 0.65}.get(band, 1.0)
with col4:
    st.markdown(" ")
    run = st.button("LOAD CHAIN", type="primary", use_container_width=True)

# ── Roll calculator (sidebar) ─────────────────────────────────────────────────
with st.sidebar:
    st.header("ROLL CALCULATOR")
    st.caption("Annualized roll for closing a position and opening a longer-dated one.")
    rc_buyback = st.number_input("Buyback premium (per share)", 0.0, value=0.50, step=0.01)
    rc_new_prem = st.number_input("New premium (per share)", 0.0, value=1.20, step=0.01)
    rc_strike_new = st.number_input("New strike", 0.0, value=100.0, step=0.50)
    rc_dte_rem = int(st.number_input("DTE remaining (current)", 1, value=10))
    rc_dte_new = int(st.number_input("DTE (new expiry)", 1, value=35))
    if rc_dte_new > rc_dte_rem and rc_strike_new > 0:
        net_cr = rc_new_prem - rc_buyback
        roll_ann = M.annualized_roll(net_cr, rc_strike_new, rc_dte_new - rc_dte_rem)
        st.metric("Annualized roll", f"{roll_ann:.1%}")
        st.metric("Net credit / share", f"${net_cr:.2f}")
    else:
        st.info("New DTE must exceed remaining DTE.")

if not ticker or not run:
    st.info("Select a ticker and click **LOAD CHAIN**.")
    st.stop()

# ── Fetch (Massive-aware via shared.py) ───────────────────────────────────────
with st.spinner(f"Fetching chain for {ticker}…"):
    spot = shared.fetch_spot(ticker)
    chain, expiry, dte = shared.fetch_chain(ticker, target_dte, "put", prefer_quotes=True)

if chain is None or getattr(chain, "empty", True) or not spot or spot != spot:
    st.error("No options data available for this ticker.")
    st.stop()

chain = chain.copy()
# Defensive: not every source populates every column (Massive vs Yahoo).
for c in ["impliedVolatility", "bid", "mid", "spread_pct", "openInterest", "volume"]:
    if c not in chain.columns:
        chain[c] = np.nan

st.subheader(f"{ticker}  •  Spot **${spot:.2f}**  •  Expiry **{expiry}**  ({dte} DTE)")

# ── Enrich ────────────────────────────────────────────────────────────────────
def _delta(r):
    iv = r["impliedVolatility"]
    if iv is None or iv != iv or iv <= 0:
        return np.nan
    return M.bs_put_delta(spot, r["strike"], iv, dte, RISK_FREE)

chain["delta"]           = chain.apply(_delta, axis=1)
chain["moneyness"]       = chain["strike"].apply(lambda k: M.moneyness(spot, k))
chain["static_yield"]    = chain.apply(lambda r: M.static_yield(r["mid"], r["strike"]), axis=1)
chain["ann_yield"]       = chain.apply(lambda r: M.annualized_yield(r["mid"], r["strike"], dte), axis=1)
chain["cushion"]         = chain["strike"].apply(lambda k: M.downside_cushion(spot, k))
chain["breakeven"]       = chain.apply(lambda r: M.breakeven(r["strike"], r["mid"]), axis=1)
chain["eff_entry"]       = chain.apply(lambda r: M.effective_entry_vs_spot(r["strike"], r["mid"], spot), axis=1)
chain["cash_secured_1ct"]= chain["strike"] * 100
chain["illiquid"]        = chain["spread_pct"].fillna(1.0) > 0.10

if band != "All":
    chain = chain[(chain["delta"] >= delta_lo) & (chain["delta"] <= delta_hi)]

if chain.empty:
    st.warning("No strikes in this delta band for the selected expiry. Try 'All' "
               "(or the source may not report IV, so delta can't be computed).")
    st.stop()

chain = chain.sort_values("strike").reset_index(drop=True)

# ── Display table ─────────────────────────────────────────────────────────────
DISP = {
    "strike": "Strike", "moneyness": "Moneyness", "impliedVolatility": "Impl. Vol",
    "delta": "Delta", "bid": "Bid", "mid": "Mid", "static_yield": "Static Yield",
    "ann_yield": "Ann. Yield", "cushion": "Cushion", "breakeven": "Breakeven",
    "eff_entry": "Eff. Entry vs Spot", "cash_secured_1ct": "Cash Secured (1ct)",
    "openInterest": "OI", "volume": "Volume", "spread_pct": "Bid/Ask Spread %",
    "illiquid": "Illiquid ⚠️",
}
present = [c for c in DISP if c in chain.columns]
disp = chain[present].rename(columns=DISP)

def color_moneyness(v):
    return {"OTM": "background-color:#1a3a1a", "ATM": "background-color:#3a3a00",
            "ITM": "background-color:#3a1a1a"}.get(v, "")
def color_illiquid(v):
    return "color:orange;font-weight:bold" if v else ""

st.dataframe(
    disp.style
        .map(color_moneyness, subset=["Moneyness"])
        .map(color_illiquid, subset=["Illiquid ⚠️"])
        .format({
            "Strike": "${:.2f}", "Impl. Vol": "{:.1%}", "Delta": "{:.3f}",
            "Bid": "${:.2f}", "Mid": "${:.2f}", "Static Yield": "{:.2%}",
            "Ann. Yield": "{:.1%}", "Cushion": "{:.1%}", "Breakeven": "${:.2f}",
            "Eff. Entry vs Spot": "{:.1%}", "Cash Secured (1ct)": "${:,.0f}",
            "Bid/Ask Spread %": "{:.1%}",
        }, na_rep="—"),
    use_container_width=True, hide_index=True)

# ── Best-in-band ──────────────────────────────────────────────────────────────
if chain["ann_yield"].notna().any():
    best = chain.sort_values("ann_yield", ascending=False).iloc[0]
    st.success(f"**Best yield in band:** Strike **${best['strike']:.2f}** · "
               f"Delta **{best['delta']:.3f}** · Ann. yield **{best['ann_yield']:.1%}** · "
               f"Cushion **{best['cushion']:.1%}** · Breakeven **${best['breakeven']:.2f}**")
if chain["illiquid"].any():
    st.warning("⚠️ One or more strikes have bid/ask spread >10% — verify size and liquidity with your broker.")

# ── Send a strike to the Order Ticket ─────────────────────────────────────────
st.markdown("### ADD A STRIKE TO THE ORDER TICKET")
oc1, oc2, oc3, oc4 = st.columns([2, 1, 1, 2])
sel_strike = oc1.selectbox("Strike", chain["strike"].tolist(),
                           format_func=lambda k: f"${k:.2f}")
row = chain[chain["strike"] == sel_strike].iloc[0]
default_px = float(row["mid"]) if pd.notna(row["mid"]) else 0.0
sel_px  = oc2.number_input("Price", min_value=0.0, value=round(default_px, 2), step=0.05)
sel_cts = int(oc3.number_input("Contracts", min_value=1, value=1, step=1))
oc4.markdown(" ")
if oc4.button("ADD TO ORDER TICKET", type="primary", use_container_width=True):
    ticket.add_to_ticket("sell to open", ticker, expiry, "put", sel_strike, sel_px, sel_cts)
    st.success(f"Added: sell to open {sel_cts} × {ticker} {expiry} P{sel_strike:g} @ ${sel_px:.2f}. "
               f"Open the Order Ticket to copy the broker message.")

st.caption("⚠️ Decision support only. Reconcile premium, IV and delta against your broker's live "
           "chain before submitting any order.")
