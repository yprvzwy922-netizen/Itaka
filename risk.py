"""
Risk engine — one set of limits, evaluated the same way everywhere: live
(Portfolio status strip + detail), before a trade (Option Finder pre-trade
check), and day by day over the trade log (breach history).

It measures how the book actually behaves, not just raw notional:
  • BETA of each name to QQQ, from our own daily closes (snapshots table);
  • BOOK BETA = beta-weighted $ delta / NAV — "the fund moves like N× QQQ";
  • TAIL = loss if QQQ falls 20%, each name moved by its beta, options repriced;
plus the manual's caps (single name / single trade / sector / bucket / stock
inventory / no naked calls), drawdown from the NAV-per-unit peak, and whether
every short put is still cash-secured.

Pure Python — no Streamlit, so the alert email can run it too.
"""
import math

import numpy as np
import pandas as pd

import book as bk

BENCH = "QQQ"

# One place for the policy. The Portfolio sidebar can override for a session.
LIMITS = {
    "tail_qqq20":    0.15,   # max loss if QQQ -20%, as a fraction of NAV
    "book_beta":     1.00,   # max beta-weighted $ delta / NAV (1.0 = like owning QQQ)
    "max_name":      0.10,   # max cash at risk in one name / NAV        (manual)
    "max_trade":     0.03,   # max cash at risk in one position / NAV    (manual)
    "max_sector":    0.30,   # max cash at risk in one sector / NAV      (manual)
    "max_spec":      0.40,   # max Speculative bucket / NAV              (manual)
    "min_core":      0.40,   # min Core bucket / NAV                     (manual)
    "max_stock_inv": 0.40,   # max held stock / NAV                      (manual §8.3)
    "dd_warn":       0.05,   # NAV/unit drawdown from peak: slow down
    "dd_stop":       0.10,   # NAV/unit drawdown from peak: stop adding risk
    # Pre-trade: while the QQQ tail / book beta are over their limits, a new trade
    # may add at most this much to them (every short put adds some; these let a
    # genuinely diversifying, low-beta trade through). Concentration has no tolerance.
    "tail_add_tol":  0.0025, # fraction of NAV added to the loss if QQQ -20%
    "beta_add_tol":  0.005,  # book beta added
}
WARN_AT = 0.85                                     # amber within 15% of a max limit
BUCKET_BETA = {"Core": 1.2, "Growth": 1.8, "Speculative": 2.5}   # when history is thin

STATUS_RANK = {"ok": 0, "warn": 1, "breach": 2}


# ── Prices & betas ────────────────────────────────────────────────────────────
def fetch_closes(get_rows, tickers, page=1000) -> pd.DataFrame:
    """Daily closes from the snapshots table, wide (index=date, columns=ticker).
    get_rows(params) -> list of rows, i.e. a PostgREST GET on `snapshots`.
    Pages through results (PostgREST caps a response at 1000 rows)."""
    tickers = sorted({str(t).upper() for t in tickers if t})
    if not tickers:
        return pd.DataFrame()
    rows, offset = [], 0
    while True:
        chunk = get_rows({"select": "snap_date,ticker,spot",
                          "ticker": f"in.({','.join(tickers)})",
                          "order": "snap_date,ticker", "limit": page, "offset": offset}) or []
        rows += chunk
        if len(chunk) < page:
            break
        offset += page
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["snap_date"] = pd.to_datetime(df["snap_date"]).dt.date
    df["spot"] = pd.to_numeric(df["spot"], errors="coerce")
    return df.pivot_table(index="snap_date", columns="ticker", values="spot").sort_index()


def betas_from_closes(closes, min_obs=40, lo=0.2, hi=4.0) -> dict:
    """Beta of each ticker's daily log returns to QQQ's (pairwise complete days)."""
    if closes is None or closes.empty or BENCH not in closes.columns:
        return {}
    r = np.log(closes / closes.shift(1))
    out = {}
    for t in r.columns:
        if t == BENCH:
            continue
        pair = r[[t, BENCH]].dropna()
        var = pair[BENCH].var()
        if len(pair) >= min_obs and var > 0:
            out[t] = float(np.clip(pair[t].cov(pair[BENCH]) / var, lo, hi))
    return out


