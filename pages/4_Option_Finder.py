"""
Option Finder — deep dive on any ticker, with watchlist management
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import datetime
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
import ticket
import db
import bbg_style
from shared import (get_watchlist, add_to_watchlist, remove_from_watchlist,
                    fetch_spot, fetch_chain, bs_put_delta, bs_call_delta,
                    ann_yield, ann_roll, moneyness, SECTORS)

bbg_style.inject()


c_nav1, _ = st.columns([1,9])
with c_nav1:
    if st.button("HOME"): st.switch_page("pages/0_Home.py")

st.title("OPTION FINDER")
st.caption("FULL CHAIN FOR ANY TICKER | ALL STRIKES | ALL METRICS | ROLL CALCULATOR")

# ── Watchlist quick-select buttons ────────────────────────────────────────────
wl = get_watchlist()
wl_tickers = [w["ticker"] for w in wl]

st.markdown("### QUICK SELECT")
# Display as a grid of buttons — 10 per row
cols_per_row = 10
rows_needed  = (len(wl_tickers) + cols_per_row - 1) // cols_per_row

selected_ticker = st.session_state.get("finder_ticker", "")

for row_i in range(rows_needed):
    btn_cols = st.columns(cols_per_row)
    for col_i, col in enumerate(btn_cols):
        idx = row_i * cols_per_row + col_i
        if idx < len(wl_tickers):
            tkr = wl_tickers[idx]
            is_sel = tkr == selected_ticker
            label = f"[ {tkr} ]" if is_sel else tkr
            if col.button(label, key=f"qb_{tkr}", use_container_width=True,
                          type="primary" if is_sel else "secondary"):
                st.session_state["finder_ticker"] = tkr
                st.rerun()
        elif idx == len(wl_tickers):
            # "+" quick-add button at the end of the last ticker
            if col.button("＋", key="qb_plus", use_container_width=True,
                          help="Quick-add a new ticker to the watchlist",
                          type="secondary"):
                st.session_state["show_quick_add"] = True

# Quick-add inline form (shows below grid when "+" is pressed)
if st.session_state.get("show_quick_add"):
    with st.container():
        st.markdown("**QUICK ADD TICKER TO WATCHLIST**")
        qa1, qa2, qa3, qa4, qa5, qa6, qa7 = st.columns([2,2,2,2,1,1,1])
        qa_tick = qa1.text_input("TICKER", key="qa_tick").upper().strip()
        qa_co   = qa2.text_input("COMPANY NAME", key="qa_co")
        qa_sec  = qa3.selectbox("SECTOR", SECTORS, key="qa_sec")
        qa_bkt  = qa4.selectbox("BUCKET", ["Core","Growth","Speculative"], key="qa_bkt")
        qa_conv = qa5.number_input("CONVICTION", 1, 5, 3, key="qa_conv")
        qa_band = qa6.selectbox("BAND", ["Income","Wheel"], key="qa_band")
        qa7.markdown(" ")
        qa7.markdown(" ")
        if qa7.button("ADD", type="primary", use_container_width=True) and qa_tick:
            add_to_watchlist(qa_tick, qa_co, qa_sec, qa_bkt, qa_conv, qa_band)
            st.session_state["finder_ticker"] = qa_tick
            st.session_state["show_quick_add"] = False
            st.success(f"{qa_tick} added to watchlist.")
            st.rerun()

st.markdown("---")

# ── Controls ──────────────────────────────────────────────────────────────────
c1, c2, c3, c4, c5 = st.columns([2,2,2,2,1])
with c1:
    custom = st.text_input("TYPE ANY TICKER", value=st.session_state.get("finder_ticker","")).upper().strip()
    if custom: st.session_state["finder_ticker"] = custom
    ticker = st.session_state.get("finder_ticker", "")
with c2:
    tenor = st.selectbox("TENOR", ["1M (~30 DTE)","45 DAYS","3M (MONTHLY)","6M (MONTHLY)","CUSTOM"],
                         key="finder_tenor")
    dte_map = {"1M (~30 DTE)":30,"45 DAYS":45,"3M (MONTHLY)":90,"6M (MONTHLY)":180}
    # 3M / 6M snap to the standard 3rd-Friday monthly contract (deepest liquidity)
    monthly_only = tenor in ("3M (MONTHLY)","6M (MONTHLY)")
    if tenor == "CUSTOM":
        target_dte = st.number_input("CUSTOM DTE", min_value=7, max_value=730, value=35, step=1,
                                     key="finder_custom_dte")
    else:
        target_dte = dte_map[tenor]
with c3:
    opt_type = st.selectbox("OPTION TYPE", ["PUTS","CALLS"], key="finder_opt_type")
with c4:
    band_label = st.selectbox("DELTA BAND", ["INCOME 0.15-0.30","WHEEL 0.30-0.45","ALL (0.10-0.70)"],
                              key="finder_band")
    lo = {"INCOME 0.15-0.30":0.15,"WHEEL 0.30-0.45":0.30}.get(band_label, 0.10)
    hi = {"INCOME 0.15-0.30":0.30,"WHEEL 0.30-0.45":0.45}.get(band_label, 0.70)
with c5:
    st.markdown(" ")
    st.markdown(" ")
    run = st.button("LOAD", type="primary", use_container_width=True)

# ── Watchlist management ──────────────────────────────────────────────────────
with st.expander("MANAGE WATCHLIST (add / remove)"):
    st.caption("Changes apply for this session only. Reload the page to reset to defaults.")
    mc1, mc2, mc3, mc4, mc5, mc6 = st.columns(6)
    m_tick = mc1.text_input("TICKER", key="m_tick").upper()
    m_co   = mc2.text_input("COMPANY", key="m_co")
    m_sec  = mc3.selectbox("SECTOR", SECTORS, key="m_sec")
    m_bkt  = mc4.selectbox("BUCKET", ["Core","Growth","Speculative"], key="m_bkt")
    m_conv = mc5.slider("CONVICTION", 1, 5, 3, key="m_conv")
    m_band = mc6.selectbox("BAND", ["Income","Wheel"], key="m_band")
    col_add, col_rem = st.columns(2)
    with col_add:
        if st.button("ADD TO WATCHLIST", use_container_width=True) and m_tick:
            add_to_watchlist(m_tick, m_co, m_sec, m_bkt, m_conv, m_band)
            st.success(f"{m_tick} added.")
            st.rerun()
    with col_rem:
        rem_tick = st.selectbox("REMOVE", [""] + wl_tickers, key="rem_tick")
        if st.button("REMOVE FROM WATCHLIST", use_container_width=True) and rem_tick:
            remove_from_watchlist(rem_tick)
            st.success(f"{rem_tick} removed.")
            st.rerun()
    st.markdown("---")
    st.caption("Pull in any newly-added default names (non-destructive — won't touch your edits).")
    if st.button("SYNC DEFAULT NAMES → WATCHLIST", use_container_width=True):
        from shared import DEFAULT_WATCHLIST
        n = db.sync_missing_watchlist(DEFAULT_WATCHLIST)
        st.success(f"Added {n} new name(s)." if n else "Already up to date.")
        st.rerun()

# ── Roll calculator sidebar ───────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ROLL CALCULATOR")
    st.caption("Annualized yield of rolling a short position to a later expiry.")
    rb   = st.number_input("BUYBACK PREMIUM ($/SHARE)", 0.0, step=0.01, value=0.50)
    rn   = st.number_input("NEW PREMIUM ($/SHARE)",     0.0, step=0.01, value=1.20)
    rsk  = st.number_input("NEW STRIKE",                0.0, step=0.50, value=100.0)
    rd   = st.number_input("DTE REMAINING",             1,   value=10)
    rnd  = st.number_input("NEW EXPIRY DTE",            1,   value=35)
    if rnd > rd and rsk > 0:
        nc = rn - rb
        ar = ann_roll(nc, rsk, rnd - rd)
        st.metric("ANN ROLL YIELD", f"{ar:.1%}")
        st.metric("NET CREDIT / SHARE", f"${nc:.2f}")
        st.metric("NET CREDIT / CONTRACT", f"${nc*100:.2f}")
    else:
        st.caption("Set new DTE > remaining DTE to compute.")

if not ticker:
    st.info("SELECT A TICKER ABOVE OR TYPE ONE IN THE BOX, THEN CLICK LOAD.")
    st.stop()

# A button is only True for the single rerun it was clicked on. Remember that
# LOAD was pressed so interacting with widgets below (e.g. the payoff strike
# selector) doesn't reset the page. After the first LOAD the view stays live
# and re-fetches automatically when ticker/tenor/type/band change (5-min cache).
if run:
    st.session_state["finder_loaded"] = True
if not st.session_state.get("finder_loaded"):
    st.info(f"TICKER: {ticker} — CLICK LOAD TO FETCH CHAIN.")
    st.stop()

# ── Fetch chain ───────────────────────────────────────────────────────────────
with st.spinner(f"FETCHING {ticker}..."):
    spot = fetch_spot(ticker)
    opt  = "put" if opt_type == "PUTS" else "call"
    # prefer_quotes: this page prices ORDERS -> needs real bid/ask (Yahoo
    # first); Massive close-pricing only as fallback
    chain, expiry, dte = fetch_chain(ticker, target_dte, opt,
                                     monthly_only=monthly_only, prefer_quotes=True)

if chain is None or chain.empty:
    st.error(f"No options data found for {ticker}.")
    st.stop()

st.markdown(f"### {ticker}  |  SPOT: ${spot:.2f}  |  EXPIRY: {expiry}  |  DTE: {dte}")
st.markdown("---")

# ── Enrich (vectorized) ───────────────────────────────────────────────────────
chain = chain[chain["impliedVolatility"] > 0].copy()
is_put = opt == "put"
strike_v = chain["strike"].values
mid_v    = chain["mid"].values

delta_fn = bs_put_delta if is_put else bs_call_delta
chain["delta"]       = delta_fn(spot, strike_v, chain["impliedVolatility"].values, dte)

# Moneyness via vectorized thresholds (1% band around spot)
band = 0.01 * spot
if is_put:
    chain["moneyness"] = np.where(strike_v < spot - band, "OTM",
                          np.where(strike_v > spot + band, "ITM", "ATM"))
    chain["cushion_pct"] = (spot - strike_v) / spot
    chain["breakeven"]   = chain["strike"] - chain["mid"]
    chain["eff_entry"]   = (strike_v - mid_v) / spot - 1
else:
    chain["moneyness"] = np.where(strike_v > spot + band, "OTM",
                          np.where(strike_v < spot - band, "ITM", "ATM"))
    chain["cushion_pct"] = (strike_v - spot) / spot
    chain["breakeven"]   = chain["strike"] + chain["mid"]
    chain["eff_entry"]   = (strike_v + mid_v) / spot - 1

chain["period_yield"] = mid_v / strike_v                    # actual yield over the trade's life
chain["ann_yield"]    = (mid_v / strike_v) * (365.0 / dte)
chain["cash_1ct"]     = chain["strike"] * 100
chain["cts_25k"]      = np.floor(25000.0 / (strike_v * 100)).astype(int)  # contracts per $25k tranche
chain["illiquid"]     = chain["spread_pct"].fillna(1) > 0.10

# Drop any strikes whose delta could not be computed, then apply the band filter.
# Every band (including ALL) is bounded — ALL just uses a wide 0.10-0.70 window
# so deep-OTM/ITM noise is trimmed.
chain = chain[chain["delta"].notna()].copy()
chain = chain[(chain["delta"] >= lo) & (chain["delta"] <= hi)]
if "ALL" in band_label:
    st.caption("BAND = ALL → wide 0.10-0.70 delta window (deep-OTM and deep-ITM strikes trimmed). "
               "Pick INCOME or WHEEL to narrow further.")

if chain.empty:
    st.warning("NO STRIKES IN THIS DELTA BAND. TRY A DIFFERENT TENOR OR TICKER.")
    st.stop()

# ── Optimal-strike scoring ────────────────────────────────────────────────────
# Score 0-100 balancing YIELD, CUSHION (safety), DELTA proximity to the band
# target, and LIQUIDITY. Income favours safety; Wheel tolerates more delta for
# premium because assignment at a good entry is acceptable.
if "INCOME" in band_label:
    target_delta = 0.225          # midpoint of 0.15-0.30
    W = {"yield":0.25, "cushion":0.35, "delta":0.25, "liq":0.15}
elif "WHEEL" in band_label:
    target_delta = 0.375          # midpoint of 0.30-0.45
    W = {"yield":0.40, "cushion":0.25, "delta":0.20, "liq":0.15}
else:  # ALL — default to income-style safety
    target_delta = 0.25
    W = {"yield":0.30, "cushion":0.30, "delta":0.25, "liq":0.15}

def _minmax(s):
    s = s.astype(float)
    rng = s.max() - s.min()
    if rng == 0 or np.isnan(rng):
        return pd.Series(1.0, index=s.index)   # all equal → neutral full marks
    return (s - s.min()) / rng

# Component scores (higher = better)
sc_yield   = _minmax(chain["ann_yield"])
sc_cushion = _minmax(chain["cushion_pct"])
sc_delta   = 1 - _minmax((chain["delta"] - target_delta).abs())   # closer to target = higher
sc_liq     = 1 - _minmax(chain["spread_pct"].fillna(chain["spread_pct"].max()))  # tighter spread = higher

chain["score"] = (
    W["yield"]   * sc_yield   +
    W["cushion"] * sc_cushion +
    W["delta"]   * sc_delta   +
    W["liq"]     * sc_liq
) * 100
chain["score"] = chain["score"].round(1)

# ── Display ───────────────────────────────────────────────────────────────────
# Column order: STRIKE pinned first; VOLUME after ANN YIELD; SCORE after
# VOLUME; CTS / $25K (contracts per $25k tranche) after SCORE.
COLS = {
    "strike":          "STRIKE",
    "moneyness":       "MONEYNESS",
    "impliedVolatility":"IV",
    "delta":           "DELTA",
    "bid":             "BID",
    "mid":             "MID",
    "period_yield":    "YIELD",
    "ann_yield":       "ANN YIELD",
    "volume":          "VOLUME",
    "score":           "SCORE",
    "cts_25k":         "CTS / $25K",
    "cushion_pct":     "CUSHION / UPSIDE",
    "breakeven":       "BREAKEVEN",
    "eff_entry":       "EFF ENTRY VS SPOT",
    "cash_1ct":        "CASH SECURED (1CT)",
    "openInterest":    "OI",
    "spread_pct":      "SPREAD %",
    "illiquid":        "ILLIQUID",
}
# Keep the table sorted by strike (score lives in its own column on the right)
chain = chain.sort_values("strike")

present = [c for c in COLS if c in chain.columns]
disp = chain[present].rename(columns=COLS).copy()

def cm(v):
    return {"OTM":"background-color:#0a1a0a","ATM":"background-color:#1a1400",
            "ITM":"background-color:#1a0a0a"}.get(v,"")
def ci(v): return "color:#ff9900;font-weight:600" if v else ""
def cs(v):
    try:
        f = float(v)
        return "color:#00e676;font-weight:700" if f >= 75 else "color:#00c8ff;font-weight:600" if f >= 50 else "color:#888888"
    except: return ""

styled = (disp.style
    .map(cm, subset=["MONEYNESS"])
    .map(ci, subset=["ILLIQUID"])
    .map(cs, subset=["SCORE"])
    .format({
        "SCORE":            "{:.1f}",
        "STRIKE":           "${:.2f}",
        "IV":               "{:.1%}",
        "DELTA":            "{:.3f}",
        "BID":              "${:.2f}",
        "MID":              "${:.2f}",
        "YIELD":            "{:.2%}",
        "ANN YIELD":        "{:.1%}",
        "CTS / $25K":       "{:.0f}",
        "CUSHION / UPSIDE": "{:.1%}",
        "BREAKEVEN":        "${:.2f}",
        "EFF ENTRY VS SPOT":"{:.1%}",
        "CASH SECURED (1CT)":"${:,.0f}",
        "SPREAD %":         "{:.1%}",
    }, na_rep="—"))

st.dataframe(styled, use_container_width=True, hide_index=True,
             column_config={"STRIKE": st.column_config.Column(pinned=True)})

# ── Optimal strike highlight (top score) ──────────────────────────────────────
best = chain.sort_values("score", ascending=False).iloc[0]
band_name = "INCOME" if "INCOME" in band_label else "WHEEL" if "WHEEL" in band_label else "BALANCED"
st.success(
    f"OPTIMAL {band_name} STRIKE (SCORE {best['score']:.0f}/100):  "
    f"STRIKE ${best['strike']:.2f}  |  "
    f"DELTA {best['delta']:.3f}  |  "
    f"ANN YIELD {best['ann_yield']:.1%}  |  "
    f"CUSHION {best['cushion_pct']:.1%}  |  "
    f"BREAKEVEN ${best['breakeven']:.2f}"
)
st.caption(
    f"SCORE = balance of yield, cushion, delta-fit, and liquidity.  "
    f"{band_name} weights → "
    f"YIELD {W['yield']:.0%} · CUSHION {W['cushion']:.0%} · "
    f"DELTA-FIT {W['delta']:.0%} (target {target_delta:.2f}) · LIQUIDITY {W['liq']:.0%}.  "
    f"Highest raw yield is usually the riskiest strike — score rewards the best risk-adjusted strike instead."
)

if chain["illiquid"].any():
    st.warning("ONE OR MORE STRIKES HAVE BID/ASK SPREAD > 10% — VERIFY LIQUIDITY WITH BROKER.")

# ── Payoff at expiry ──────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("### PAYOFF AT EXPIRY (SHORT, 1 CONTRACT)")

strikes_list = chain["strike"].tolist()
default_idx  = strikes_list.index(best["strike"]) if best["strike"] in strikes_list else 0
pp1, _ = st.columns([2, 8])
sel_strike = pp1.selectbox("STRIKE", strikes_list, index=default_idx,
                           format_func=lambda k: f"${k:.2f}")
sel_row  = chain[chain["strike"] == sel_strike].iloc[0]
sel_prem = float(sel_row["mid"]) if not np.isnan(sel_row["mid"]) else float(sel_row["bid"])

# Live metrics for the selected strike (update on every change)
pm1, pm2, pm3, pm4, pm5, pm6 = st.columns(6)
pm1.metric("PREMIUM (MID)", f"${sel_prem:.2f}")
pm2.metric("YIELD",         f"{sel_row['period_yield']:.2%}", help="Premium / strike over the trade's life")
pm3.metric("ANN YIELD",     f"{sel_row['ann_yield']:.1%}",    help="Period yield x 365/DTE")
pm4.metric("SCORE",         f"{sel_row['score']:.0f}/100")
pm5.metric("DELTA",         f"{sel_row['delta']:.3f}")
pm6.metric("CTS / $25K",    f"{int(sel_row['cts_25k'])}",     help="Contracts a $25k tranche covers at this strike")

S = np.linspace(spot * 0.55, spot * 1.30, 300)
intrinsic = np.maximum(sel_strike - S, 0) if opt == "put" else np.maximum(S - sel_strike, 0)
payoff = (sel_prem - intrinsic) * 100
be = sel_strike - sel_prem if opt == "put" else sel_strike + sel_prem

fig_po = go.Figure()
fig_po.add_scatter(x=S, y=payoff, mode="lines", line=dict(color="#00c8ff", width=2),
                   fill="tozeroy", fillcolor="rgba(0,200,255,0.06)")
fig_po.add_hline(y=0, line_color="#444444", line_width=1)
fig_po.add_vline(x=spot, line_color="#00e676", line_dash="dash",
                 annotation_text=f"SPOT ${spot:.2f}", annotation_font_color="#00e676")
fig_po.add_vline(x=sel_strike, line_color="#00c8ff", line_dash="dot",
                 annotation_text=f"STRIKE ${sel_strike:.2f}", annotation_font_color="#00c8ff")
fig_po.add_vline(x=be, line_color="#ff9900", line_dash="dot",
                 annotation_text=f"BREAKEVEN ${be:.2f}", annotation_font_color="#ff9900",
                 annotation_position="bottom right")
fig_po.update_layout(
    paper_bgcolor="#0a0a0a", plot_bgcolor="#0d0d0d",
    font=dict(family="IBM Plex Mono", color="#cccccc", size=11),
    margin=dict(l=40, r=20, t=20, b=40), height=380, showlegend=False,
    xaxis=dict(title="UNDERLYING AT EXPIRY", gridcolor="#1e1e1e", tickprefix="$"),
    yaxis=dict(title="P&L PER CONTRACT", gridcolor="#1e1e1e", tickprefix="$"))
st.plotly_chart(fig_po, use_container_width=True)
st.caption(f"MAX PROFIT ${sel_prem*100:,.0f} (PREMIUM)  |  "
           f"BREAKEVEN ${be:.2f} ({(be-spot)/spot:+.1%} FROM SPOT)  |  "
           f"GTC BUY-TO-CLOSE TARGET (50%): ${sel_prem/2:.2f}")

# ── Add to order ticket ───────────────────────────────────────────────────────
st.markdown("### ADD TO ORDER TICKET")
sel_bid = float(sel_row["bid"]) if not np.isnan(sel_row["bid"]) else sel_prem
# Whenever the strike changes, refresh PRICE (to the bid) and CONTRACTS (to the
# $25k-tranche size) — they're still editable before you add.
if st.session_state.get("at_last_strike") != sel_strike:
    st.session_state["at_price"] = round(sel_bid, 2)
    st.session_state["at_cts"]   = int(sel_row["cts_25k"]) if sel_row["cts_25k"] >= 1 else 1
    st.session_state["at_last_strike"] = sel_strike

at1, at2, at3, at4, at5 = st.columns([1.2, 1.2, 1.4, 1.2, 2])
at_action = at1.selectbox("ACTION", ["sell to open", "buy to close", "buy to open", "sell to close"],
                          key="at_action")
at_cts    = at2.number_input("CONTRACTS", min_value=1, step=1, key="at_cts",
                             help="Defaults to the $25k-tranche size")
at_price  = at3.number_input("PRICE (BID)", min_value=0.0, step=0.01, key="at_price",
                             help="Defaults to the live bid — adjust to your limit")
at4.markdown(" "); at4.markdown(" ")
if at4.button("＋ ADD", type="primary", use_container_width=True):
    ticket.add_to_ticket(at_action, ticker, expiry, opt, sel_strike, at_price, at_cts)
    st.success("Added: " + ticket.format_line(ticket.get_ticket()[-1]))
n_ticket = len(ticket.get_ticket())
at5.markdown(" ")
if at5.button(f"VIEW TICKET ({n_ticket})", use_container_width=True):
    st.switch_page("pages/8_Order_Ticket.py")

st.markdown("---")
st.caption("DECISION SUPPORT ONLY | ALWAYS RECONCILE PREMIUM, IV, AND DELTA WITH BROKER LIVE CHAIN BEFORE TRADING")
