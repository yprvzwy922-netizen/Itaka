"""
Options Desk — entrypoint / router.
Central password gate + grouped sidebar navigation (st.navigation).
Home content lives in pages/0_Home.py.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st
import bbg_style

st.set_page_config(page_title="Itaka Fund", page_icon=None, layout="wide",
                   initial_sidebar_state="expanded")
bbg_style.inject(guard=False)   # entrypoint renders the login itself

# ── Auth (guards every page — pages no longer need their own gate) ────────────
# FAIL-CLOSED: if the password secret is missing/unreadable, the app LOCKS
# (with instructions) instead of silently opening.
PASSWORD = ""
try:
    PASSWORD = str(st.secrets.get("SCREENER_PASSWORD", "") or "")
except Exception:
    PASSWORD = ""

if not PASSWORD:
    st.title("ITAKA FUND")
    st.error("LOCKED — no password configured. Add SCREENER_PASSWORD to the app's "
             "Secrets (Manage app → Settings → Secrets), save, and reload.")
    st.stop()

if not st.session_state.get("authenticated"):
    st.title("ITAKA FUND")
    st.markdown("---")
    pwd = st.text_input("PASSWORD", type="password")
    if st.button("LOGIN", type="primary"):
        if pwd == PASSWORD:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("INCORRECT PASSWORD")
    st.stop()

# ── Grouped navigation ────────────────────────────────────────────────────────
PAGES = {
    "HOME": [
        st.Page("pages/0_Home.py",         title="Home", default=True),
    ],
    "TRADING": [
        st.Page("pages/4_Option_Finder.py", title="Option Finder"),
        st.Page("pages/8_Order_Ticket.py",  title="Order Ticket"),
        st.Page("pages/5_Trade_Log.py",     title="Trade Log"),
    ],
    "FUND": [
        st.Page("pages/6_Portfolio.py",    title="Portfolio & Risk"),
        st.Page("pages/7_Fund.py",         title="Performance"),
    ],
}
try:
    # expanded=True keeps every section fully visible (no collapsed menu)
    nav = st.navigation(PAGES, position="sidebar", expanded=True)
except TypeError:
    nav = st.navigation(PAGES)
nav.run()
