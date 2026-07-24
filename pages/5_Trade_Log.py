"""
Trade Log — all strategies, auto-calculated fields, CSV export/import.
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

bbg_style.inject()


c_nav1, _ = st.columns([1, 9])
with c_nav1:
    if st.button("HOME"): st.switch_page("pages/0_Home.py")

st.title("TRADE LOG")
if db.configured():
    st.caption("STORAGE: SUPABASE (SHARED, PERSISTENT — SAME BOOK ON EVERY PC) | DTE, CASH SECURED, MAX LOSS AUTO-CALCULATED")
else:
    st.caption("STORAGE: SESSION ONLY — EXPORT CSV BEFORE CLOSING | SET SUPABASE SECRETS TO ENABLE SHARED PERSISTENCE")

# ── Store (DB-backed when configured, session otherwise) ──────────────────────
COLUMNS = db.TRADE_COLUMNS
trades: pd.DataFrame = db.get_trades_df()

# ── Import / Export ───────────────────────────────────────────────────────────
c_imp, c_exp, _ = st.columns([2, 2, 6])
with c_imp:
    uploaded = st.file_uploader("IMPORT CSV", type="csv", label_visibility="collapsed")
    if uploaded:
        try:
            loaded = pd.read_csv(uploaded)
            for c in COLUMNS:
                if c not in loaded.columns:
                    loaded[c] = None
            loaded = loaded[COLUMNS]
            # Guard so the held file isn't re-imported on every rerun — only set
            # AFTER a successful save, so a failed import can be retried.
            imp_key = f"{uploaded.name}_{len(loaded)}"
            if st.session_state.get("last_import") != imp_key:
                merged = pd.concat([trades, loaded], ignore_index=True)
                merged = merged.drop_duplicates(subset=["ID"], keep="last")
                ok = db.save_trades_df(merged)
                if ok:
                    st.session_state["last_import"] = imp_key
                    st.success(f"Imported {len(loaded)} trades (merged by ID).")
                    st.rerun()
                # on failure, db.save_trades_df already showed the Supabase error
        except Exception as e:
            st.error(f"CSV import failed: {e}")
with c_exp:
    st.markdown(" ")
    if not trades.empty:
        st.download_button("EXPORT CSV", trades.to_csv(index=False).encode(),
                           f"trades_{datetime.date.today()}.csv", "text/csv",
                           use_container_width=True, type="primary")

st.markdown("---")

# ── Strategy definitions (drives auto-calc logic) ─────────────────────────────
STRATEGIES = {
    "Short Put":                  {"legs":"single","type":"put",  "short":True},
    "Cash-Secured Put (Wheel)":   {"legs":"single","type":"put",  "short":True},
    "Bull Put Spread":            {"legs":"spread","type":"put",  "short":True},
    "Covered Call":               {"legs":"single","type":"call", "short":True},
    "Bear Call Spread":           {"legs":"spread","type":"call", "short":True},
    "Long Put (Hedge)":           {"legs":"single","type":"put",  "short":False},
    "Long Call":                  {"legs":"single","type":"call", "short":False},
    # Stock positions: CONTRACTS = SHARES, PREMIUM / CREDIT = entry price/share,
    # no expiry, multiplier 1 (not 100)
    "Long Stock":                 {"legs":"stock", "type":"stock","short":False},
}

def strat_mult(strategy: str) -> int:
    """P&L multiplier: 1 for stock (per share), 100 for option contracts."""
    return 1 if STRATEGIES.get(str(strategy), {}).get("legs") == "stock" else 100

STRAT_NAMES = list(STRATEGIES.keys())

# ── Auto-calc preview (outside form so it updates live) ───────────────────────
st.markdown("### NEW TRADE")

# Use session keys so values persist across reruns while filling the form
def ss(key, default): return st.session_state.setdefault(f"nt_{key}", default)

cc1, cc2, cc3, cc4 = st.columns(4)
nt_date     = cc1.date_input("DATE OPENED", datetime.date.today(), key="nt_date")
nt_ticker   = cc2.text_input("TICKER", key="nt_ticker").upper().strip()
nt_strategy = cc3.selectbox("STRATEGY", STRAT_NAMES, key="nt_strategy")
strat_def   = STRATEGIES[nt_strategy]
is_spread   = strat_def["legs"] == "spread"
is_stock    = strat_def["legs"] == "stock"
nt_contracts= cc4.number_input("SHARES" if is_stock else "CONTRACTS",
                               min_value=1, value=100 if is_stock else 1, key="nt_contracts")

sc1, sc2, sc3 = st.columns(3)
nt_short_strike = sc1.number_input(
    "SHORT STRIKE (sell leg)" + (" — N/A FOR STOCK" if is_stock else ""),
    min_value=0.0, step=0.50, key="nt_short_strike", disabled=is_stock)
nt_long_strike  = sc2.number_input(
    "LONG STRIKE (buy leg)" + (" — SPREADS ONLY" if is_spread else " — not needed"),
    min_value=0.0, step=0.50, key="nt_long_strike",
    disabled=not is_spread,
    help="Only for spreads — the strike you buy as protection"
)
nt_expiry = sc3.date_input("EXPIRY DATE" + (" — N/A FOR STOCK" if is_stock else ""),
                           datetime.date.today() + datetime.timedelta(days=35),
                           key="nt_expiry", disabled=is_stock)

pc1, pc1b, pc2 = st.columns(3)
nt_premium = pc1.number_input(
    "ENTRY PRICE PER SHARE" if is_stock else "PREMIUM / NET CREDIT (per share)",
    min_value=0.0, step=0.01, key="nt_premium",
    help="Stock: your purchase price per share." if is_stock else
         "For short options: credit received per share. For spreads: net credit = sell leg − buy leg.")
# Manual: log the Alpha Trend signal that triggered every trade (daily chart)
nt_signal  = pc1b.selectbox("ALPHA TREND SIGNAL (DAILY)", [
    "MACRO GREEN + STRENGTH",
    "BULLISH TURQUOISE 'R' (CONFIRMED)",
    "MACRO GREEN (PLAIN)",
    "DOTS FLIPPED RED (DE-RISKED)",
    "TOPPING 'T' / YELLOW 'R'",
    "MACRO RED",
    "OTHER / NOT SIGNAL-DRIVEN",
], key="nt_signal")
nt_notes   = pc2.text_input("NOTES", key="nt_notes")

# ── Accountability: who recommended this trade + was it a consensus call ───────
ac1, ac2, ac3 = st.columns([2, 1.5, 6])
# Single-owner fund — no investors table. Keep a light accountability tag.
_rec_opts = ["Owner", "Consensus", "Other"]
nt_rec = ac1.selectbox("RECOMMENDED BY", _rec_opts, key="nt_rec",
                       help="Who put this trade forward (accountability).")
nt_consensus = ac2.checkbox("CONSENSUS TRADE", key="nt_consensus",
                            help="Flag if this was an agreed / high-conviction call.")

# Auto-calculations
nt_dte = None if is_stock else max((nt_expiry - datetime.date.today()).days, 0)

if is_stock:
    # Long stock: cost basis = price x shares; worst case stock -> $0
    nt_cash_secured = nt_premium * nt_contracts
    nt_max_loss = nt_cash_secured
    cash_note = f"Entry ${nt_premium:.2f} × {nt_contracts} shares = ${nt_cash_secured:,.0f}"
    loss_note = f"Stock → $0 = ${nt_max_loss:,.0f}"

elif strat_def["type"] == "put" and strat_def["short"] and not is_spread:
    # Short Put / Wheel: cash secured = strike × 100 × contracts
    nt_cash_secured = nt_short_strike * 100 * nt_contracts
    nt_max_loss = nt_cash_secured  # worst case: stock to zero
    cash_note = f"Strike × 100 × contracts = ${nt_cash_secured:,.0f}"
    loss_note = f"Same as cash secured (stock → $0) = ${nt_max_loss:,.0f}"

elif is_spread and nt_long_strike > 0 and nt_short_strike > 0:
    # Spread: max loss = (width - net credit) × 100 × contracts
    spread_width = abs(nt_long_strike - nt_short_strike)
    nt_cash_secured = 0.0
    nt_max_loss = max((spread_width - nt_premium) * 100 * nt_contracts, 0)
    cash_note = "N/A (spread — margin = max loss)"
    loss_note = f"(Width ${spread_width:.2f} − Credit ${nt_premium:.2f}) × 100 × {nt_contracts} = ${nt_max_loss:,.0f}"

elif strat_def["type"] == "call" and strat_def["short"] and not is_spread:
    # Covered Call: no extra cash needed (you own the stock)
    nt_cash_secured = 0.0
    nt_max_loss = 0.0  # capped by stock ownership
    cash_note = "N/A — you own the underlying"
    loss_note = "Capped by stock ownership (opportunity cost only)"

else:
    nt_cash_secured = nt_short_strike * 100 * nt_contracts if nt_short_strike > 0 else 0
    nt_max_loss = nt_premium * 100 * nt_contracts if not strat_def["short"] else nt_cash_secured
    cash_note = f"${nt_cash_secured:,.0f}"
    loss_note = f"${nt_max_loss:,.0f}"

# Preview calculated values
pc3, pc4, pc5, pc6 = st.columns(4)
pc3.metric("DTE (AUTO)", "—" if nt_dte is None else nt_dte, help="Expiry date − today (N/A for stock)")
pc4.metric("CASH DEPLOYED (AUTO)", f"${nt_cash_secured:,.0f}", help=cash_note)
pc5.metric("MAX LOSS (AUTO)", f"${nt_max_loss:,.0f}", help=loss_note)
if is_stock:
    pc6.metric("COST BASIS ($)", f"${nt_premium*nt_contracts:,.0f}",
               help="Entry price × shares")
else:
    pc6.metric("TOTAL CREDIT ($)", f"${nt_premium*100*nt_contracts:,.0f}",
               help="Premium per share × 100 × contracts")

if st.button("ADD TRADE", type="primary", use_container_width=False):
    if not nt_ticker:
        st.error("Enter a ticker.")
    else:
        # Robust next-ID: handles imported CSVs missing/empty/non-numeric ID column
        if not trades.empty and "ID" in trades.columns:
            ids = pd.to_numeric(trades["ID"], errors="coerce").dropna()
            new_id = int(ids.max()) + 1 if not ids.empty else 1
        else:
            new_id = 1
        new_row = {
            "ID":               new_id,
            "DATE OPENED":      nt_date.isoformat(),
            "TICKER":           nt_ticker,
            "STRATEGY":         nt_strategy,
            "SHORT STRIKE":     nt_short_strike if nt_short_strike > 0 and not is_stock else None,
            "LONG STRIKE":      nt_long_strike  if is_spread and nt_long_strike > 0 else None,
            "EXPIRY":           None if is_stock else nt_expiry.isoformat(),
            "DTE OPEN":         nt_dte,
            "CONTRACTS":        nt_contracts,
            "PREMIUM / CREDIT": nt_premium,
            "CASH SECURED":     nt_cash_secured if nt_cash_secured > 0 else None,
            "MAX LOSS":         nt_max_loss     if nt_max_loss > 0 else None,
            "STATUS":           "OPEN",
            "DATE CLOSED":      None,
            "CLOSE PRICE":      None,
            "REALIZED PNL":     None,
            "SIGNAL":           nt_signal,
            "RECOMMENDED BY":   nt_rec,
            "CONSENSUS":        bool(nt_consensus),
            "NOTES":            nt_notes,
        }
        db.save_trades_df(pd.concat([trades, pd.DataFrame([new_row])], ignore_index=True))
        if is_stock:
            st.success(f"Added: {nt_strategy} on {nt_ticker} | {nt_contracts} shares @ ${nt_premium:.2f} | Cost ${nt_premium*nt_contracts:,.0f}")
        else:
            st.success(f"Added: {nt_strategy} on {nt_ticker} | Strike ${nt_short_strike:.2f} | Expiry {nt_expiry} | Credit ${nt_premium*100*nt_contracts:,.0f}")
        st.rerun()

# ── Close a trade ─────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("### CLOSE / EXPIRE A TRADE")

trades = st.session_state["trades"]
open_trades = trades[trades["STATUS"] == "OPEN"].copy() if not trades.empty else pd.DataFrame()

if not open_trades.empty:
    cx1, cx2, cx3, cx4, cx5 = st.columns(5)
    close_id = cx1.selectbox(
        "SELECT TRADE",
        open_trades["ID"].tolist(),
        format_func=lambda i: f"#{i}  {open_trades[open_trades['ID']==i]['TICKER'].values[0]}  {open_trades[open_trades['ID']==i]['STRATEGY'].values[0]}  {open_trades[open_trades['ID']==i]['EXPIRY'].values[0]}",
        key="close_id",
    )
    _sel = trades[trades["ID"] == close_id].iloc[0]
    _full = int(_sel["CONTRACTS"]) if pd.notna(_sel["CONTRACTS"]) else 1
    # Reset the qty box when the selected trade changes
    if st.session_state.get("close_last_id") != close_id:
        st.session_state["close_qty"] = _full
        st.session_state["close_last_id"] = close_id
    close_qty = cx2.number_input("QTY TO CLOSE", min_value=1, max_value=_full, step=1, key="close_qty",
                                 help="Close PART of the position (e.g. half at 50% profit) or all of it.")
    close_status = cx3.selectbox("OUTCOME", [
        "EXPIRED WORTHLESS (MAX PROFIT)",
        "CLOSED EARLY",
        "ASSIGNED / EXERCISED",
        "ROLLED",
        "STOP LOSS HIT",
    ])
    close_price = cx4.number_input("BUYBACK / CLOSE PRICE (per share)", min_value=0.0, step=0.01,
                                   help="For short options: premium to buy back. 0 if expired worthless.")
    close_date  = cx5.date_input("DATE CLOSED", datetime.date.today(), key="close_date")

    # Strategy facts; `qty` = how many contracts/shares are being closed
    def _close_facts(row, qty):
        strat    = str(row["STRATEGY"])
        sdef     = STRATEGIES.get(strat, {})
        is_short = sdef.get("short", True)
        mult     = strat_mult(strat)
        prem     = float(row["PREMIUM / CREDIT"] or 0)
        full     = int(row["CONTRACTS"]) if pd.notna(row["CONTRACTS"]) else 1
        qty      = min(int(qty), full)
        strike   = float(row["SHORT STRIKE"]) if pd.notna(row["SHORT STRIKE"]) else 0.0
        assigned = close_status == "ASSIGNED / EXERCISED"
        put_assigned = (assigned and is_short and sdef.get("type") == "put"
                        and sdef.get("legs") == "single")
        cc_assigned  = assigned and strat == "Covered Call"
        if assigned and is_short:
            realized = prem * mult * qty                       # keep full premium
        elif is_short:
            realized = (prem - close_price) * mult * qty
        else:
            realized = (close_price - prem) * mult * qty
        is_csp = strat in ("Short Put", "Cash-Secured Put (Wheel)") and strike > 0
        return dict(strat=strat, is_short=is_short, mult=mult, prem=prem, full=full,
                    qty=qty, strike=strike, put_assigned=put_assigned,
                    cc_assigned=cc_assigned, realized=realized, is_csp=is_csp)

    if close_id:
        row = trades[trades["ID"] == close_id].iloc[0]
        f   = _close_facts(row, close_qty)
        denom = f["strike"] * 100 * f["qty"] if f["is_csp"] else (
                float(row["MAX LOSS"]) if pd.notna(row["MAX LOSS"]) and row["MAX LOSS"] else 0)
        return_pct = f["realized"] / denom if denom else 0
        partial = f["qty"] < f["full"]
        tag = f" (PARTIAL — {f['qty']}/{f['full']}, {f['full']-f['qty']} stay open)" if partial else ""
        st.info(f"REALIZED P&L on {f['qty']} ct{tag}: **${f['realized']:,.2f}**  |  Return on capital: **{return_pct:.1%}**")
        if f["put_assigned"] and f["strike"] > 0:
            eff = f["strike"] - f["prem"]
            st.warning(f"ASSIGNMENT → will create LONG STOCK: **{f['qty']*100} shares of "
                       f"{row['TICKER']} @ ${f['strike']:.2f}** (effective basis ${eff:.2f} after premium).")
        elif f["cc_assigned"]:
            st.warning("COVERED CALL ASSIGNED → your shares are CALLED AWAY. "
                       "Close/trim the matching LONG STOCK position manually in the table below.")

    if st.button("CLOSE TRADE", type="primary"):
        row = trades[trades["ID"] == close_id].iloc[0]
        f   = _close_facts(row, close_qty)
        idx = trades[trades["ID"] == close_id].index[0]
        partial = f["qty"] < f["full"]

        def _next_id(df):
            ids = pd.to_numeric(df["ID"], errors="coerce").dropna()
            return int(ids.max()) + 1 if not ids.empty else 1

        extra = []
        if partial:
            # Shrink the open trade to the remaining contracts...
            remaining = f["full"] - f["qty"]
            trades.at[idx, "CONTRACTS"] = remaining
            if f["is_csp"]:
                trades.at[idx, "CASH SECURED"] = f["strike"] * 100 * remaining
                trades.at[idx, "MAX LOSS"]     = f["strike"] * 100 * remaining
            # ...and book the closed portion as its own closed row
            closed = {c: row[c] for c in COLUMNS}
            closed.update({
                "CONTRACTS": f["qty"], "STATUS": close_status,
                "DATE CLOSED": close_date.isoformat(), "CLOSE PRICE": close_price,
                "REALIZED PNL": round(f["realized"], 2),
                "CASH SECURED": f["strike"]*100*f["qty"] if f["is_csp"] else row.get("CASH SECURED"),
                "MAX LOSS":     f["strike"]*100*f["qty"] if f["is_csp"] else row.get("MAX LOSS"),
                "NOTES": f"Partial close {f['qty']}/{f['full']} of #{close_id}",
            })
            extra.append(closed)
            msg = f"Closed {f['qty']}/{f['full']} ct of #{close_id}. P&L: ${f['realized']:,.2f} | {remaining} still open."
        else:
            trades.at[idx, "STATUS"]      = close_status
            trades.at[idx, "DATE CLOSED"] = close_date.isoformat()
            trades.at[idx, "CLOSE PRICE"] = close_price
            trades.at[idx, "REALIZED PNL"]= round(f["realized"], 2)
            msg = f"Trade #{close_id} closed. P&L: ${f['realized']:,.2f}"

        # Assigned short put -> create Long Stock for the assigned (closed) qty
        if f["put_assigned"] and f["strike"] > 0:
            shares = f["qty"] * 100
            stock_row = {c: None for c in COLUMNS}
            stock_row.update({
                "DATE OPENED": close_date.isoformat(), "TICKER": row["TICKER"],
                "STRATEGY": "Long Stock", "CONTRACTS": shares, "PREMIUM / CREDIT": f["strike"],
                "CASH SECURED": round(f["strike"] * shares, 2),
                "MAX LOSS": round(f["strike"] * shares, 2),
                "STATUS": "OPEN", "SIGNAL": row.get("SIGNAL"),
                "NOTES": f"Assigned from put #{close_id} @ ${f['strike']:.2f}",
            })
            extra.append(stock_row)
            msg += f"  →  Created LONG STOCK: {shares} sh {row['TICKER']} @ ${f['strike']:.2f}"

        new_frame = trades
        if extra:
            base = _next_id(trades)
            for i, r in enumerate(extra):
                r["ID"] = base + i
            new_frame = pd.concat([trades, pd.DataFrame(extra)], ignore_index=True)

        db.save_trades_df(new_frame)
        st.success(msg)
        st.rerun()
else:
    st.caption("No open trades.")

# ── Modify / cancel a trade ───────────────────────────────────────────────────
st.markdown("---")
st.markdown("### MODIFY / CANCEL A TRADE")
trades = st.session_state["trades"]

if trades.empty:
    st.caption("No trades to modify.")
else:
    ids_all = pd.to_numeric(trades["ID"], errors="coerce").dropna().astype(int).tolist()
    def _lbl(i):
        r = trades[trades["ID"] == i].iloc[0]
        return f"#{i}  {r['TICKER']}  {r['STRATEGY']}  K{r['SHORT STRIKE']}  {r['EXPIRY']}  [{r['STATUS']}]"
    mod_id = st.selectbox("SELECT TRADE", ids_all, format_func=_lbl, key="mod_id")
    row = trades[trades["ID"] == mod_id].iloc[0]
    is_stock_row = str(row["STRATEGY"]) == "Long Stock"

    # When the selected trade changes, refresh the input fields to ITS values
    # (widgets with keys otherwise keep the previous trade's numbers).
    try:
        _cur_exp = datetime.date.fromisoformat(str(row["EXPIRY"]))
    except Exception:
        _cur_exp = datetime.date.today() + datetime.timedelta(days=35)
    if st.session_state.get("mod_last_id") != mod_id:
        st.session_state["mod_strike"] = float(row["SHORT STRIKE"]) if pd.notna(row["SHORT STRIKE"]) else 0.0
        st.session_state["mod_ctrs"]   = int(row["CONTRACTS"]) if pd.notna(row["CONTRACTS"]) else 1
        st.session_state["mod_prem"]   = float(row["PREMIUM / CREDIT"]) if pd.notna(row["PREMIUM / CREDIT"]) else 0.0
        st.session_state["mod_exp"]    = _cur_exp
        st.session_state["mod_mark"]   = float(row["MANUAL MARK"]) if pd.notna(row.get("MANUAL MARK")) and row.get("MANUAL MARK") else 0.0
        st.session_state["mod_ncb"]    = float(row["NET CREDIT BASIS"]) if pd.notna(row.get("NET CREDIT BASIS")) and row.get("NET CREDIT BASIS") else 0.0
        st.session_state["mod_last_id"] = mod_id

    mc1, mc2, mc3, mc4, mc5, mc6 = st.columns(6)
    m_strike = mc1.number_input("SHORT STRIKE", min_value=0.0, step=0.50,
                                disabled=is_stock_row, key="mod_strike")
    m_ctrs   = mc2.number_input("CONTRACTS / SHARES", min_value=1, step=1, key="mod_ctrs")
    m_prem   = mc3.number_input("PREMIUM / ENTRY", min_value=0.0, step=0.01, key="mod_prem")
    m_exp    = mc4.date_input("EXPIRY", disabled=is_stock_row, key="mod_exp")
    m_mark   = mc5.number_input("MANUAL MARK ($/SHARE)", min_value=0.0, step=0.01, key="mod_mark",
                                help="Current price from your BROKER for thin names Yahoo can't quote. "
                                     "Overrides the live mid in P&L/NAV. Set 0 to go back to automatic.")
    m_ncb    = mc6.number_input("NET CREDIT BASIS ($/SH)", min_value=0.0, step=0.01, key="mod_ncb",
                                help="ROLLED positions only: the CAMPAIGN's cumulative net credit per "
                                     "share (e.g. NUAI = 1.25). The profit-take ACTION then measures "
                                     "against this, not the new leg's premium. 0 = use the leg premium.")

    cu1, cu2, _ = st.columns([2, 2, 6])
    if cu1.button("UPDATE TRADE", type="primary", use_container_width=True):
        idx = trades[trades["ID"] == mod_id].index[0]
        trades.at[idx, "CONTRACTS"]        = m_ctrs
        trades.at[idx, "PREMIUM / CREDIT"] = m_prem
        trades.at[idx, "MANUAL MARK"]      = float(m_mark) if m_mark > 0 else float("nan")
        trades.at[idx, "NET CREDIT BASIS"] = float(m_ncb) if m_ncb > 0 else float("nan")
        if not is_stock_row:
            trades.at[idx, "SHORT STRIKE"] = float(m_strike) if m_strike > 0 else float("nan")
            trades.at[idx, "EXPIRY"]       = m_exp.isoformat()
            try:
                d_open = datetime.date.fromisoformat(str(row["DATE OPENED"]))
            except Exception:
                d_open = datetime.date.today()
            trades.at[idx, "DTE OPEN"]     = max((m_exp - d_open).days, 0)
            # Recompute cash/max-loss for single-leg short puts
            if str(row["STRATEGY"]) in ("Short Put", "Cash-Secured Put (Wheel)") and m_strike > 0:
                trades.at[idx, "CASH SECURED"] = m_strike * 100 * m_ctrs
                trades.at[idx, "MAX LOSS"]     = m_strike * 100 * m_ctrs
        else:
            trades.at[idx, "CASH SECURED"] = m_prem * m_ctrs
            trades.at[idx, "MAX LOSS"]     = m_prem * m_ctrs
        db.save_trades_df(trades)
        st.success(f"Trade #{mod_id} updated.")
        st.rerun()

    if cu2.button("DELETE TRADE", use_container_width=True):
        db.remove_trades([mod_id])          # targeted delete — won't touch other rows
        st.success(f"Trade #{mod_id} deleted.")
        st.rerun()

# ── Summary ───────────────────────────────────────────────────────────────────
st.markdown("---")
trades = st.session_state["trades"]

if not trades.empty:
    open_ct    = (trades["STATUS"] == "OPEN").sum()
    closed_ct  = (trades["STATUS"] != "OPEN").sum()
    total_pnl  = pd.to_numeric(trades["REALIZED PNL"], errors="coerce").sum()
    # Option credits only — for Long Stock the premium column is an entry price
    opt_rows   = trades[trades["STRATEGY"] != "Long Stock"]
    total_cred = (pd.to_numeric(opt_rows["PREMIUM / CREDIT"], errors="coerce") *
                  pd.to_numeric(opt_rows["CONTRACTS"], errors="coerce")).sum() * 100

    k1,k2,k3,k4 = st.columns(4)
    k1.metric("OPEN",           open_ct)
    k2.metric("CLOSED",         closed_ct)
    k3.metric("REALIZED P&L",   f"${total_pnl:,.2f}")
    k4.metric("TOTAL CREDITS COLLECTED", f"${total_cred:,.0f}")

    st.markdown("---")
    st.markdown("### ALL TRADES")
    st.caption("Edit cells directly. Changes save automatically to this session.")

    edited = st.data_editor(
        trades,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "STATUS": st.column_config.SelectboxColumn("STATUS", options=[
                "OPEN","EXPIRED WORTHLESS (MAX PROFIT)","CLOSED EARLY",
                "ASSIGNED / EXERCISED","ROLLED","STOP LOSS HIT"]),
            "REALIZED PNL":     st.column_config.NumberColumn(format="$%.2f"),
            "PREMIUM / CREDIT": st.column_config.NumberColumn(format="$%.2f"),
            "CASH SECURED":     st.column_config.NumberColumn(format="$%.0f"),
            "MAX LOSS":         st.column_config.NumberColumn(format="$%.0f"),
        }
    )
    if not edited.equals(trades):
        # Rows added in the editor get the next free ID before persisting
        if edited["ID"].isna().any():
            ids = pd.to_numeric(edited["ID"], errors="coerce")
            nxt = int(ids.max()) + 1 if ids.notna().any() else 1
            for i in edited.index[ids.isna()]:
                edited.at[i, "ID"] = nxt
                nxt += 1
        # Rows the user removed in the editor -> delete ONLY those ids (targeted)
        before = set(pd.to_numeric(trades["ID"], errors="coerce").dropna().astype(int))
        after  = set(pd.to_numeric(edited["ID"], errors="coerce").dropna().astype(int))
        removed = before - after
        if removed:
            db.remove_trades(list(removed))
        db.save_trades_df(edited)
        st.rerun()

    # P&L by strategy
    closed = trades[trades["STATUS"] != "OPEN"].copy()
    if not closed.empty:
        closed["REALIZED PNL"] = pd.to_numeric(closed["REALIZED PNL"], errors="coerce")
        by_strat = closed.groupby("STRATEGY")["REALIZED PNL"].agg(["sum","count","mean"]).reset_index()
        by_strat.columns = ["STRATEGY","TOTAL PNL","TRADES","AVG PNL"]
        st.markdown("### P&L BY STRATEGY")
        st.dataframe(
            by_strat.style.format({"TOTAL PNL":"${:,.2f}","AVG PNL":"${:,.2f}"}),
            use_container_width=True, hide_index=True)

        # ── Per-trade return on capital (closed trades only) ──────────────────
        rt = closed.copy()
        cap = pd.to_numeric(rt["CASH SECURED"], errors="coerce")
        cap = cap.fillna(pd.to_numeric(rt["MAX LOSS"], errors="coerce"))   # spreads: use max loss
        rt["CAPITAL"] = cap
        opened = pd.to_datetime(rt["DATE OPENED"], errors="coerce")
        closedd = pd.to_datetime(rt["DATE CLOSED"], errors="coerce")
        rt["DAYS"] = (closedd - opened).dt.days.clip(lower=1)
        rt["ROC"]  = rt["REALIZED PNL"] / rt["CAPITAL"]
        rt["ANN. RETURN"] = rt["ROC"] * 365.0 / rt["DAYS"]
        # Only trades whose P&L is FINAL and complete. Assigned (premium kept but
        # the real P&L is now in the stock) and Rolled (loss booked but the
        # campaign continues in the new leg) would show a misleading return.
        CLEAN = ["EXPIRED WORTHLESS (MAX PROFIT)", "CLOSED EARLY", "STOP LOSS HIT"]
        rcols = ["TICKER","STRATEGY","STATUS","DATE OPENED","DATE CLOSED","DAYS",
                 "CAPITAL","REALIZED PNL","ROC","ANN. RETURN"]
        clean_mask = rt["CAPITAL"].notna() & closedd.notna() & rt["STATUS"].isin(CLEAN)
        excluded   = int((closedd.notna() & ~rt["STATUS"].isin(CLEAN)).sum())
        show = rt[clean_mask][rcols].rename(
            columns={"STATUS":"OUTCOME","DATE OPENED":"OPENED","DATE CLOSED":"CLOSED"})
        if not show.empty:
            st.markdown("### CLOSED TRADES — RETURN ON CAPITAL")
            def _cr(v):
                try: return "color:#00e676;font-weight:600" if float(v)>0 else ("color:#ff4444;font-weight:600" if float(v)<0 else "")
                except Exception: return ""
            st.dataframe(
                show.sort_values("CLOSED", ascending=False).style
                    .map(_cr, subset=["REALIZED PNL","ROC","ANN. RETURN"])
                    .format({"CAPITAL":"${:,.0f}","REALIZED PNL":"${:,.2f}","DAYS":"{:.0f}",
                             "ROC":"{:.1%}","ANN. RETURN":"{:.0%}"}, na_rep="—"),
                use_container_width=True, hide_index=True)
            cap = ("ANN. RETURN = (realized ÷ capital at risk) × 365 ÷ days held. FINISHED trades "
                   "only — a fast 50% close is capital-efficient, but short holds over-annualize, "
                   "so read those as 'efficient', not a yearly rate.")
            if excluded:
                cap += f"  {excluded} assigned/rolled trade(s) are shown separately below."
            st.caption(cap)

        # ── Assigned / rolled — shown SEPARATELY (P&L not final) ──────────────
        pend = rt[closedd.notna() & ~rt["STATUS"].isin(CLEAN)].copy()
        if not pend.empty:
            pend["CONTINUES IN"] = pend["STATUS"].map(
                lambda s: "→ assigned stock" if "ASSIGNED" in str(s) else "→ new (rolled) leg")
            pv = pend[["TICKER","STRATEGY","STATUS","DATE CLOSED","REALIZED PNL","CONTINUES IN"]].rename(
                columns={"STATUS":"OUTCOME","DATE CLOSED":"CLOSED","REALIZED PNL":"BOOKED (LEG ONLY)"})
            with st.expander(f"ASSIGNED / ROLLED — {len(pv)} trade(s), P&L NOT FINAL (no return shown)"):
                st.dataframe(
                    pv.sort_values("CLOSED", ascending=False).style
                      .format({"BOOKED (LEG ONLY)":"${:,.2f}"}, na_rep="—"),
                    use_container_width=True, hide_index=True)
                st.caption("Deliberately no return here — these aren't finished. The amount is ONE leg "
                           "only: an assigned put keeps its premium but the real P&L is now in the stock; "
                           "a roll books this leg's loss but the campaign continues. The full return "
                           "becomes real when the stock is sold / the rolled position finally closes.")

    # ── Accountability — who recommended what, and how it did ──────────────────
    if "RECOMMENDED BY" in trades.columns and trades["RECOMMENDED BY"].notna().any():
        st.markdown("### ACCOUNTABILITY — TRADES BY RECOMMENDER")
        acc = trades.copy()
        acc["RECOMMENDED BY"] = acc["RECOMMENDED BY"].fillna("—")
        acc["REALIZED PNL"]   = pd.to_numeric(acc["REALIZED PNL"], errors="coerce")
        acc["CONSENSUS"]      = acc["CONSENSUS"].fillna(False).astype(bool)
        tally = acc.groupby("RECOMMENDED BY").agg(
            TRADES=("ID", "count"),
            OPEN=("STATUS", lambda s: (s == "OPEN").sum()),
            CLOSED=("STATUS", lambda s: (s != "OPEN").sum()),
            CONSENSUS=("CONSENSUS", "sum"),
            REALIZED_PNL=("REALIZED PNL", "sum"),
        ).reset_index()
        ck1, ck2, ck3 = st.columns(3)
        ck1.metric("TOTAL TRADES LOGGED", int(tally["TRADES"].sum()))
        ck2.metric("CONSENSUS TRADES", int(acc["CONSENSUS"].sum()))
        ck3.metric("SOLO TRADES", int((~acc["CONSENSUS"]).sum()))
        def _cpnl(v):
            try: return "color:#00e676" if float(v) > 0 else "color:#ff4444" if float(v) < 0 else ""
            except: return ""
        st.dataframe(
            tally.style.map(_cpnl, subset=["REALIZED_PNL"])
                 .format({"REALIZED_PNL": "${:,.2f}"}),
            use_container_width=True, hide_index=True)
        st.caption("Accountability: tracks who put each trade forward and how their calls performed. "
                   "CONSENSUS = everyone agreed.")

    # ── Income chart — realized premium vs the plan ───────────────────────────
    if not closed.empty and closed["DATE CLOSED"].notna().any():
        inc = closed[closed["DATE CLOSED"].notna()].copy()
        inc["MONTH"] = pd.to_datetime(inc["DATE CLOSED"], errors="coerce").dt.to_period("M").astype(str)
        monthly = inc.groupby("MONTH")["REALIZED PNL"].sum().reset_index()
        monthly["CUMULATIVE"] = monthly["REALIZED PNL"].cumsum()

        st.markdown("### REALIZED INCOME")
        fig = go.Figure()
        fig.add_bar(x=monthly["MONTH"], y=monthly["REALIZED PNL"], name="MONTHLY P&L",
                    marker_color="#00c8ff")
        fig.add_scatter(x=monthly["MONTH"], y=monthly["CUMULATIVE"], name="CUMULATIVE",
                        mode="lines+markers", line=dict(color="#00e676", width=2))
        # Manual plan: 30% on $1M = ~$25k/month glidepath
        fig.add_scatter(x=monthly["MONTH"], y=[25000*(i+1) for i in range(len(monthly))],
                        name="PLAN (30% / $25K MO)", mode="lines",
                        line=dict(color="#ff9900", width=1, dash="dot"))
        fig.update_layout(
            paper_bgcolor="#0a0a0a", plot_bgcolor="#0d0d0d",
            font=dict(family="IBM Plex Mono", color="#cccccc", size=11),
            legend=dict(orientation="h", y=1.1),
            margin=dict(l=40, r=20, t=30, b=40), height=360,
            xaxis=dict(gridcolor="#1e1e1e"), yaxis=dict(gridcolor="#1e1e1e", tickprefix="$"))
        st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No trades yet. Add your first trade above.")

st.markdown("---")
if db.configured():
    st.caption("STORAGE: SUPABASE — TRADES SHARED ACROSS ALL PCS AND SESSIONS")
else:
    st.caption("SESSION ONLY — EXPORT CSV BEFORE CLOSING BROWSER")
