"""
Options Desk — entrypoint / router.
Central password gate + grouped sidebar navigation (st.navigation).
Home content lives in pages/0_Home.py.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

# ── Stale-module guard ────────────────────────────────────────────────────────
# Streamlit Cloud pulls new code on a git push and re-reads this file and the
# pages, but can keep the OLD copies of our own modules (shared, db, book, ...)
# in memory — a page then fails importing a name only the new copy has. Each
# run, drop any of our modules whose file changed since it was checked, or whose
# loaded copy lacks a function/class its file defines, so the next import loads
# it fresh. One stat() per module per run; a file is parsed only when it changes.
import ast
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_checked = sys.__dict__.setdefault("_app_module_mtimes", {})
for _name, _mod in list(sys.modules.items()):
    _file = getattr(_mod, "__file__", None) or ""
    if not _file.endswith(".py") or os.path.dirname(os.path.abspath(_file)) != _APP_DIR:
        continue
    try:
        _mtime = os.path.getmtime(_file)
        if _checked.get(_name) == _mtime:
            continue                                   # unchanged since last check
        with open(_file) as _fh:
            _defined = {n.name for n in ast.parse(_fh.read()).body
                        if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    except (OSError, SyntaxError):
        continue
    if _name in _checked or not _defined <= set(vars(_mod)):
        sys.modules.pop(_name, None)                   # stale -> imported fresh
        _checked.pop(_name, None)
    else:
        _checked[_name] = _mtime

import streamlit as st
import bbg_style

# Fund identity is per-deployment: set FUND_NAME in the app's Streamlit secrets.
# One codebase serves multiple funds — each Streamlit app points at its own
# Supabase and its own FUND_NAME. Defaults to ITAKA FUND when unset.
def _fund_name():
    try:
        return str(st.secrets.get("FUND_NAME", "") or "ITAKA FUND")
    except Exception:
        return "ITAKA FUND"
FUND_NAME = _fund_name()

st.set_page_config(page_title=FUND_NAME, page_icon=None, layout="wide",
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
    st.title(FUND_NAME)
    st.error("LOCKED — no password configured. Add SCREENER_PASSWORD to the app's "
             "Secrets (Manage app → Settings → Secrets), save, and reload.")
    st.stop()

if not st.session_state.get("authenticated"):
    st.title(FUND_NAME)
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
        st.Page("pages/9_Roll_Finder.py",   title="Roll Finder"),
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
