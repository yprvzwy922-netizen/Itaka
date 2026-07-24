"""
Home — tool tiles. (Navigation itself lives in app.py via st.navigation.)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import streamlit as st
import bbg_style

bbg_style.inject()

st.title("ITAKA FUND")
st.markdown("Single-beneficiary put-selling tracker &nbsp;|&nbsp; live marks via Massive / yfinance &nbsp;|&nbsp; Reconcile with broker before trading",
            unsafe_allow_html=True)
st.markdown("---")

st.markdown("### SELECT A TOOL")
st.markdown(" ")

col1, col2, col3 = st.columns(3, gap="large")
with col1:
    st.markdown("**OPTION FINDER**")
    st.markdown("Deep-dive put/call chain for any ticker — strikes, yields, delta, score, payoff.")
    if st.button("OPEN OPTION FINDER", type="primary", use_container_width=True):
        st.switch_page("pages/4_Option_Finder.py")
with col2:
    st.markdown("**ROLL FINDER**")
    st.markdown("Roll an open short — scored later-expiry candidates, net credit at mid vs cross.")
    if st.button("OPEN ROLL FINDER", type="primary", use_container_width=True):
        st.switch_page("pages/9_Roll_Finder.py")
with col3:
    st.markdown("**ORDER TICKET**")
    st.markdown("Collect the strikes you picked into one broker-ready message.")
    if st.button("OPEN ORDER TICKET", type="primary", use_container_width=True):
        st.switch_page("pages/8_Order_Ticket.py")

st.markdown(" ")

col4, col5, col6 = st.columns(3, gap="large")
with col4:
    st.markdown("**TRADE LOG**")
    st.markdown("Record every trade — short puts, covered calls, spreads. Export to CSV.")
    if st.button("OPEN TRADE LOG", type="primary", use_container_width=True):
        st.switch_page("pages/5_Trade_Log.py")
with col5:
    st.markdown("**PORTFOLIO & RISK**")
    st.markdown("Open positions, delta exposure by stock and sector, risk limit gauges.")
    if st.button("OPEN PORTFOLIO", type="primary", use_container_width=True):
        st.switch_page("pages/6_Portfolio.py")
with col6:
    st.markdown("**PERFORMANCE**")
    st.markdown("Cash flows, NAV/unit (= time-weighted return), P&L and benchmark.")
    if st.button("OPEN PERFORMANCE", type="primary", use_container_width=True):
        st.switch_page("pages/7_Fund.py")

st.markdown(" ")

# ── Data feed status ──────────────────────────────────────────────────────────
import massive
with st.expander("DATA FEED STATUS (MASSIVE / YFINANCE)"):
    if massive.configured():
        st.success("MASSIVE API KEY CONFIGURED — chains, IV and spot come from Massive; "
                   "yfinance is the fallback + history source.")
        if st.button("RUN FEED SELF-TEST (AAPL)"):
            with st.spinner("Testing key entitlements..."):
                r = massive.self_test("AAPL")
            if r.get("ok"):
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("EXPIRATIONS", r.get("expirations", 0))
                c2.metric("CONTRACTS (1ST EXP)", r.get("contracts", 0))
                c3.metric("BID/ASK QUOTES", "YES" if r.get("has_bid_ask") else "NO")
                c4.metric("IV / GREEKS", f"{'YES' if r.get('has_iv') else 'NO'} / "
                                          f"{'YES' if r.get('has_greeks') else 'NO'}")
                if not r.get("has_bid_ask"):
                    st.info("This plan doesn't include NBBO quotes — pricing uses Massive's "
                            "15-min-delayed DAY CLOSE per contract (works after hours too), "
                            "with real IV/Greeks. Confirm final prices at the broker as usual.")
            else:
                st.error(f"Feed test failed: {r.get('error')}")
    else:
        st.info("No MASSIVE_API_KEY in secrets — running fully on yfinance (free, best-effort). "
                "Add the key in Manage app → Settings → Secrets to switch.")

st.caption("MATH: BLACK-SCHOLES EUROPEAN APPROX | NOT EXECUTION READY")
