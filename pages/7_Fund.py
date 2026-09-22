"""
Performance — single-beneficiary unitized accounting (time-weighted return).

There is exactly ONE owner. Cash flows are deposits (amount > 0) or withdrawals
(amount < 0). Each flow issues/redeems units at the NAV/unit of its own date, so
NAV/unit is unaffected by the size or timing of flows — it moves ONLY with
performance. That means **NAV/unit indexed to 100 IS the time-weighted return.**

  net_contributed = Σ amounts            (deposits +, withdrawals −)
  total_units     = Σ units_delta        (deposits +, withdrawals −)
  NAV             = net_contributed + realized P&L + unrealized P&L
  NAV/unit        = NAV / total_units
  TWR since incep = NAV/unit − 100       (seed = 100)

Daily history is written by scripts/daily_snapshot.py.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import datetime
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import bbg_style
import db
from shared import compute_book_pnl, fetch_hist

bbg_style.inject()


c_nav1, c_nav2, _ = st.columns([1, 2, 7])
with c_nav1:
    if st.button("HOME"): st.switch_page("pages/0_Home.py")
with c_nav2:
    if st.button("↻ REFRESH DATA", help="Pull the latest snapshots from Supabase (after a manual run)"):
        db.load_fund_snapshots.clear()
        db.load_portfolio_snapshots.clear()
        st.rerun()

st.title("PERFORMANCE")
st.caption("SINGLE-OWNER UNITIZED FUND | NAV/UNIT INDEXED TO 100 IS THE TIME-WEIGHTED RETURN")

SEED_NAV_PER_UNIT = 100.0   # first deposit prices units at $100 each

# ── Current fund value ────────────────────────────────────────────────────────
trades = db.get_trades_df()
with st.spinner("MARKING BOOK..."):
    realized, unreal = compute_book_pnl(trades)

flows = db.load_cash_flows()
net_contributed = float(pd.to_numeric(flows["amount"], errors="coerce").sum()) if not flows.empty else 0.0
total_units     = float(pd.to_numeric(flows["units_delta"], errors="coerce").sum()) if not flows.empty else 0.0

nav = net_contributed + realized + unreal
nav_per_unit = (nav / total_units) if total_units > 0 else SEED_NAV_PER_UNIT
total_pnl = realized + unreal
twr = nav_per_unit - SEED_NAV_PER_UNIT     # NAV/unit − 100 = time-weighted return (points = %)

# ── Headline: time-weighted return ────────────────────────────────────────────
h1, h2, h3, h4 = st.columns(4)
h1.metric("TWR SINCE INCEPTION", f"{twr:+.2f}%",
          help="NAV/unit − 100. Pure performance — unaffected by when/how much cash was added or withdrawn.")
h2.metric("CURRENT NAV",   f"${nav:,.0f}", help="Net capital in + realized + unrealized")
h3.metric("NET CAPITAL IN", f"${net_contributed:,.0f}", help="Σ cash flows (deposits − withdrawals)")
h4.metric("TOTAL P&L ($)", f"${total_pnl:,.0f}",
          f"{(total_pnl/net_contributed):+.1%}" if net_contributed > 0 else None,
          help="Realized + unrealized, in dollars (the % is on net capital in)")

k1, k2, k3, k4 = st.columns(4)
k1.metric("NAV / UNIT",     f"${nav_per_unit:,.2f}",
          f"{(nav_per_unit/SEED_NAV_PER_UNIT-1):+.1%}" if total_units > 0 else None)
k2.metric("TOTAL UNITS",    f"{total_units:,.2f}")
k3.metric("REALIZED P&L",   f"${realized:,.0f}")
k4.metric("UNREALIZED P&L", f"${unreal:,.0f}")

st.markdown("---")

# ── Log a cash flow (deposit or withdrawal) ───────────────────────────────────
st.markdown("### LOG A CASH FLOW")
st.caption("Positive AMOUNT = deposit (issues units). Negative AMOUNT = withdrawal (redeems units).")

cc1, cc2 = st.columns(2)
c_amt  = cc1.number_input("AMOUNT ($) — negative to withdraw", value=0.0, step=1000.0,
                          format="%.2f", key="c_amt")
c_date = cc2.date_input("DATE", datetime.date.today(), key="c_date")

# Units MUST be priced at the NAV/unit of the FLOW DATE, not today's — otherwise a
# backdated flow issues/redeems units at the wrong price. Use that date's snapshot
# (or the latest one on/before it); fall back to live NAV only when there's no
# snapshot yet (e.g. a flow dated today before the job has run).
def _nav_on(d):
    try:
        snaps = db.load_fund_snapshots()
        if snaps.empty or "snap_date" not in snaps:
            return None, None
        s = snaps.copy()
        s["nav_per_unit"] = pd.to_numeric(s["nav_per_unit"], errors="coerce")
        s = s[(s["snap_date"].astype(str) <= d.isoformat()) & s["nav_per_unit"].notna()]
        if s.empty:
            return None, None
        s = s.sort_values("snap_date")
        return float(s["nav_per_unit"].iloc[-1]), str(s["snap_date"].iloc[-1])
    except Exception:
        return None, None

nav_hist, nav_src = _nav_on(c_date)
use_nav = nav_hist if nav_hist and nav_hist > 0 else nav_per_unit
units_delta = (c_amt / use_nav) if use_nav > 0 else 0.0

if c_amt != 0 and use_nav > 0:
    verb = "Issues" if c_amt > 0 else "Redeems"
    src_note = (f"snapshot {nav_src}" if nav_hist and nav_src == c_date.isoformat()
                else f"latest snapshot on/before {c_date.isoformat()}: {nav_src}" if nav_hist
                else f"CURRENT NAV/unit (no snapshot on/before {c_date.isoformat()})")
    st.caption(f"At NAV/unit **${use_nav:,.4f}** ({src_note}) → "
               f"**{verb} {abs(units_delta):,.2f} units**.")

# Guard: a withdrawal can't redeem more units than exist.
over_withdraw = c_amt < 0 and abs(units_delta) > total_units + 1e-9
if over_withdraw:
    st.error(f"Withdrawal too large — it would redeem {abs(units_delta):,.2f} units but only "
             f"{total_units:,.2f} exist (≈ ${total_units*use_nav:,.0f} available at this NAV/unit).")

if st.button("LOG CASH FLOW", type="primary", disabled=(c_amt == 0 or over_withdraw)):
    db.add_cash_flow(c_date.isoformat(), c_amt, units_delta, use_nav)
    verb = "Deposited" if c_amt > 0 else "Withdrew"
    st.success(f"{verb} ${abs(c_amt):,.2f} → {units_delta:+,.2f} units @ ${use_nav:,.4f}/unit.")
    st.rerun()

# ── All cash flows ────────────────────────────────────────────────────────────
if flows.empty:
    st.info("No cash flows yet. Log the initial deposit above to seed the fund at $100/unit.")
else:
    with st.expander("ALL CASH FLOWS"):
        show = flows.copy()
        show["TYPE"] = np.where(pd.to_numeric(show["amount"], errors="coerce") >= 0,
                                "DEPOSIT", "WITHDRAWAL")
        show = show[["flow_date", "TYPE", "amount", "units_delta", "nav_per_unit"]]
        st.dataframe(
            show.sort_values("flow_date").style.format({
                "amount": "${:,.2f}", "units_delta": "{:+,.2f}", "nav_per_unit": "${:,.4f}",
            }), use_container_width=True, hide_index=True)

# ── History (daily snapshots) ─────────────────────────────────────────────────
if db.configured():
    fs = db.load_fund_snapshots()
    if not fs.empty and "snap_date" in fs.columns:
        fs = fs.sort_values("snap_date").reset_index(drop=True)
        fs["nav"]          = pd.to_numeric(fs["nav"], errors="coerce")
        fs["nav_per_unit"] = pd.to_numeric(fs["nav_per_unit"], errors="coerce")

        # ── Performance tear sheet (fund-only, from NAV/unit) ────────────────
        st.markdown("---")
        st.markdown("### PERFORMANCE TEAR SHEET")
        RF = 0.045                                    # risk-free (T-bill) for Sharpe/Sortino
        npu = fs["nav_per_unit"].dropna().reset_index(drop=True)
        if len(npu) >= 2:
            rets = npu.pct_change().dropna()
            try:
                d0 = datetime.date.fromisoformat(str(fs["snap_date"].iloc[0]))
                d1 = datetime.date.fromisoformat(str(fs["snap_date"].iloc[-1]))
                cal_days = max((d1 - d0).days, 1)
            except Exception:
                cal_days = max(len(npu) - 1, 1)

            total_ret = npu.iloc[-1] / npu.iloc[0] - 1
            cagr      = (npu.iloc[-1] / npu.iloc[0]) ** (365.0 / cal_days) - 1
            ann_vol   = rets.std(ddof=1) * np.sqrt(252) if len(rets) > 1 else np.nan
            excess    = rets - RF / 252.0
            sharpe    = (excess.mean() / rets.std(ddof=1) * np.sqrt(252)
                         if len(rets) > 1 and rets.std(ddof=1) > 0 else np.nan)
            dvol      = np.sqrt((rets.clip(upper=0) ** 2).mean())        # downside deviation
            sortino   = (excess.mean() / dvol * np.sqrt(252)) if dvol > 0 else np.nan
            dd        = npu / npu.cummax() - 1
            max_dd    = float(dd.min())
            calmar    = (cagr / abs(max_dd)) if max_dd < 0 else np.nan
            pct_pos   = float((rets > 0).mean())

            def _f(x, pct=False, sfx=""):
                if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
                    return "—"
                return f"{x:.1%}" if pct else f"{x:.2f}{sfx}"

            r1 = st.columns(4)
            r1[0].metric("TOTAL RETURN", _f(total_ret, pct=True), help="NAV/unit since first snapshot")
            r1[1].metric("ANN. RETURN (CAGR)", _f(cagr, pct=True), help="Calendar-annualized; noisy on short history")
            r1[2].metric("ANN. VOLATILITY", _f(ann_vol, pct=True))
            r1[3].metric("MAX DRAWDOWN", _f(max_dd, pct=True), help="Worst peak-to-trough on NAV/unit")
            r2 = st.columns(4)
            r2[0].metric("SHARPE", _f(sharpe), help=f"(ann. return − {RF:.1%} rf) / ann. vol")
            r2[1].metric("SORTINO", _f(sortino), help="Uses downside deviation only — fairer to premium-selling")
            r2[2].metric("CALMAR", _f(calmar), help="CAGR / |max drawdown|")
            r2[3].metric("% POSITIVE DAYS", _f(pct_pos, pct=True))

            # Closed-trade stats (meaningful even with short history)
            cl = trades[trades["STATUS"].isin(
                ["CLOSED","EXPIRED WORTHLESS (MAX PROFIT)","CLOSED EARLY",
                 "ASSIGNED / EXERCISED","ROLLED","STOP LOSS HIT"])].copy() if not trades.empty else pd.DataFrame()
            rp = pd.to_numeric(cl["REALIZED PNL"], errors="coerce").dropna() if not cl.empty else pd.Series(dtype=float)
            if len(rp):
                wins, losses = rp[rp > 0], rp[rp < 0]
                pf = (wins.sum() / abs(losses.sum())) if losses.sum() != 0 else np.nan
                t = st.columns(4)
                t[0].metric("WIN RATE", f"{len(wins)/len(rp):.0%}", help=f"{len(rp)} closed trades")
                t[1].metric("AVG WIN", f"${wins.mean():,.0f}" if len(wins) else "—")
                t[2].metric("AVG LOSS", f"${losses.mean():,.0f}" if len(losses) else "—")
                t[3].metric("PROFIT FACTOR", _f(pf), help="Gross wins / gross losses (>1 = profitable)")

            # Track-record honesty banner (auto-lifts as history matures)
            if cal_days < 540:
                st.warning(f"⚠ PRELIMINARY — {cal_days} calendar days / {len(npu)} snapshots. Ratios "
                           f"annualize short history and are NOT yet statistically meaningful (need "
                           f"~18–24 months). Note: Sharpe flatters premium-selling — always read it "
                           f"beside MAX DRAWDOWN. Not an audited track record.")
        else:
            st.info("Performance metrics appear once ≥2 daily snapshots exist.")

        st.markdown("---")
        st.markdown("### FUND VALUE ($) — HISTORY")

        # Single clean NAV line with cash-flow markers on their ACTUAL dates:
        # deposits point UP (green), withdrawals point DOWN (red). Markers sit on
        # the NAV line at each flow date, so the picture is value + when cash moved.
        fig = go.Figure()
        fig.add_scatter(x=[pd.Timestamp(d) for d in fs["snap_date"]], y=fs["nav"],
                        name="FUND VALUE", mode="lines+markers",
                        line=dict(color="#00c8ff", width=2))

        if not flows.empty and "flow_date" in flows.columns:
            f2 = flows.copy()
            f2["amount"] = pd.to_numeric(f2["amount"], errors="coerce")
            cby = f2.groupby("flow_date")["amount"].sum().sort_index()
            nav_by_date = {str(d): v for d, v in zip(fs["snap_date"], fs["nav"])}
            latest_nav = float(fs["nav"].iloc[-1]) if not fs.empty else 0.0

            def _nav_at(dstr):
                # place marker on the NAV line: exact snapshot else latest on/before
                if dstr in nav_by_date and pd.notna(nav_by_date[dstr]):
                    return nav_by_date[dstr]
                prior = [nav_by_date[k] for k in sorted(nav_by_date) if k <= dstr and pd.notna(nav_by_date[k])]
                return prior[-1] if prior else latest_nav

            for sign, name, sym, col in [(1, "DEPOSIT", "triangle-up", "#00e676"),
                                         (-1, "WITHDRAWAL", "triangle-down", "#ff4444")]:
                sel = cby[(cby > 0) if sign > 0 else (cby < 0)]
                if len(sel):
                    xs = [pd.Timestamp(d) for d in sel.index]
                    ys = [_nav_at(str(d)) for d in sel.index]
                    fig.add_scatter(x=xs, y=ys, name=name, mode="markers+text",
                                    marker=dict(symbol=sym, size=13, color=col),
                                    text=[f"{v:+,.0f}" for v in sel.values],
                                    textposition="top center" if sign > 0 else "bottom center",
                                    textfont=dict(color=col, size=10),
                                    hovertemplate=name + " %{x|%b %d}: $%{text}<extra></extra>")

        fig.update_layout(
            paper_bgcolor="#0a0a0a", plot_bgcolor="#0d0d0d",
            font=dict(family="IBM Plex Mono", color="#cccccc", size=11),
            legend=dict(orientation="h", y=1.14),
            margin=dict(l=40, r=20, t=40, b=40), height=380,
            xaxis=dict(gridcolor="#1e1e1e", type="date", tickformat="%b %d"),
            yaxis=dict(gridcolor="#1e1e1e", tickprefix="$",
                       title=dict(text="NAV", font=dict(color="#00c8ff")),
                       tickfont=dict(color="#00c8ff")))
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Blue line = total fund value (NAV). Green ▲ = deposits, red ▼ = withdrawals on "
                   "their dates. Performance itself is the NAV/unit chart below (flows don't move it).")

        st.markdown("### NAV PER UNIT — HISTORY (= TIME-WEIGHTED RETURN)")
        st.caption("Per-unit value is unaffected by deposits or withdrawals (that's the point of unit "
                   "accounting) — this line is pure performance. Indexed to 100 at inception.")
        fig2 = go.Figure()
        fig2.add_scatter(x=fs["snap_date"], y=fs["nav_per_unit"],
                         mode="lines+markers", line=dict(color="#00e676", width=2))
        fig2.add_hline(y=SEED_NAV_PER_UNIT, line_color="#444444", line_dash="dot")
        fig2.update_layout(
            paper_bgcolor="#0a0a0a", plot_bgcolor="#0d0d0d",
            font=dict(family="IBM Plex Mono", color="#cccccc", size=11),
            margin=dict(l=40, r=20, t=20, b=40), height=320, showlegend=False,
            xaxis=dict(gridcolor="#1e1e1e", type="category"),
            yaxis=dict(gridcolor="#1e1e1e", tickprefix="$"))
        st.plotly_chart(fig2, use_container_width=True)

        # ── Fund vs Nasdaq benchmark (indexed) ───────────────────────────────
        # Prefer the QQQ close captured in each snapshot by the daily job (it
        # runs on GitHub Actions, where yfinance is reliable). Fall back to a
        # live fetch, then to a clear message — never silently hide the chart.
        bench = fs[["snap_date", "nav_per_unit"]].copy()
        if "qqq_close" in fs.columns and \
           pd.to_numeric(fs["qqq_close"], errors="coerce").notna().sum() >= 2:
            bench["qqq"] = pd.to_numeric(fs["qqq_close"], errors="coerce")
        else:
            qqq_hist = fetch_hist("QQQ")          # yfinance-only; may be empty on cloud
            if not qqq_hist.empty:
                closes = {d.isoformat(): float(c)
                          for d, c in zip(qqq_hist.index.date, qqq_hist["Close"])}
                bench["qqq"] = bench["snap_date"].astype(str).map(closes)
            else:
                bench["qqq"] = np.nan
        bench = bench.dropna(subset=["qqq"]).reset_index(drop=True)

        if len(bench) >= 2:
            q0 = float(bench["qqq"].iloc[0])
            # FUND line = the actual NAV/unit (already 100 at inception since
            # SEED = $100). QQQ indexed to 100 at the first snapshot so both
            # sit on a comparable scale.
            fund_idx  = bench["nav_per_unit"] / SEED_NAV_PER_UNIT * 100
            qqq_idx   = bench["qqq"] / q0 * 100
            basket_2x = 100 * (1 + 2 * (bench["qqq"] / q0 - 1))   # beta≈2 basket proxy

            st.markdown("### FUND vs NASDAQ — INDEXED TO 100 (100 = inception)")
            fig3 = go.Figure()
            fig3.add_scatter(x=bench["snap_date"], y=basket_2x, name="2× QQQ (≈ YOUR BASKET)",
                             mode="lines", line=dict(color="#666666", width=1, dash="dot"))
            fig3.add_scatter(x=bench["snap_date"], y=qqq_idx, name="QQQ",
                             mode="lines+markers", line=dict(color="#ff9900", width=2))
            fig3.add_scatter(x=bench["snap_date"], y=fund_idx, name="FUND (NAV/UNIT)",
                             mode="lines+markers", line=dict(color="#00c8ff", width=2))
            fig3.add_hline(y=100, line_color="#444444", line_dash="dot")
            fig3.update_layout(
                paper_bgcolor="#0a0a0a", plot_bgcolor="#0d0d0d",
                font=dict(family="IBM Plex Mono", color="#cccccc", size=11),
                legend=dict(orientation="h", y=1.14),
                margin=dict(l=40, r=20, t=30, b=40), height=340,
                xaxis=dict(gridcolor="#1e1e1e", type="category"),
                yaxis=dict(gridcolor="#1e1e1e"))
            st.plotly_chart(fig3, use_container_width=True)
            # Fair window comparison: both measured from the first snapshot.
            d_f = (fund_idx.iloc[-1] / fund_idx.iloc[0] - 1) * 100
            d_q = qqq_idx.iloc[-1] - 100
            st.caption(f"FUND now {fund_idx.iloc[-1]:.2f} (= NAV/unit above). Over the tracked "
                       f"window: FUND {d_f:+.1f}% vs QQQ {d_q:+.1f}% (implied ≈β2 basket "
                       f"{2*d_q:+.1f}%). Blue above grey in a selloff = the "
                       f"premium cushion absorbing beta — the strategy doing its job. Expect blue "
                       f"to LAG in strong rallies (capped upside): judge over full cycles.")
        else:
            st.markdown("### FUND vs NASDAQ")
            st.info("Benchmark unavailable — couldn't load QQQ history (the app's server is likely "
                    "blocked from Yahoo). It fills in automatically once the daily snapshot job has "
                    "stored QQQ closes for ≥2 days — run it from the Actions tab.")
    else:
        st.markdown("---")
        st.info("NAV history will appear here once the daily snapshot job has run. "
                "Each trading day adds one point.")

# ── Weekly report (one-click, in-app) ─────────────────────────────────────────
st.markdown("---")
st.markdown("### WEEKLY REPORT")
st.caption("Build the 3-page report (Performance · Benchmark vs QQQ · The Book) from the current data — "
           "no screenshots, no email. The open book is marked with the app's live feed; the benchmark uses the "
           "stored QQQ closes.")

def _rep_fund_name():
    try:
        return str(st.secrets.get("FUND_NAME", "") or "ITAKA FUND")
    except Exception:
        return "ITAKA FUND"

if st.button("📄 GENERATE WEEKLY REPORT", type="primary"):
    _rp = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts")
    if _rp not in sys.path:
        sys.path.insert(0, _rp)
    try:
        import app_report
        with st.spinner("Building report — marking the open book…"):
            _html = app_report.build_report_html(db.load_fund_snapshots(), db.get_trades_df(), _rep_fund_name())
        if not _html:
            st.warning("Need at least 2 daily snapshots to build the report.")
            st.session_state.pop("_report_html", None)
        else:
            st.session_state["_report_html"] = _html
    except Exception as e:
        st.error(f"Report build failed: {e}")

if st.session_state.get("_report_html"):
    import base64
    import streamlit.components.v1 as _components
    _html = st.session_state["_report_html"]
    _fname = f"{_rep_fund_name().split()[0].lower()}_report_{datetime.date.today().isoformat()}"

    # Primary PDF path: the browser's own print engine — vector, identical to the
    # file, and works on any deployment with no server-side libraries. Opens the
    # report in a new tab and auto-triggers Print → the user picks "Save as PDF".
    _b64 = base64.b64encode(_html.encode("utf-8")).decode("ascii")
    _components.html(
        '<button onclick="_openRep()" style="width:100%;padding:11px;background:#00c8ff;border:none;'
        'border-radius:6px;color:#00121a;font-weight:700;font-family:monospace;cursor:pointer;font-size:14px;">'
        '🖨  SAVE AS PDF</button>'
        '<div style="font-family:monospace;font-size:11px;color:#888;margin-top:6px;">Opens the report in a new tab '
        'and brings up Print — choose <b>Save as PDF</b> (Letter size, identical to the file).</div>'
        '<script>function _openRep(){var h=decodeURIComponent(escape(window.atob("' + _b64 + '")));'
        'var w=window.open("","_blank");if(!w){alert("Allow pop-ups for this site, then click SAVE AS PDF again.");return;}'
        'w.document.open();w.document.write(h);w.document.close();w.focus();setTimeout(function(){w.print();},600);}</script>',
        height=88)

    rc1, rc2, _ = st.columns([2, 2, 6])
    rc1.download_button("⬇ DOWNLOAD (HTML)", _html, _fname + ".html", "text/html", use_container_width=True)
    try:                                  # bonus: direct PDF download if WeasyPrint is available
        import weasyprint
        _pdf = weasyprint.HTML(string=_html).write_pdf()
        rc2.download_button("⬇ DOWNLOAD (PDF)", _pdf, _fname + ".pdf", "application/pdf", use_container_width=True)
    except Exception:
        pass

    _components.html(_html, height=850, scrolling=True)

st.markdown("---")
st.caption("NAV = NET CAPITAL IN + REALIZED + UNREALIZED  |  UNITS PRICED AT NAV/UNIT ON FLOW DATE  |  "
           "TWR = NAV/UNIT − 100  |  UNREALIZED MARKED AT LIVE OPTION MID / SPOT")
