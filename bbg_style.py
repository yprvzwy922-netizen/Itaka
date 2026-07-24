"""
Bloomberg-style CSS injection.
Call inject() at the top of every page.
"""
import streamlit as st

BBG_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap');

/* ── Base ── */
html, body, [class*="css"] {
    font-family: 'IBM Plex Sans', sans-serif;
}

.stApp {
    background-color: #0a0a0a;
    color: #cccccc;
}

/* ── Typography ── */
h1 {
    font-family: 'IBM Plex Mono', monospace !important;
    color: #00c8ff !important;
    font-size: 1.3rem !important;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    border-bottom: 2px solid #00c8ff;
    padding-bottom: 6px;
    margin-bottom: 16px !important;
}

h2 {
    font-family: 'IBM Plex Mono', monospace !important;
    color: #00c8ff !important;
    font-size: 0.95rem !important;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    border-left: 3px solid #00c8ff;
    padding-left: 8px;
}

h3 {
    font-family: 'IBM Plex Mono', monospace !important;
    color: #aaaaaa !important;
    font-size: 0.8rem !important;
    text-transform: uppercase;
    letter-spacing: 0.08em;
}

p, li, .stMarkdown {
    color: #bbbbbb;
    font-size: 0.85rem;
}

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background-color: #0d0d0d !important;
    border-right: 1px solid #1e1e1e;
}

[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
    border: none !important;
    padding-left: 0 !important;
}

/* ── Buttons ── */
.stButton > button {
    background-color: #141414 !important;
    color: #cccccc !important;
    border: 1px solid #2a2a2a !important;
    border-radius: 0 !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.72rem !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 4px 10px !important;
    transition: all 0.1s;
}

.stButton > button:hover {
    background-color: #00c8ff !important;
    color: #000000 !important;
    border-color: #00c8ff !important;
}

.stButton > button[kind="primary"] {
    background-color: #00c8ff !important;
    color: #000000 !important;
    border-color: #00c8ff !important;
    font-weight: 600 !important;
}

.stButton > button[kind="primary"]:hover {
    background-color: #0099cc !important;
    border-color: #0099cc !important;
    color: #000000 !important;
}

/* All blue-background buttons must have black text — target button AND every child */
.stButton > button[kind="primary"],
.stButton > button[kind="primary"]:hover,
.stButton > button[kind="primary"]:active,
.stButton > button[kind="primary"]:focus,
button[data-testid="baseButton-primary"],
button[data-testid="baseButton-primary"]:hover,
.stButton > button[kind="primary"] *,
.stButton > button[kind="primary"] p,
.stButton > button[kind="primary"] div,
.stButton > button[kind="primary"] span,
button[data-testid="baseButton-primary"] *,
button[data-testid="baseButton-primary"] p,
button[data-testid="baseButton-primary"] div,
button[data-testid="baseButton-primary"] span {
    color: #000000 !important;
    font-weight: 700 !important;
}

/* ── Inputs ── */
.stTextInput > div > div > input,
.stNumberInput > div > div > input {
    background-color: #141414 !important;
    color: #cccccc !important;
    border: 1px solid #2a2a2a !important;
    border-radius: 0 !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.8rem !important;
}

.stSelectbox > div > div,
.stMultiSelect > div > div {
    background-color: #141414 !important;
    border: 1px solid #2a2a2a !important;
    border-radius: 0 !important;
    font-family: 'IBM Plex Mono', monospace !important;
}

/* ── Slider ── (colors come from .streamlit/config.toml theme — the old
      deep-child selector painted value labels as blue boxes on new Streamlit) */

/* ── Metrics ── */
[data-testid="metric-container"] {
    background-color: #111111;
    border: 1px solid #1e1e1e;
    border-radius: 0;
    padding: 10px 14px;
}

[data-testid="stMetricLabel"] {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.65rem !important;
    text-transform: uppercase;
    color: #666666 !important;
    letter-spacing: 0.08em;
}

[data-testid="stMetricValue"] {
    font-family: 'IBM Plex Mono', monospace !important;
    color: #00c8ff !important;
    font-size: 1.3rem !important;
}

/* ── Dataframe ── */
.stDataFrame {
    border: 1px solid #1e1e1e !important;
}

.stDataFrame th {
    background-color: #111111 !important;
    color: #00c8ff !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.68rem !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    border-bottom: 1px solid #2a2a2a !important;
}

.stDataFrame td {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.75rem !important;
    background-color: #0d0d0d !important;
    border-bottom: 1px solid #161616 !important;
}

/* ── Alerts ── */
.stSuccess {
    background-color: #0a1a0a !important;
    border: 1px solid #1a4d1a !important;
    border-radius: 0 !important;
    color: #4caf50 !important;
}

.stWarning {
    background-color: #1a1200 !important;
    border: 1px solid #4d3800 !important;
    border-radius: 0 !important;
    color: #00c8ff !important;
}

.stError {
    background-color: #1a0a0a !important;
    border: 1px solid #4d1a1a !important;
    border-radius: 0 !important;
    color: #ff4444 !important;
}

.stInfo {
    background-color: #0a0f1a !important;
    border: 1px solid #1a2d4d !important;
    border-radius: 0 !important;
}

/* ── Expander ── */
.streamlit-expanderHeader {
    background-color: #111111 !important;
    border: 1px solid #1e1e1e !important;
    border-radius: 0 !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.75rem !important;
    text-transform: uppercase;
    color: #aaaaaa !important;
}

/* ── Progress bar ── */
.stProgress > div > div > div > div {
    background-color: #00c8ff !important;
}

/* ── Caption ── */
.stCaption {
    color: #444444 !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.65rem !important;
}

/* ── Divider ── */
hr {
    border-color: #1e1e1e !important;
}

/* ── Tabs ── */
.stTabs [data-baseweb="tab"] {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.75rem !important;
    text-transform: uppercase;
    background-color: #111111 !important;
    color: #666666 !important;
    border-radius: 0 !important;
}

.stTabs [aria-selected="true"] {
    background-color: #00c8ff !important;
    color: #000000 !important;
}
</style>
"""

def inject(guard: bool = True):
    st.markdown(BBG_CSS, unsafe_allow_html=True)
    # DEFENSE IN DEPTH: every page calls inject(), so no page can render
    # without an authenticated session — independently of the entrypoint gate.
    # Only the entrypoint itself (which renders the login) passes guard=False.
    if guard and not st.session_state.get("authenticated"):
        st.error("LOCKED — open the app and log in.")
        st.stop()