def _with_betas(book, betas):
    b = book.copy()
    est = ~b["TICKER"].isin(list(betas))
    b["BETA"] = [betas.get(t, BUCKET_BETA.get(bu, 1.5)) for t, bu in zip(b["TICKER"], b["BUCKET"])]
    b["BETA EST"] = est.values
    b["BETA $ DELTA"] = pd.to_numeric(b["$ DELTA"], errors="coerce").fillna(0) * b["BETA"]
    return b


def qqq_shock(book, qqq_move) -> dict:
    """Per-ticker move when QQQ moves `qqq_move` (each name scaled by its beta)."""
    return {t: qqq_move * be for t, be in book.groupby("TICKER")["BETA"].first().items()}


# ── Evaluation ────────────────────────────────────────────────────────────────
def _max_status(v, lim):
    return "breach" if v > lim else ("warn" if v > WARN_AT * lim else "ok")


def _check(key, label, value, limit, status, detail, fmt="pct"):
    return {"key": key, "label": label, "value": value, "limit": limit,
            "status": status, "detail": detail, "fmt": fmt}


def evaluate(book, nav, betas=None, limits=None, *, npu=None, peak_npu=None,
             available=None, events=True) -> dict:
    """Every risk measure + limit check for one book.
    Returns {"checks": [...], "metrics": {...}, "book": book with BETA columns}."""
    L = {**LIMITS, **(limits or {})}
    if book is None or book.empty or not nav or nav <= 0:
        return {"checks": [], "metrics": {}, "book": book}
    b = _with_betas(book, betas or {})
    cash = pd.to_numeric(b["CASH AT RISK"], errors="coerce").fillna(0)
    checks, m = [], {}

    # Market risk — book beta and the QQQ tail
    m["book_beta"] = b["BETA $ DELTA"].sum() / nav
    base = bk.scenario_pnl(b, 0.0)
    m["tail10"] = bk.scenario_pnl(b, qqq_shock(b, -0.10)) - base
    m["tail20"] = bk.scenario_pnl(b, qqq_shock(b, -0.20)) - base
    tail_pct = -m["tail20"] / nav
    by_tkr = []
    for t, g in b.groupby("TICKER"):
        by_tkr.append((t, bk.scenario_pnl(g, qqq_shock(g, -0.20)) - bk.scenario_pnl(g, 0.0)))
    m["tail20_by_name"] = dict(by_tkr)
    worst = sorted(by_tkr, key=lambda x: x[1])[:3]
    m["beta_estimated"] = sorted(b.loc[b["BETA EST"], "TICKER"].unique().tolist())
    checks.append(_check("tail_qqq20", "LOSS IF QQQ −20%", tail_pct, L["tail_qqq20"],
                         _max_status(tail_pct, L["tail_qqq20"]),
                         f"${-m['tail20']:,.0f} · biggest: " +
                         ", ".join(f"{t} ${-v:,.0f}" for t, v in worst if v < 0)))
    checks.append(_check("book_beta", "BOOK BETA (× QQQ)", m["book_beta"], L["book_beta"],
                         _max_status(m["book_beta"], L["book_beta"]),
                         f"moves like {m['book_beta']:.2f}× QQQ · beta-weighted $ delta "
                         f"${b['BETA $ DELTA'].sum():,.0f}", fmt="x"))

    # Concentration — the manual's caps, on cash at risk
    by_name = cash.groupby(b["TICKER"]).sum() / nav
    by_sector = cash.groupby(b["SECTOR"]).sum() / nav
    by_bucket = cash.groupby(b["BUCKET"]).sum() / nav
    m.update(by_name=by_name.sort_values(ascending=False), by_sector=by_sector.sort_values(ascending=False),
             by_bucket=by_bucket)
    for key, label, s in (("max_name", "LARGEST NAME", by_name), ("max_sector", "LARGEST SECTOR", by_sector)):
        top = s.idxmax() if len(s) else "—"
        v = float(s.max()) if len(s) else 0.0
        over = [f"{n} {p:.0%}" for n, p in s.items() if p > L[key]]
        checks.append(_check(key, label, v, L[key], _max_status(v, L[key]),
                             f"{top} {v:.1%}" + (f" · over: {', '.join(over)}" if over else "")))
    pos_pct = cash / nav
    i_max = pos_pct.idxmax() if len(pos_pct) else None
    v = float(pos_pct.max()) if len(pos_pct) else 0.0
    checks.append(_check("max_trade", "LARGEST POSITION", v, L["max_trade"], _max_status(v, L["max_trade"]),
                         f"#{b.loc[i_max, 'ID']} {b.loc[i_max, 'TICKER']} ${cash[i_max]:,.0f}" if i_max is not None else "—"))
    spec = float(by_bucket.get("Speculative", 0.0))
    core = float(by_bucket.get("Core", 0.0))
    checks.append(_check("max_spec", "SPECULATIVE BUCKET", spec, L["max_spec"],
                         _max_status(spec, L["max_spec"]), f"{spec:.1%} of NAV"))
    checks.append(_check("min_core", "CORE BUCKET (MIN)", core, L["min_core"],
                         "breach" if core < L["min_core"] else ("warn" if core < L["min_core"] / WARN_AT else "ok"),
                         f"{core:.1%} of NAV"))

    # Stock inventory (held shares + stock legs of standalone covered calls)
    stock_val = 0.0
    for _, r in b.iterrows():
        px = r["SPOT"] if not bk._missing(r["SPOT"]) else (r["_PREM"] or 0)
        if r["_IS_STOCK"]:
            stock_val += px * r["CONTRACTS"]
        elif r["_IS_CC"] and r["_CC_STANDALONE"]:
            stock_val += px * 100 * r["CONTRACTS"]
    sv = stock_val / nav
    checks.append(_check("max_stock_inv", "STOCK INVENTORY", sv, L["max_stock_inv"],
                         _max_status(sv, L["max_stock_inv"]), f"${stock_val:,.0f}"))

    # No naked short calls: covered-call contracts need 100 held shares each
    shares = b[b["_IS_STOCK"]].groupby("TICKER")["CONTRACTS"].sum()
    naked = []
    for t, g in b[b["_IS_CC"]].groupby("TICKER"):
        need, have = float(g["CONTRACTS"].sum()) * 100, float(shares.get(t, 0))
        if need > have + 1e-6:
            naked.append(f"{t} {int(math.ceil((need - have) / 100))} uncovered")
    checks.append(_check("naked_calls", "NO NAKED CALLS", len(naked), 0,
                         "breach" if naked else "ok", ", ".join(naked) or "all covered", fmt="count"))

    # Drawdown from the NAV/unit high-water mark
    if npu and peak_npu:
        dd = max(0.0, 1 - npu / peak_npu)
        checks.append(_check("drawdown", "DRAWDOWN FROM PEAK", dd, L["dd_stop"],
                             "breach" if dd >= L["dd_stop"] else ("warn" if dd >= L["dd_warn"] else "ok"),
                             f"NAV/unit {npu:,.2f} vs peak {peak_npu:,.2f} · slow down at "
                             f"{L['dd_warn']:.0%}, stop adding risk at {L['dd_stop']:.0%}"))

    # Every short put still cash-secured (negative available cash = puts on margin).
    # Near-zero is normal under the 100%-invested mandate, so there's no amber zone.
    if available is not None:
        checks.append(_check("cash_secured", "PUTS CASH-SECURED", available, 0,
                             "breach" if available < 0 else "ok",
                             f"available cash ${available:,.0f}", fmt="usd"))

    # Earnings inside a short option's life (gap risk) — a warning, never a breach
    if events and "EARNINGS" in b.columns:
        ev = b[b["_IS_SHORT"] & ~b["_IS_STOCK"] & b["EARNINGS"].notna()]
        checks.append(_check("earnings", "SHORTS THROUGH EARNINGS", len(ev), 0,
                             "warn" if len(ev) else "ok",
                             ", ".join(f"{r.TICKER} {int(r.EARNINGS)}d" for r in ev.itertuples()) or "none",
                             fmt="count"))
    return {"checks": checks, "metrics": m, "book": b}


