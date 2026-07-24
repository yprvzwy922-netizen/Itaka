"""
Roll Finder — pick an open short option, scan later expiries, score roll
candidates (net credit at mid, worst case at cross, delta, annualized roll
yield), and send the chosen roll to the Order Ticket as a single net-credit
spread block.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import datetime
import numpy as np
import pandas as pd
import streamlit as st
import bbg_style
import db
import ticket
from shared import (fetch_spot, fetch_expirations, fetch_chain_exact,
                    bs_put_delta, bs_call_delta, is_third_friday)

bbg_style.inject()

st.title("ROLL FINDER")
st.caption("ROLL AN OPEN SHORT: BUY TO CLOSE THE CURRENT LEG + SELL TO OPEN A LATER EXPIRY, AS ONE NET-CREDIT ORDER")

# ── Pick an open short option from the book ───────────────────────────────────
trades = db.get_trades_df()
ROLLABLE = ("Short Put", "Cash-Secured Put (Wheel)", "Covered Call")
open_opts = pd.DataFrame()
if not trades.empty:
    open_opts = trades[(trades["STATUS"] == "OPEN") &
                       (trades["STRATEGY"].isin(ROLLABLE)) &
                       (trades["SHORT STRIKE"].notna())].copy()

if open_opts.empty:
    st.info("No open short puts / covered calls to roll. Positions come from the Trade Log.")
    st.stop()

def _lbl(i):
    r = open_opts[open_opts["ID"] == i].iloc[0]
    return (f"#{i}  {r['TICKER']}  {r['STRATEGY']}  K{r['SHORT STRIKE']:g}  "
            f"{r['EXPIRY']}  x{int(r['CONTRACTS'])}")

sel_id = st.selectbox("POSITION TO ROLL", open_opts["ID"].tolist(), format_func=_lbl)
pos = open_opts[open_opts["ID"] == sel_id].iloc[0]

tkr        = str(pos["TICKER"])
cur_strike = float(pos["SHORT STRIKE"])
cur_expiry = str(pos["EXPIRY"])
cts        = int(pos["CONTRACTS"])
orig_prem  = float(pos["PREMIUM / CREDIT"]) if pd.notna(pos["PREMIUM / CREDIT"]) else 0.0
opt_type   = "put" if "Put" in str(pos["STRATEGY"]) else "call"

# ── Current leg: buyback cost ─────────────────────────────────────────────────
with st.spinner(f"FETCHING {tkr} CHAINS..."):
    spot = fetch_spot(tkr)
    cur_chain = fetch_chain_exact(tkr, cur_expiry, opt_type, prefer_quotes=True)

if cur_chain is None or np.isnan(spot):
    st.error(f"Couldn't fetch the current chain for {tkr} {cur_expiry}. Try REFRESH or later.")
    st.stop()

cur_chain = cur_chain.copy()
cur_chain["dist"] = (cur_chain["strike"] - cur_strike).abs()
cur_row = cur_chain.loc[cur_chain["dist"].idxmin()]
if float(cur_row["dist"]) > max(0.015 * cur_strike, 0.50):
    st.error(f"Strike {cur_strike:g} not listed on {cur_expiry} — check the position's expiry/strike.")
    st.stop()

buy_bid  = float(cur_row["bid"]);  buy_ask = float(cur_row["ask"])
buy_mid  = float(cur_row["mid"]) if not np.isnan(cur_row["mid"]) else float("nan")
try:
    cur_dte = max((datetime.date.fromisoformat(cur_expiry) - datetime.date.today()).days, 0)
except Exception:
    cur_dte = 0
iv_cur = float(cur_row["impliedVolatility"]) if cur_row["impliedVolatility"] > 0 else 0.35
dfn    = bs_put_delta if opt_type == "put" else bs_call_delta
cur_delta = abs(dfn(spot, cur_strike, iv_cur, max(cur_dte, 1)))

h1, h2, h3, h4, h5 = st.columns(5)
h1.metric("SPOT", f"${spot:.2f}")
h2.metric("BUYBACK (MID)", f"${buy_mid:.2f}" if not np.isnan(buy_mid) else "—",
          help=f"bid {buy_bid:.2f} / ask {buy_ask:.2f} — worst case you pay the ask")
h3.metric("CURRENT DELTA", f"{cur_delta:.2f}")
h4.metric("DTE LEFT", cur_dte)
h5.metric("LEG P&L IF CLOSED",
          f"${(orig_prem - buy_mid)*100*cts:,.0f}" if not np.isnan(buy_mid) else "—",
          help="(original premium − buyback mid) × 100 × contracts — books as realized when you roll")

# The BUYBACK leg must be priceable (NBBO mid or day close). Without any
# price, every candidate's net credit would be fiction — stop clearly.
if np.isnan(buy_mid) or buy_mid <= 0:
    st.error(f"CAN'T PRICE THE BUYBACK LEG — {tkr} {cur_expiry} K{cur_strike:g} has no usable "
             f"price (no quote and no session close). Get the buyback price from your broker "
             f"and price this roll manually.")
    st.stop()
_has_quotes = buy_bid > 0 and buy_ask > 0
if not _has_quotes:
    st.info("PRICING FROM DAY CLOSE (plan has no live quotes) — net credits are close-to-close "
            "estimates; WORST (CROSS) is unavailable. Confirm final prices at the broker.")

st.markdown("---")

# ── Candidate scan controls ───────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
n_exp     = c1.slider("EXPIRIES TO SCAN", 1, 8, 4)
monthlies = c2.checkbox("MONTHLIES ONLY (3rd Friday)", False)
if opt_type == "put":
    strike_mode = c3.selectbox("STRIKES", ["Same or lower (roll down)", "Same strike only"])
else:
    strike_mode = c3.selectbox("STRIKES", ["Same or higher (roll up)", "Same strike only"])
show_debits = c4.checkbox("SHOW DEBIT ROLLS", False,
                          help="Manual rule: roll for a CREDIT — a debit roll pays new money into a "
                               "losing trade. Enable only to evaluate a deliberate defensive "
                               "roll-down (paying to cut assignment risk).")

exps = [e for e in fetch_expirations(tkr) if e > cur_expiry]
if monthlies:
    exps = [e for e in exps if is_third_friday(datetime.date.fromisoformat(e))]
exps = exps[:n_exp]

if not exps:
    st.warning("No later expirations found.")
    st.stop()

# ── Build candidates ──────────────────────────────────────────────────────────
cands = []
skipped_quotes = 0
prog = st.progress(0, text="SCANNING EXPIRIES...")
for j, e in enumerate(exps):
    ch = fetch_chain_exact(tkr, e, opt_type, prefer_quotes=True)
    prog.progress((j + 1) / len(exps), text=f"SCANNING {e}...")
    if ch is None:
        continue
    ch = ch[ch["impliedVolatility"] > 0].copy()
    if strike_mode == "Same strike only":
        ch = ch[(ch["strike"] - cur_strike).abs() < max(0.015 * cur_strike, 0.50)]
    elif opt_type == "put":
        ch = ch[(ch["strike"] <= cur_strike * 1.001) & (ch["strike"] >= cur_strike * 0.60)]
    else:
        ch = ch[(ch["strike"] >= cur_strike * 0.999) & (ch["strike"] <= cur_strike * 1.40)]
    try:
        new_dte    = max((datetime.date.fromisoformat(e) - datetime.date.today()).days, 1)
        added_days = max((datetime.date.fromisoformat(e) -
                          datetime.date.fromisoformat(cur_expiry)).days, 1)
    except Exception:
        continue
    for _, r in ch.iterrows():
        new_mid = float(r["mid"]) if not np.isnan(r["mid"]) else float("nan")
        new_bid = float(r["bid"])
        # The SELL leg needs a price (NBBO mid or day close). When quotes are
        # available, also require a live bid (bid 0 = no buyer right now).
        if np.isnan(new_mid) or (_has_quotes and new_bid <= 0):
            skipped_quotes += 1
            continue
        net_mid   = new_mid - buy_mid                     # fair-value roll credit
        net_worst = (new_bid - buy_ask) if (_has_quotes and new_bid > 0) else np.nan
        k_new     = float(r["strike"])
        delta_new = abs(dfn(spot, k_new, float(r["impliedVolatility"]), new_dte))
        cands.append({
            "EXPIRY": e, "STRIKE": k_new,
            "NET CREDIT (MID)": round(net_mid, 2),
            "WORST (CROSS)":    round(net_worst, 2),
            "NEW DELTA": round(delta_new, 3),
            "Δ DELTA":   round(delta_new - cur_delta, 3),
            "ADDED DAYS": added_days,
            "ANN ROLL YIELD": round((net_mid / k_new) * (365 / added_days), 4) if k_new else np.nan,
            "OI": int(r.get("openInterest", 0) or 0),
            "SPREAD %": round(float(r["spread_pct"]), 3) if not np.isnan(r["spread_pct"]) else np.nan,
        })
prog.empty()

cdf = pd.DataFrame(cands)
if not cdf.empty and not show_debits:
    cdf = cdf[cdf["NET CREDIT (MID)"] > 0]     # manual rule: credit rolls only
if cdf.empty:
    if skipped_quotes:
        st.error(f"NO PRICEABLE CANDIDATES — {skipped_quotes} strike(s) had no live quote "
                 f"(thin chain). Price this roll at your broker.")
    else:
        st.warning("No credit-roll candidates found (all candidates would be debits). "
                   "Consider buying back instead — don't pay to extend a loser.")
    st.stop()
if skipped_quotes:
    st.warning(f"CHECK: {skipped_quotes} candidate strike(s) were excluded — no live quote on the sell leg. "
               f"If a strike you expected is missing, verify it at the broker.")

# Score: ann yield 50% (capital efficiency first — short cycles + redeploy) +
# liquidity 20% (OI depth AND spread) + slippage 15% (fraction of the mid
# credit that survives crossing — relative, so long expiries aren't favored
# just for having bigger absolute credits) + delta reduction 15%.
def _mm(s):
    s = s.astype(float)
    rng = s.max() - s.min()
    return pd.Series(1.0, index=s.index) if (rng == 0 or np.isnan(rng)) else (s - s.min()) / rng

liq  = 0.5 * _mm(np.log1p(cdf["OI"].clip(lower=0))) + \
       0.5 * (1 - _mm(cdf["SPREAD %"].fillna(cdf["SPREAD %"].max())))
# Slippage share; neutral 0.5 when no quotes (close-based pricing has no cross)
slip = (cdf["WORST (CROSS)"] / cdf["NET CREDIT (MID)"]).clip(lower=0).fillna(0.5)
cdf["SCORE"] = (0.50 * _mm(cdf["ANN ROLL YIELD"]) +
                0.20 * liq +
                0.15 * _mm(slip) +
                0.15 * (1 - _mm(cdf["NEW DELTA"]))) * 100
cdf["SCORE"] = cdf["SCORE"].round(1)
# Intuitive reading order: nearest expiry first (score stays as the guide)
cdf = cdf.sort_values(["EXPIRY", "STRIKE"], ascending=[True, False]).reset_index(drop=True)

st.markdown("### ROLL CANDIDATES" + (" — INCLUDING DEBITS" if show_debits else " (CREDIT ONLY)"))
def _sc(v):
    try:
        f = float(v)
        return "color:#00e676;font-weight:700" if f >= 75 else "color:#00c8ff;font-weight:600" if f >= 50 else "color:#888888"
    except Exception:
        return ""
def _wc(v):
    try: return "color:#00e676" if float(v) > 0 else "color:#ff4444"
    except Exception: return ""

st.dataframe(cdf.style.map(_sc, subset=["SCORE"]).map(_wc, subset=["WORST (CROSS)", "NET CREDIT (MID)"]).format({
    "STRIKE": "${:.2f}", "NET CREDIT (MID)": "${:.2f}", "WORST (CROSS)": "${:.2f}",
    "NEW DELTA": "{:.3f}", "Δ DELTA": "{:+.3f}", "ANN ROLL YIELD": "{:.1%}",
    "SPREAD %": "{:.1%}", "SCORE": "{:.0f}",
}, na_rep="—"), use_container_width=True, hide_index=True,
    column_config={"EXPIRY": st.column_config.Column(pinned=True)})
st.caption("SORTED BY EXPIRY (nearest first). SCORE = ann roll yield (50%) + liquidity (20%: OI depth + spread) "
           "+ slippage (15%: share of the mid credit that survives crossing) + delta reduction (15%). "
           "WORST (CROSS) = credit if you cross both bid/asks — red means a cross could turn the roll into a debit. "
           "Manual playbook: roll for a CREDIT at the SAME OR LOWER delta.")

# ── Send to order ticket ──────────────────────────────────────────────────────
st.markdown("### ADD ROLL TO ORDER TICKET")
opts = [f"{r['EXPIRY']}  K{r['STRIKE']:g}  mid {r['NET CREDIT (MID)']:.2f} (score {r['SCORE']:.0f})"
        for _, r in cdf.iterrows()]
sel_i = st.selectbox("CANDIDATE", range(len(opts)), format_func=lambda i: opts[i])
cand = cdf.iloc[sel_i]

# Refresh the editable fields when the candidate changes
_ck = f"{sel_id}|{cand['EXPIRY']}|{cand['STRIKE']}"
if st.session_state.get("roll_last_key") != _ck:
    st.session_state["roll_credit"] = float(cand["NET CREDIT (MID)"])
    st.session_state["roll_cts"]    = cts
    st.session_state["roll_last_key"] = _ck

a1, a2, a3, a4 = st.columns([1.4, 1.4, 1.4, 3])
r_cts    = a1.number_input("CONTRACTS", min_value=1, max_value=cts, step=1, key="roll_cts",
                           help="Up to the position size — roll part or all")
r_credit = a2.number_input("NET CREDIT (+) / DEBIT (−) LIMIT", min_value=-100.0, step=0.05, key="roll_credit",
                           help=f"Mid {cand['NET CREDIT (MID)']:.2f} / worst {cand['WORST (CROSS)']:.2f}. "
                                f"Start near mid and work down.")
a3.markdown(" "); a3.markdown(" ")
if a3.button("＋ ADD ROLL", type="primary", use_container_width=True):
    ticket.add_roll_to_ticket(tkr, opt_type, r_cts, cur_expiry, cur_strike,
                              cand["EXPIRY"], float(cand["STRIKE"]), r_credit)
    st.success("Added roll to ticket.")
a4.markdown(" "); a4.markdown(" ")
if a4.button(f"VIEW TICKET ({len(ticket.get_ticket())})", use_container_width=True):
    st.switch_page("pages/8_Order_Ticket.py")

st.markdown("---")
st.caption("AFTER THE FILL: book it in the Trade Log yourself — close the old leg (status ROLLED, "
           "buyback price) and add the new leg as a fresh trade. The ticket never touches the log.")
