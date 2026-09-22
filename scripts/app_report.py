"""
In-app weekly report builder.

Returns the same 3-page report HTML as scripts/messi_report.py, but sourced from
the live app: snapshots from db.load_fund_snapshots() and the open book marked
with the app's own feed (shared.fetch_option_live / fetch_spot). The benchmark
uses the stored qqq_close column (no live yfinance needed), falling back to a
live QQQ fetch only if the column isn't populated.

Used by pages/7_Fund.py behind the "Generate weekly report" button.
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import messi_report as mr          # render_perf / render_bench / render_book / PAGE_WRAP
import shared                       # fetch_option_live / fetch_spot (the app's marking)


def _f(v, d=0.0):
    try:
        return float(v)
    except Exception:
        return d


def _positions(trades):
    """Reconstruct the open book as report rows, marked like the Portfolio page."""
    if trades is None or getattr(trades, "empty", True):
        return []
    open_t = trades[trades["STATUS"] == "OPEN"]
    rows = []
    for _, t in open_t.iterrows():
        strat = str(t.get("STRATEGY") or "")
        try:
            ctrs = int(_f(t.get("CONTRACTS")))
        except Exception:
            ctrs = 0
        prem = _f(t.get("PREMIUM / CREDIT")); tkr = str(t.get("TICKER") or "")
        mm = t.get("MANUAL MARK")
        try:
            mm = float(mm); mm = mm if mm > 0 else None
        except Exception:
            mm = None

        if strat == "Long Stock":
            price = mm if mm else shared.fetch_spot(tkr)
            price = price if (price == price) else None      # NaN guard
            pnl = (price - prem) * ctrs if (price is not None and prem > 0) else None
            rows.append(dict(ticker=tkr, position="Long Stock", expiry="", qty=f"{ctrs} sh",
                             entry=prem, mid=price, prem=None, pnl=pnl))
            continue

        is_short = strat not in ("Long Put (Hedge)", "Long Call")
        strike = _f(t.get("SHORT STRIKE")); expiry = str(t.get("EXPIRY") or "")
        opt = "put" if "Put" in strat else "call"
        if mm:
            mid = mm
        elif strike and expiry and expiry not in ("None", "nan", ""):
            m, _iv = shared.fetch_option_live(tkr, strike, expiry, opt)
            mid = m if m == m else None
        else:
            mid = None
        pnl = (((prem - mid) if is_short else (mid - prem)) * 100 * ctrs) if mid is not None else None
        pos = strat if strat in ("Covered Call", "Long Call", "Long Put (Hedge)") \
            else ("Short Put" if "Put" in strat else "Short Call")
        try:
            exp = datetime.date.fromisoformat(expiry).strftime("%m/%d/%y")
        except Exception:
            exp = expiry
        rows.append(dict(ticker=tkr, position=pos, expiry=exp, qty=f"{ctrs} cts",
                         entry=prem, mid=mid, prem=prem * 100 * ctrs, pnl=pnl))
    return rows


def build_report_html(fs, trades, fund_name):
    """fs = fund_snapshots DataFrame; trades = trade-log DataFrame. Returns HTML or None."""
    if fs is None or fs.empty or "snap_date" not in fs.columns:
        return None
    fs = fs.sort_values("snap_date").reset_index(drop=True)
    snaps = []
    for _, r in fs.iterrows():
        realized = _f(r.get("realized_pnl")); unreal = _f(r.get("unreal_pnl"))
        snaps.append(dict(date=str(r["snap_date"]), npu=_f(r["nav_per_unit"]), nav=_f(r["nav"]),
                          contrib=_f(r["contributed"]), realized=realized, unreal=unreal,
                          pl=realized + unreal))
    if len(snaps) < 2:
        return None
    dates = [s["date"] for s in snaps]; npu = [s["npu"] for s in snaps]
    pl = [s["pl"] for s in snaps]; last = snaps[-1]

    tgt = (datetime.date.fromisoformat(dates[-1]) - datetime.timedelta(days=7)).isoformat()
    lr = max((i for i, d in enumerate(dates) if d <= tgt), default=max(0, len(dates) - 2))
    week_ret = (last["npu"] / snaps[lr]["npu"] - 1) * 100
    week_pl = last["pl"] - snaps[lr]["pl"]
    cum_twr = last["npu"] - 100
    realized = last["realized"]

    positions = _positions(trades)
    open_unreal = sum(p["pnl"] for p in positions if p["pnl"] is not None)
    open_prem = sum(p["prem"] for p in positions if p["prem"] is not None)

    # benchmark: prefer the stored qqq_close column; else a live fetch; else skip
    qqq = None
    if "qqq_close" in fs.columns:
        qc = fs["qqq_close"].tolist()
        if all(v is not None and str(v) not in ("nan", "") for v in qc):
            try:
                q0 = float(qc[0]); qqq = [float(v) / q0 * 100 for v in qc]
            except Exception:
                qqq = None
    if qqq is None:
        try:
            qqq = mr.fetch_qqq(dates)
        except Exception:
            qqq = None

    wend = datetime.date.fromisoformat(dates[-1]).strftime("%b %d, %Y").replace(" 0", " ")
    pages = mr.render_perf(fund_name, wend, dates, snaps, lr, week_ret, week_pl, cum_twr,
                           last, realized, len(positions), pl)
    if qqq is not None:
        try:
            pages += mr.render_bench(fund_name, dates, npu, qqq, mr.benchmark_stats(npu, qqq, dates))
        except Exception:
            pass
    pages += mr.render_book(positions, open_unreal, open_prem, realized, week_pl, last)
    return mr.PAGE_WRAP.replace("%%PAGES%%", pages)
