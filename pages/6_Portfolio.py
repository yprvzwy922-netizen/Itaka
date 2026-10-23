"""
Portfolio & Risk — risk status, open positions, assignment planner, held stock,
risk detail + breach history, stress test.

Positions are priced by book.py (via shared.build_book) and risk is measured by
risk.py — the same engine behind the Fund headline NAV, the Option Finder
pre-trade check and the nightly alert email.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import bbg_style
import db
import ticket
import risk
import book as bk
from shared import build_book, fund_nav, sector_map

bbg_style.inject()

GREEN, AMBER, RED = "#00e676", "#ff9900", "#ff4444"
STATUS_COLOR = {"ok": GREEN, "warn": AMBER, "breach": RED}
STATUS_TEXT = {"ok": "OK", "warn": "WATCH", "breach": "BREACH"}
LAYOUT = dict(paper_bgcolor="#0a0a0a", plot_bgcolor="#0d0d0d",
              font=dict(family="IBM Plex Mono", color="#cccccc", size=11))

c_nav1, _ = st.columns([1, 9])
with c_nav1:
    if st.button("HOME"): st.switch_page("pages/0_Home.py")

st.title("PORTFOLIO & RISK")
st.caption("RISK STATUS | OPEN POSITIONS | ASSIGNMENT PLANNER | HELD STOCK | RISK DETAIL & HISTORY | STRESS TEST")

# ── Sidebar: capital base + risk limits ───────────────────────────────────────
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
    st.caption("Defaults are the fund's policy (risk.py). Sliders override for this session only.")
    D = risk.LIMITS
    def _pct(label, key, lo, hi, help=None):
        return st.slider(label, lo, hi, int(round(D[key] * 100)), help=help) / 100
    LIM = {
        "tail_qqq20":    _pct("MAX LOSS IF QQQ −20% (% NAV)", "tail_qqq20", 5, 50,
                              help="Every name moved by its beta to QQQ, options repriced."),
        "book_beta":     st.slider("MAX BOOK BETA (× QQQ)", 0.25, 2.0, float(D["book_beta"]), 0.05,
                                   help="1.0 = the fund moves like owning QQQ outright."),
        "max_name":      _pct("MAX SINGLE NAME %", "max_name", 5, 30),
        "max_trade":     _pct("MAX SINGLE POSITION %", "max_trade", 1, 15),
        "max_sector":    _pct("MAX SECTOR %", "max_sector", 10, 60),
        "max_spec":      _pct("MAX SPECULATIVE %", "max_spec", 10, 60),
        "min_core":      _pct("MIN CORE %", "min_core", 0, 70),
        "max_stock_inv": _pct("MAX STOCK INVENTORY %", "max_stock_inv", 10, 60),
        "dd_warn":       _pct("DRAWDOWN — SLOW DOWN AT %", "dd_warn", 1, 20),
        "dd_stop":       _pct("DRAWDOWN — STOP ADDING RISK AT %", "dd_stop", 2, 30),
    }
    st.markdown("---")
    st.markdown("### HOW RISK IS MEASURED")
    st.caption(
        "BETA — each name's sensitivity to QQQ, from our own daily closes.\n\n"
        "BOOK BETA — Σ($ delta × beta) ÷ NAV. 1.5× means the fund moves like 1.5× QQQ.\n\n"
        "LOSS IF QQQ −20% — every name moved by its beta, options repriced (Black-Scholes, live IV).\n\n"
        "CONCENTRATION — cash at risk (puts = strike × 100) ÷ NAV, per the manual.\n\n"
        "DELTA — short put +d · short call −d · stock +1 · covered call −d (shares on their own row) "
        "· long put −d · long call +d.")

# ── Book + capital ────────────────────────────────────────────────────────────
trades = db.get_trades_df()
if trades.empty or (trades["STATUS"] == "OPEN").sum() == 0:
    st.info("No open trades in the Trade Log. Add trades in the Trade Log page first.")
    st.markdown("---")
    if st.button("GO TO TRADE LOG", type="primary"):
        st.switch_page("pages/5_Trade_Log.py")
    st.stop()

with st.spinner("MARKING POSITIONS..."):
    book = build_book(trades)
fn = fund_nav(trades, book)
realized_all, contributed, total_unreal = fn["realized"], fn["contributed"], fn["unreal"]

if CAP_MODE.startswith("Auto") and contributed > 0:
    TOTAL_CAPITAL = fn["nav"]
    cap_note = (f"AUTO = FUND NAV  →  contributed ${contributed:,.0f} + realized ${realized_all:,.0f} "
                f"+ unrealized ${total_unreal:,.0f} = ${TOTAL_CAPITAL:,.0f}")
else:
    TOTAL_CAPITAL = MANUAL_CAPITAL
    cap_note = (f"MANUAL = ${MANUAL_CAPITAL:,.0f}"
                + ("  (no cash flows logged yet — add them on the Performance page to use Auto)"
                   if CAP_MODE.startswith("Auto") else ""))

cs = bk.cash_summary(book, TOTAL_CAPITAL)
acct_cash, reserved_cash, available_cash = cs["acct_cash"], cs["reserved"], cs["available"]
# % deployed is measured against CASH (puts are cash-secured), not NAV.
pct_deployed = reserved_cash / acct_cash if acct_cash else 0
short_opt = book[(~book["_IS_STOCK"]) & (book["_IS_SHORT"])]
total_premium = (pd.to_numeric(short_opt["PREM RECEIVED"], errors="coerce") *
                 pd.to_numeric(short_opt["CONTRACTS"], errors="coerce") * 100).sum()

k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("TOTAL CAPITAL",     f"${TOTAL_CAPITAL:,.0f}",
          help="The base all risk caps are measured against. " + cap_note)
k2.metric("TOTAL CASH (T-BILLS)", f"${acct_cash:,.0f}",
          help="Fund value − stock held + premium cash collected. The actual cash in the account.")
k3.metric("CAPITAL DEPLOYED",  f"${reserved_cash:,.0f}", f"{pct_deployed:.1%}",
          help="Cash-secured collateral on SHORT options (cash-secured put = strike×100; spreads = "
               "max loss; covered calls = $0). EXCLUDES assigned stock (stock-secured) and LONG options "
               "— their premium is already spent, so it reduces TOTAL CASH rather than being reserved. "
               "So the tiles reconcile: TOTAL CASH − CAPITAL DEPLOYED = AVAILABLE CASH.")
k4.metric("AVAILABLE CASH",    f"${available_cash:,.0f}",
          help="Dry powder free to deploy into new cash-secured puts (total cash − collateral reserved).")
k5.metric("PREMIUM RECEIVED",  f"${total_premium:,.0f}",
          help="Σ premium × 100 × contracts on open short options (credit collected up front)")
k6.metric("UNREAL PNL (MID)",  f"${total_unreal:,.0f}",
          help="(Premium received − current mid) × 100 × contracts")
st.caption(f"CAPITAL BASE — {cap_note}  |  OPEN POSITIONS: {len(book)}")

missing = sorted(set(bk.unpriced(book)))
if missing:
    st.warning(f"NO LIVE PRICE FOR: {', '.join(missing)} — those positions are held flat at entry "
               f"(P&L, NAV and risk use the entry price) until a price comes back. For thin names, "
               f"type a MANUAL MARK in the Trade Log.")

# ── Risk status — top of the page, so a breach can't sit unseen ───────────────
closes = db.load_closes(tuple(sorted(set(trades["TICKER"].astype(str)) | {risk.BENCH})))
betas = risk.betas_from_closes(closes)
fsnaps = db.load_fund_snapshots() if db.configured() else pd.DataFrame()
npu = fn["npu"] if CAP_MODE.startswith("Auto") else None
peak = None
if npu and not fsnaps.empty and "nav_per_unit" in fsnaps.columns:
    peak = max(float(pd.to_numeric(fsnaps["nav_per_unit"], errors="coerce").max()), npu)
res = risk.evaluate(book, TOTAL_CAPITAL, betas, LIM, npu=npu, peak_npu=peak, available=available_cash)
checks, rbook, met = res["checks"], res["book"], res["metrics"]

st.markdown("### RISK STATUS")
breaches = [c for c in checks if c["status"] == "breach"]
if breaches:
    st.error(f"{len(breaches)} LIMIT(S) BREACHED — " + "  ·  ".join(
        f"{c['label']} {risk.fmt_value(c)} (limit {risk.fmt_limit(c)})" for c in breaches))
chips = "".join(
    f"<div style='flex:1 1 150px;min-width:140px;background:#111;border:1px solid #222;"
    f"border-left:3px solid {STATUS_COLOR[c['status']]};padding:6px 8px'>"
    f"<div style='font-size:0.68rem;color:#999;letter-spacing:.04em'>{c['label']}</div>"
    f"<div style='font-size:1.05rem;color:{STATUS_COLOR[c['status']]};font-weight:600'>{risk.fmt_value(c)}</div>"
    f"<div style='font-size:0.68rem;color:#777'>limit {risk.fmt_limit(c)} · {STATUS_TEXT[c['status']]}</div></div>"
    for c in checks)
st.markdown(f"<div style='display:flex;flex-wrap:wrap;gap:6px'>{chips}</div>", unsafe_allow_html=True)
st.caption("What's driving each number, and how long each limit has been breached: RISK DETAIL below.")

st.markdown("---")

# ── Open positions ────────────────────────────────────────────────────────────
st.markdown("### OPEN POSITIONS")

def color_dte(v):
    try: return f"color:{RED};font-weight:600" if int(v) < 14 else f"color:{AMBER}" if int(v) < 21 else ""
    except Exception: return ""

def color_pnl(v):
    try: return f"color:{GREEN}" if float(v) > 0 else f"color:{RED}" if float(v) < 0 else ""
    except Exception: return ""

def color_pct_profit(v):
    try:
        f = float(v)
        if f >= 0.50: return f"color:{GREEN};font-weight:700"   # at/past the GTC level
        if f >= 0.25: return "color:#00c8ff"
        if f < 0:     return f"color:{RED}"
        return ""
    except Exception: return ""

def color_action(v):
    s = str(v)
    if s.startswith("CLOSE"):  return f"color:{GREEN};font-weight:700"
    if s.startswith("TAKE"):   return "color:#00c8ff;font-weight:600"
    if s.startswith("MANAGE"): return f"color:{AMBER};font-weight:600"
    return ""

def color_earn(v):
    try: return f"color:{RED};font-weight:700" if float(v) <= 10 else f"color:{AMBER}"
    except Exception: return ""

fmt = {
    "SPOT": "${:.2f}", "DTE LEFT": "{:.0f}", "EARNINGS": "{:.0f}d", "CONTRACTS": "{:.0f}",
    "SHORT STRIKE": "${:.2f}", "BREAKEVEN": "${:.2f}", "PREM RECEIVED": "${:.2f}",
    "CURRENT MID": "${:.2f}", "TOTAL $ PREM RECEIVED": "${:,.0f}", "IV USED": "{:.1%}",
    "DELTA": "{:+.3f}", "$ DELTA": "${:,.0f}", "CASH AT RISK": "${:,.0f}", "MAX LOSS": "${:,.0f}",
    "UNREAL PNL": "${:,.0f}", "% MAX PROFIT": "{:.0%}", "YIELD LEFT": "{:.1%}",
}
# Strategy filter — the DISPLAYED table only (KPIs, risk and stress test use the full book).
_strat_opts = sorted(book["STRATEGY"].dropna().unique().tolist())
_sel_strats = st.segmented_control(
    "SHOW", _strat_opts, selection_mode="multi", default=_strat_opts, key="pos_filter",
    help="Filter the table to these position types. Deselect everything to show all again. "
         "The metrics and risk checks always use the full book.")
_active = _sel_strats if _sel_strats else _strat_opts
fbook = book[book["STRATEGY"].isin(_active)].reset_index(drop=True)
if len(fbook) < len(book):
    st.caption(f"Showing {len(fbook)} of {len(book)} open positions.")
disp_book = fbook[[c for c in fbook.columns if not c.startswith("_") and c != "ID"]]
styled_book = (disp_book.style
    .map(color_dte,        subset=["DTE LEFT"])
    .map(color_earn,       subset=["EARNINGS"])
    .map(color_pnl,        subset=["UNREAL PNL"])
    .map(color_pnl,        subset=["DELTA"])
    .map(color_pct_profit, subset=["% MAX PROFIT"])
    .map(color_action,     subset=["ACTION"])
    .format(fmt, na_rep="—"))

_book_event = st.dataframe(styled_book, use_container_width=True, hide_index=True,
             column_config={"TICKER": st.column_config.Column(pinned=True)},
             on_select="rerun", selection_mode="multi-row", key="book_sel")
st.caption("TIP: tick rows above, then use CLOSE SELECTED → TICKET below to build the closing order.  |  "
           "EARNINGS = days to the next report when it lands before the option expires (stock: within 14 days); "
           "red = within 10 days.")
st.caption("PROFIT-TAKE PROCEDURE (MANUAL §5.1): GTC BUY-TO-CLOSE AT 50% ON ENTRY → CLOSE 1/2 AT 50%, 1/4 AT 75%, REST BY 90% OR MANAGE-BY DATE (1M @ 21 DTE, 3M @ 45 DTE). "
           "YIELD LEFT = ANNUALIZED YIELD OF PREMIUM STILL ON THE TABLE — IF < 15% AFTER THE 50% TIER, CLOSE AND REDEPLOY.")

# ── Close selected → Order Ticket ─────────────────────────────────────────────
# Tick positions in the OPEN POSITIONS table above, then add their CLOSING legs
# (buy-to-close for shorts, sell-to-close for longs) to the Order Ticket at the
# current mark. Stock rows are ignored (no option ticket line). Builds the order
# only — close the trade in the Trade Log after the fill.
st.markdown("### CLOSE SELECTED → TICKET")
try:
    _sel_rows = list(_book_event.selection["rows"])
except Exception:
    _sel_rows = []
_sel     = fbook.iloc[_sel_rows] if _sel_rows else fbook.iloc[0:0]
_sel_opt = _sel[~_sel["_IS_STOCK"]] if not _sel.empty else _sel
_n       = len(_sel_opt)

b_add, b_view, _ = st.columns([3, 3, 4])
if b_add.button(f"＋ ADD {_n} TO TICKET (CLOSE)", type="primary", use_container_width=True, disabled=(_n == 0)):
    _added, _skip = 0, []
    for _, r in _sel_opt.iterrows():
        m = r["CURRENT MID"]
        if pd.isna(m):
            _skip.append(str(r["TICKER"])); continue
        act = "buy to close" if bool(r["_IS_SHORT"]) else "sell to close"
        opt = "put" if bool(r["_IS_PUT"]) else "call"
        stk = float(r["SHORT STRIKE"]) if pd.notna(r["SHORT STRIKE"]) else 0.0
        ticket.add_to_ticket(act, str(r["TICKER"]), str(r["EXPIRY"]), opt, stk, float(m), int(r["CONTRACTS"]))
        _added += 1
    if _added:
        st.success(f"Added {_added} close order(s) to the ticket.")
    if _skip:
        st.warning(f"Skipped (no live mark): {', '.join(_skip)} — add these in the ticket with a manual price.")
if b_view.button(f"→ OPEN ORDER TICKET ({len(ticket.get_ticket())})", use_container_width=True):
    st.switch_page("pages/8_Order_Ticket.py")
_stk_ignored = len(_sel) - _n
st.caption("BUY-TO-CLOSE (shorts) / SELL-TO-CLOSE (longs) at the current mark. Review & send on the ORDER TICKET page. "
           "Closing here builds the order only — close the trade in the Trade Log after the fill."
           + (f"  ({_stk_ignored} stock row(s) ignored.)" if _stk_ignored else ""))

# ── Assignment planner — short puts at/near the money close to expiry ─────────
near = book[book["_IS_PUT"] & book["_IS_SHORT"] & ~book["_IS_SPREAD"] & ~book["_IS_STOCK"]].copy()
near["DTE LEFT"] = pd.to_numeric(near["DTE LEFT"], errors="coerce")
near = near[(near["DTE LEFT"] <= 10) & near["SPOT"].notna()
            & (near["SPOT"] < pd.to_numeric(near["SHORT STRIKE"], errors="coerce") * 1.02)]
if not near.empty:
    st.markdown("### ASSIGNMENT PLANNER — PUTS LIKELY TO BE ASSIGNED")
    stock_now = next((c["value"] for c in checks if c["key"] == "max_stock_inv"), 0.0)
    ap = []
    for _, r in near.iterrows():
        sh = int(r["CONTRACTS"]) * 100
        k, s, be = float(r["SHORT STRIKE"]), float(r["SPOT"]), float(r["BREAKEVEN"])
        ap.append({"TICKER": r["TICKER"], "STRIKE": k, "EXPIRY": r["EXPIRY"], "DTE": int(r["DTE LEFT"]),
                   "SPOT": s, "VS STRIKE": s / k - 1, "SHARES": sh, "CASH USED": k * sh,
                   "NET BASIS": be, "PAPER P&L AT SPOT": (s - be) * sh, "% OF NAV": s * sh / TOTAL_CAPITAL})
    ap = pd.DataFrame(ap)
    stock_after = stock_now + ap["% OF NAV"].sum()
    st.dataframe(ap.style.map(color_pnl, subset=["PAPER P&L AT SPOT", "VS STRIKE"])
                   .format({"STRIKE": "${:.2f}", "SPOT": "${:.2f}", "VS STRIKE": "{:+.1%}", "SHARES": "{:,.0f}",
                            "CASH USED": "${:,.0f}", "NET BASIS": "${:.2f}", "PAPER P&L AT SPOT": "${:,.0f}",
                            "% OF NAV": "{:.1%}"}),
                 use_container_width=True, hide_index=True)
    st.caption(f"Puts expiring within 10 days that are in the money or within 2% of it. Their cash is already "
               f"reserved (cash-secured), so assignment turns reserved cash into stock: AVAILABLE CASH doesn't drop. "
               f"What changes is STOCK INVENTORY: {stock_now:.1%} → {stock_after:.1%} of NAV "
               f"(limit {LIM['max_stock_inv']:.0%}). NET BASIS = strike − premium. "
               f"Per line: take the shares, roll down/out for a credit (ROLL FINDER), or buy to close.")

# ── Held stock — covered-call capacity + wheel breakeven ─────────────────────
# Multiple Long Stock lots per name are possible (each assignment adds a row).
_stock = book[book["_IS_STOCK"]]
if not _stock.empty:
    st.markdown("### HELD STOCK — COVERED CALLS & WHEEL BREAKEVEN")
    _cc = book[book["_IS_CC"]]
    realized_by = pd.to_numeric(trades["REALIZED PNL"], errors="coerce").fillna(0).groupby(trades["TICKER"]).sum()
    hs_rows = []
    for tkr, grp in _stock.groupby("TICKER"):
        sh_qty = pd.to_numeric(grp["CONTRACTS"], errors="coerce").fillna(0)
        shares = int(sh_qty.sum())
        cost = float((pd.to_numeric(grp["PREM RECEIVED"], errors="coerce") * sh_qty).sum())
        avg_cost = cost / shares if shares else float("nan")
        spot_s = pd.to_numeric(grp["SPOT"], errors="coerce").dropna()
        spot_v = float(spot_s.iloc[0]) if len(spot_s) else float("nan")
        unreal = (spot_v - avg_cost) * shares if not (np.isnan(spot_v) or np.isnan(avg_cost)) else float("nan")

        cgrp = _cc[_cc["TICKER"] == tkr]
        call_cts = int(pd.to_numeric(cgrp["CONTRACTS"], errors="coerce").fillna(0).sum()) if not cgrp.empty else 0
        call_desc = " | ".join(f"{int(r['CONTRACTS'])}×${r['SHORT STRIKE']:g} {str(r['EXPIRY'])[5:] or ''}".strip()
                               for _, r in cgrp.iterrows()) if not cgrp.empty else "—"
        cc_credit = float((cgrp["PREM RECEIVED"] * cgrp["CONTRACTS"] * 100).sum()) if not cgrp.empty else 0.0
        # Wheel breakeven: share cost less every premium the name has paid us
        # (closed puts / calls, assignment premium, sold lots) and the open calls' credit.
        wheel_be = (cost - float(realized_by.get(tkr, 0.0)) - cc_credit) / shares if shares else float("nan")
        covered_sh = call_cts * 100
        free_sh = shares - covered_sh
        hs_rows.append({
            "TICKER": tkr, "SHARES": shares, "AVG COST": round(avg_cost, 2) if not np.isnan(avg_cost) else None,
            "WHEEL B/E": round(wheel_be, 2) if not np.isnan(wheel_be) else None,
            "SPOT": round(spot_v, 2) if not np.isnan(spot_v) else None,
            "VS B/E": (spot_v / wheel_be - 1) if (wheel_be and not np.isnan(spot_v) and wheel_be > 0) else None,
            "UNREAL $": round(unreal, 0) if not np.isnan(unreal) else None,
            "CALL": call_desc, "COVERED SH": covered_sh, "FREE SH": free_sh, "CALLS AVAIL": int(free_sh // 100),
        })
    hs = pd.DataFrame(hs_rows)

    def _c_avail(v):
        try:
            f = float(v)
            if f >= 1: return f"color:{GREEN};font-weight:700"   # free shares -> can write more calls
            if f < 0:  return f"color:{RED};font-weight:700"     # over-covered / naked
            return "color:#888888"
        except Exception:
            return ""

    st.dataframe(
        hs.style
          .map(color_pnl, subset=["UNREAL $", "VS B/E"])
          .map(_c_avail, subset=["CALLS AVAIL"])
          .format({"AVG COST": "${:.2f}", "WHEEL B/E": "${:.2f}", "SPOT": "${:.2f}", "VS B/E": "{:+.1%}",
                   "UNREAL $": "${:,.0f}", "SHARES": "{:,.0f}", "COVERED SH": "{:,.0f}", "FREE SH": "{:,.0f}"},
                  na_rep="—"),
        use_container_width=True, hide_index=True,
        column_config={"TICKER": st.column_config.Column(pinned=True)})
    _avail = int(hs["CALLS AVAIL"].clip(lower=0).sum())
    st.caption(f"WHEEL B/E = share cost − all premium collected on the name (closed puts & calls, sold lots) − open "
               f"call credit, per share: the price at which the whole campaign is flat. CALLS AVAIL = free shares ÷ 100 "
               f"({_avail} across the book) — green = free shares to write; red = over-covered (naked).")

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

# ── Risk detail ───────────────────────────────────────────────────────────────
st.markdown("### RISK DETAIL")
st.dataframe(
    pd.DataFrame([{"STATUS": STATUS_TEXT[c["status"]], "MEASURE": c["label"], "NOW": risk.fmt_value(c),
                   "LIMIT": risk.fmt_limit(c), "WHAT'S DRIVING IT": c["detail"]} for c in checks])
      .style.map(lambda v: f"color:{STATUS_COLOR[{'OK': 'ok', 'WATCH': 'warn', 'BREACH': 'breach'}[v]]};"
                           f"font-weight:700", subset=["STATUS"]),
    use_container_width=True, hide_index=True)

tail_by = met.get("tail20_by_name", {})
by_name = rbook.groupby("TICKER").agg(
    SECTOR=("SECTOR", "first"), BUCKET=("BUCKET", "first"), CASH_AT_RISK=("CASH AT RISK", "sum"),
    BETA=("BETA", "first"), BETA_EST=("BETA EST", "first"), BETA_DELTA=("BETA $ DELTA", "sum"),
).reset_index()
by_name["% OF NAV"] = by_name["CASH_AT_RISK"] / TOTAL_CAPITAL
by_name["LOSS IF QQQ −20%"] = by_name["TICKER"].map(tail_by).fillna(0)
tot_tail = by_name["LOSS IF QQQ −20%"].sum()
by_name["SHARE OF TAIL"] = by_name["LOSS IF QQQ −20%"] / tot_tail if tot_tail else 0
by_name["BETA"] = [f"{b:.2f}{'*' if e else ''}" for b, e in zip(by_name["BETA"], by_name["BETA_EST"])]
by_name = by_name.drop(columns="BETA_EST").sort_values("LOSS IF QQQ −20%")
over_name = lambda v: f"color:{RED};font-weight:600" if v > LIM["max_name"] else ""
st.markdown("#### EXPOSURE BY NAME")
st.dataframe(by_name.rename(columns={"CASH_AT_RISK": "CASH AT RISK", "BETA_DELTA": "BETA-WEIGHTED $ DELTA"})
             .style.map(over_name, subset=["% OF NAV"]).map(color_pnl, subset=["LOSS IF QQQ −20%"])
             .format({"CASH AT RISK": "${:,.0f}", "% OF NAV": "{:.1%}", "BETA-WEIGHTED $ DELTA": "${:,.0f}",
                      "LOSS IF QQQ −20%": "${:,.0f}", "SHARE OF TAIL": "{:.0%}"}),
             use_container_width=True, hide_index=True,
             column_config={"TICKER": st.column_config.Column(pinned=True)})
if met.get("beta_estimated"):
    st.caption("* BETA ESTIMATED from the name's bucket (Core 1.2 / Growth 1.8 / Speculative 2.5) — not enough "
               "daily closes stored yet: " + ", ".join(met["beta_estimated"]) + ". Fills in as the snapshot job runs.")

sc1, sc2 = st.columns(2)
with sc1:
    st.markdown("#### BY SECTOR")
    s_df = met["by_sector"].rename("% OF NAV").reset_index().rename(columns={"index": "SECTOR"})
    st.dataframe(s_df.style.map(lambda v: f"color:{RED};font-weight:600" if v > LIM["max_sector"] else "",
                                subset=["% OF NAV"]).format({"% OF NAV": "{:.1%}"}),
                 use_container_width=True, hide_index=True)
with sc2:
    st.markdown("#### BY BUCKET")
    b_df = met["by_bucket"].rename("% OF NAV").reset_index().rename(columns={"index": "BUCKET"})
    b_df["TARGET"] = b_df["BUCKET"].map({"Core": f"≥ {LIM['min_core']:.0%}",
                                         "Speculative": f"≤ {LIM['max_spec']:.0%}"}).fillna("residual")
    st.dataframe(b_df.style.format({"% OF NAV": "{:.1%}"}), use_container_width=True, hide_index=True)

# ── Breach history — was the book over a limit, and for how long? ─────────────
st.markdown("#### BREACH HISTORY")

@st.cache_data(ttl=3600, show_spinner=False)
def _history(trades_, closes_, fsnaps_, betas_, smap_, lim_):
    return risk.history(trades_, closes_, fsnaps_, betas_, smap_, lim_)

if not fsnaps.empty and not closes.empty:
    with st.spinner("REPLAYING THE BOOK DAY BY DAY..."):
        hist = _history(trades, closes, fsnaps, betas, sector_map(), LIM)
    if hist.empty:
        st.info("Not enough history yet.")
    else:
        st.dataframe(risk.breach_summary(hist), use_container_width=True, hide_index=True)
        rank = hist.assign(r=hist["status"].map(risk.STATUS_RANK)).pivot_table(
            index="label", columns="date", values="r", aggfunc="max")
        fig_h = go.Figure(go.Heatmap(
            z=rank.values, x=[str(d) for d in rank.columns], y=rank.index.tolist(), zmin=0, zmax=2,
            colorscale=[[0, "#1d6b3e"], [0.33, "#1d6b3e"], [0.34, AMBER], [0.66, AMBER], [0.67, RED], [1, RED]],
            showscale=False, xgap=1, ygap=1,
            hovertemplate="%{y}<br>%{x}<extra></extra>"))
        fig_h.update_layout(**LAYOUT, height=60 + 26 * len(rank.index), margin=dict(l=10, r=10, t=10, b=30))
        st.plotly_chart(fig_h, use_container_width=True)
        st.caption("Each day re-runs today's checks on the positions open that day (from the Trade Log), that day's "
                   "closes and that day's NAV. Concentration caps and drawdown are exact; book beta and the QQQ tail "
                   "are estimates (options priced with Black-Scholes at realized vol — no historical option quotes). "
                   "Green = OK, amber = watch, red = breach.")
else:
    st.info("Breach history needs the daily snapshots (NAV history + daily closes) from the Supabase DB.")

st.markdown("---")

# ── Stress test (manual §9 on the live book) ─────────────────────────────────
st.markdown("### STRESS TEST")
sm0, sm1, sm2 = st.columns([3, 3, 4])
with sm0:
    basis = st.segmented_control(
        "SHOCK", ["QQQ MOVE (BETA-SCALED)", "SAME % EVERY NAME"], default="QQQ MOVE (BETA-SCALED)",
        selection_mode="single",
        help="QQQ MOVE: each name moves by its beta × the QQQ move — how the book really behaves in a "
             "market selloff. SAME %: every name moves the same % (the old basket shock).")
    basis = basis or "QQQ MOVE (BETA-SCALED)"
with sm1:
    stress_mode = st.segmented_control(
        "VALUATION MODE", ["INSTANT SHOCK", "HOLD TO EXPIRY"], default="INSTANT SHOCK", selection_mode="single",
        help="INSTANT SHOCK: every position repriced with Black-Scholes at live IV, on its remaining DTE minus "
             "the TIME HORIZON (expired legs settle to intrinsic). HOLD TO EXPIRY: each option at intrinsic on "
             "ITS OWN expiry (final P&L vs entry — matches the payoff diagrams; the horizon is ignored).")
    stress_mode = stress_mode or "INSTANT SHOCK"
with sm2:
    weeks_fwd = st.slider("TIME HORIZON — WEEKS FORWARD", 0, 12, 0, disabled=(stress_mode == "HOLD TO EXPIRY"),
        help="Roll the clock forward: short premium is harvested as those legs decay and expire, while any "
             "long options bleed theta. Applies to INSTANT SHOCK.")

beta_scaled = basis.startswith("QQQ")
st.caption("Stock legs: Long Stock P&L vs entry; covered calls assume 100 sh/contract. IV held constant (a real "
           "crash lifts IV, worsening short-option marks). T-bill interest not modeled.")

def total_pnl_at(move):
    """Total fund P&L = banked realized + open positions at the shocked spot —
    the same basis as TOTAL CAPITAL, so the drawdown lines compare like with like."""
    shock = risk.qqq_shock(rbook, move) if beta_scaled else move
    return realized_all + bk.scenario_pnl(rbook, shock, stress_mode, _wk)

_wk = weeks_fwd if stress_mode == "INSTANT SHOCK" else 0
shocks = np.arange(-0.40, 0.405, 0.01) if beta_scaled else np.arange(-0.60, 0.605, 0.01)
curve = [total_pnl_at(s) for s in shocks]
_lbl = "QQQ MOVE %" if beta_scaled else "BASKET SHOCK %"
sel_shock = st.slider(_lbl, int(shocks[0] * 100), int(round(shocks[-1] * 100)), 0, 1) / 100
pnl_at_sel = total_pnl_at(sel_shock)

_hz = f"  ·  +{_wk}W" if _wk else ""
s1, s2, s3 = st.columns(3)
s1.metric(f"P&L AT {sel_shock:+.0%}{_hz}", f"${pnl_at_sel:,.0f}",
          help="Total fund P&L = realized (banked) + unrealized at this shock.")
s2.metric("VS TOTAL CAPITAL", f"{pnl_at_sel/TOTAL_CAPITAL:+.1%}")
s3.metric("DRAWDOWN TOLERANCE (20-30%)", "WITHIN" if pnl_at_sel / TOTAL_CAPITAL > -0.30 else "BREACHED")

fig_st = go.Figure()
fig_st.add_scatter(x=shocks * 100, y=curve, mode="lines", name="P&L", line=dict(color="#00c8ff", width=2))
fig_st.add_hline(y=0, line_color="#444444", line_width=1)
fig_st.add_hline(y=-0.20 * TOTAL_CAPITAL, line_color=AMBER, line_dash="dot",
                 annotation_text="-20% CAPITAL", annotation_font_color=AMBER)
fig_st.add_hline(y=-0.30 * TOTAL_CAPITAL, line_color=RED, line_dash="dot",
                 annotation_text="-30% CAPITAL", annotation_font_color=RED)
fig_st.add_vline(x=sel_shock * 100, line_color=GREEN, line_dash="dash")
fig_st.update_layout(**LAYOUT, margin=dict(l=40, r=20, t=20, b=40), height=380, showlegend=False,
    xaxis=dict(title=_lbl, gridcolor="#1e1e1e", ticksuffix="%"),
    yaxis=dict(title=f"P&L ({stress_mode}{', +'+str(_wk)+'w' if _wk else ''})", gridcolor="#1e1e1e", tickprefix="$"))
st.plotly_chart(fig_st, use_container_width=True)

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
                           name="REALIZED + UNREALIZED", line=dict(color="#00c8ff", width=2))
        fig_eq.update_layout(**LAYOUT, margin=dict(l=40, r=20, t=20, b=40), height=320, showlegend=False,
                             xaxis=dict(gridcolor="#1e1e1e"), yaxis=dict(gridcolor="#1e1e1e", tickprefix="$"))
        st.plotly_chart(fig_eq, use_container_width=True)
        st.caption("ONE POINT PER TRADING DAY — WRITTEN AUTOMATICALLY AFTER US CLOSE BY THE SNAPSHOT JOB")

st.markdown("---")
st.caption("IV FROM LIVE OPTION CHAIN (1-MIN CACHE) | DELTA USES BLACK-SCHOLES EUROPEAN APPROX | NOT EXECUTION READY")