def trade_impact(before, after, nav, limits=None, new_id="NEW") -> dict:
    """What ONE new trade does, measured on the trade itself — its own size, its
    own name and sector — and whether it may be added.
    before / after = evaluate() without / with the trade (row ID == new_id).
    Each row's verdict (the first two FAIL the trade):
      NEW BREACH     — this trade pushes the measure over its limit
      ADDS TO BREACH — already over, and this trade makes it worse (concentration:
                       any increase; QQQ tail / book beta: more than the tolerance)
      ALREADY OVER   — already over, but this trade doesn't (materially) add to it
      WATCH          — within 15% of the limit after the trade
      OK"""
    L = {**LIMITS, **(limits or {})}
    m0, m1, b1 = before["metrics"], after["metrics"], after["book"]
    t = b1[b1["ID"].astype(str) == str(new_id)].iloc[0]
    tkr, sector, bucket = t["TICKER"], t["SECTOR"], t["BUCKET"]
    rows = []

    def add(label, v0, v1, lim, fmt="pct", contrib=None, cap_only=False, tol=0.0):
        if v1 > lim:
            if cap_only or v0 is None or v0 <= lim:
                verdict = "NEW BREACH"
            else:
                verdict = "ADDS TO BREACH" if v1 - v0 > tol else "ALREADY OVER"
        else:
            verdict = "WATCH" if v1 > WARN_AT * lim else "OK"
        f = {"pct": lambda v: f"{v:.1%}", "x": lambda v: f"{v:.2f}×", "usd": lambda v: f"${v:,.0f}"}[fmt]
        rows.append({"MEASURE": label,
                     "THIS TRADE": contrib if contrib is not None else f((v1 - v0) if v0 is not None else v1),
                     "BEFORE": f(v0) if v0 is not None else "—", "AFTER": f(v1),
                     "LIMIT": (f"≤ {lim:.0%}" if fmt == "pct" else f"≤ {lim:.2f}×" if fmt == "x" else "≥ $0"),
                     "VERDICT": verdict})

    # The trade on its own: position size vs the per-position cap
    add(f"POSITION SIZE ({tkr})", None, float(t["CASH AT RISK"]) / nav, L["max_trade"], cap_only=True,
        contrib=f"${float(t['CASH AT RISK']):,.0f}")
    # Its name and its sector — not "the largest", which can hide a smaller one
    for label, key, s0, s1 in ((f"NAME: {tkr}", "max_name", m0["by_name"], m1["by_name"]),
                               (f"SECTOR: {sector}", "max_sector", m0["by_sector"], m1["by_sector"])):
        k = tkr if key == "max_name" else sector
        add(label, float(s0.get(k, 0.0)), float(s1.get(k, 0.0)), L[key])
    if bucket == "Speculative":
        add("SPECULATIVE BUCKET", float(m0["by_bucket"].get(bucket, 0.0)),
            float(m1["by_bucket"].get(bucket, 0.0)), L["max_spec"])
    # Market risk the trade adds
    add("LOSS IF QQQ −20%", -m0["tail20"] / nav, -m1["tail20"] / nav, L["tail_qqq20"],
        contrib=f"+${m0['tail20'] - m1['tail20']:,.0f}", tol=L["tail_add_tol"])
    add(f"BOOK BETA ({tkr} β {t['BETA']:.2f}{'*' if t['BETA EST'] else ''})",
        m0["book_beta"], m1["book_beta"], L["book_beta"], fmt="x",
        contrib=f"{m1['book_beta'] - m0['book_beta']:+.2f}×", tol=L["beta_add_tol"])
    # Cash: still every put cash-secured afterwards?
    cash = {r["key"]: r["value"] for r in before["checks"]}, {r["key"]: r["value"] for r in after["checks"]}
    if "cash_secured" in cash[1]:
        a0, a1 = cash[0].get("cash_secured", 0.0), cash[1]["cash_secured"]
        rows.append({"MEASURE": "AVAILABLE CASH", "THIS TRADE": f"−${a0 - a1:,.0f}", "BEFORE": f"${a0:,.0f}",
                     "AFTER": f"${a1:,.0f}", "LIMIT": "≥ $0",
                     "VERDICT": ("NEW BREACH" if a1 < 0 <= a0 else "ADDS TO BREACH" if a1 < min(a0, 0) else "OK")})
    fails = [r for r in rows if r["VERDICT"] in ("NEW BREACH", "ADDS TO BREACH")]
    return {"rows": rows, "ticker": tkr, "passes": not fails,
            "fails": [f"{r['MEASURE']} {'' if r['BEFORE'] == '—' else r['BEFORE'] + ' → '}{r['AFTER']} "
                      f"(limit {r['LIMIT']})" for r in fails],
            "already_over": [f"{r['MEASURE']} ({r['THIS TRADE']})" for r in rows if r["VERDICT"] == "ALREADY OVER"],
            "earnings": None if bk._missing(t.get("EARNINGS")) else int(t["EARNINGS"])}


def worst_status(checks) -> str:
    return max((c["status"] for c in checks), key=STATUS_RANK.get, default="ok")


def fmt_value(c) -> str:
    v, f = c["value"], c["fmt"]
    if f == "x":
        return f"{v:.2f}×"
    if f == "count":
        return f"{int(v)}"
    if f == "usd":
        return f"${v:,.0f}"
    return f"{v:.1%}"


def fmt_limit(c) -> str:
    if c["key"] == "min_core":
        return f"≥ {c['limit']:.0%}"
    if c["fmt"] == "x":
        return f"≤ {c['limit']:.2f}×"
    if c["fmt"] in ("count", "usd"):
        return "0" if c["key"] != "cash_secured" else "≥ $0"
    return f"≤ {c['limit']:.0%}"


# ── History: was the book in breach, and for how long? ────────────────────────
def history(trades, closes, fund_snaps, betas, sector_map=None, limits=None, days=180) -> pd.DataFrame:
    """Re-run evaluate() on every snapshot day, using the positions open that day
    (from the trade log), that day's closes and the day's actual NAV.
    Options are priced with Black-Scholes at a realized-vol IV (no historical
    option quotes), so the beta/tail rows are estimates; the concentration caps
    and drawdown are exact. Returns one row per (date, check)."""
    if trades is None or trades.empty or fund_snaps is None or fund_snaps.empty or closes.empty:
        return pd.DataFrame()
    fs = fund_snaps.copy()
    fs["d"] = pd.to_datetime(fs["snap_date"]).dt.date
    fs["nav"] = pd.to_numeric(fs["nav"], errors="coerce")
    fs["npu"] = (pd.to_numeric(fs["nav_per_unit"], errors="coerce")
                 if "nav_per_unit" in fs.columns else np.nan)
    fs = fs.dropna(subset=["nav"]).sort_values("d").tail(days)
    fs["peak"] = fs["npu"].cummax()

    px = closes.sort_index().ffill()
    vol = (np.log(px / px.shift(1)).rolling(63, min_periods=15).std() * np.sqrt(252)).clip(0.25, 1.5) * 1.1

    T = trades.copy()
    T["_open"] = pd.to_datetime(T["DATE OPENED"], errors="coerce").dt.date
    T["_close"] = pd.to_datetime(T["DATE CLOSED"], errors="coerce").dt.date
    T["MANUAL MARK"] = None                       # today's broker marks don't apply to past days

    out = []
    for d, nav, npu, peak in fs[["d", "nav", "npu", "peak"]].itertuples(index=False):
        live = T[(T["_open"] <= d) & (T["_close"].isna() | (T["_close"] > d))]
        if live.empty:
            continue
        hist = px.loc[:d]
        if hist.empty:
            continue
        spots, ivs = hist.iloc[-1], vol.loc[:d].iloc[-1]

        def spot_fn(t):
            return float(spots.get(t, np.nan))

        def mark_fn(t, k, e, kind):
            s, iv = spot_fn(t), float(ivs.get(t, np.nan))
            iv = iv if not np.isnan(iv) else 0.5
            dte = (pd.Timestamp(e).date() - d).days
            return bk.bs_price(s, k, iv, max(dte, 0), kind=kind), iv

        b = bk.build_book(live, spot_fn, mark_fn, None, sector_map, today=d)
        res = evaluate(b, nav, betas, limits, npu=npu if npu == npu else None,
                       peak_npu=peak if peak == peak else None, events=False)
        for c in res["checks"]:
            out.append({"date": d, "key": c["key"], "label": c["label"],
                        "value": c["value"], "status": c["status"]})
    return pd.DataFrame(out)


def breach_summary(hist) -> pd.DataFrame:
    """Per check: days in breach / warning over the window, and the current streak."""
    if hist is None or hist.empty:
        return pd.DataFrame()
    rows = []
    for (key, label), g in hist.sort_values("date").groupby(["key", "label"], sort=False):
        st = g["status"].tolist()
        streak = 0
        for s in reversed(st):
            if s != "breach":
                break
            streak += 1
        breached = g[g["status"] == "breach"]["date"]
        rows.append({"LIMIT": label, "DAYS IN BREACH": int((g["status"] == "breach").sum()),
                     "DAYS IN WARNING": int((g["status"] == "warn").sum()), "OF DAYS": len(g),
                     "FIRST BREACH": breached.min() if len(breached) else None,
                     "IN BREACH NOW FOR": f"{streak} day(s)" if streak else "—"})
    return pd.DataFrame(rows).sort_values("DAYS IN BREACH", ascending=False)
