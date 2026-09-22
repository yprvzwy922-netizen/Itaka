#!/usr/bin/env python3
"""
Weekly fund report generator (Messi / Itaka style).

Turns two inputs — the fund_snapshots history and the current open positions —
into the 3-page PDF (Performance · Benchmark vs QQQ · The Book). Same look and
math as the hand-built weekly reports. Self-contained: this one file is all you
need (plus numpy, yfinance, and Google Chrome).

INPUTS
------
1) snapshots CSV — exactly the columns from the Supabase query:
     snap_date,nav,units,nav_per_unit,contributed,realized_pnl,unreal_pnl
   run:  select snap_date,nav,units,nav_per_unit,contributed,realized_pnl,unreal_pnl
         from messi_fund_snapshots order by snap_date;   → Export CSV

2) positions CSV — transcribed from Portfolio → OPEN POSITIONS:
     ticker,position,expiry,qty,entry,current_mid,premium_dollars,current_pnl
   e.g.
     OUST,Long Stock (assigned),,1200 sh,40.00,35.05,,-5940
     OUST,Covered Call,10/16/26,12 cts,1.15,1.25,1380,-120
     ACN,Short Put,10/16/26,2 cts,10.04,15.00,2008,-992
   (premium_dollars blank for stock; current_pnl = the UNREAL PNL column.)

USAGE
-----
  python scripts/messi_report.py \
      --snapshots snaps.csv --positions positions.csv \
      --fund "Messi se toma una pesi" --week-ending 2026-09-25 \
      --out ~/Desktop/messi_week.pdf

Optional:
  --last-review YYYY-MM-DD   marker + week-start (default: snapshot ~7 days back)
  --realized-live N          cumulative realized incl. anything that settled
                             after the last snapshot (e.g. an option expiring on
                             report day); shown on the book page.
  --no-benchmark             skip page 2 if QQQ can't be fetched.
"""
import argparse, csv, math, os, subprocess, sys
from datetime import datetime, timedelta
from shutil import which

import numpy as np

GREEN="#00e676"; CYAN="#00c8ff"; ORANGE="#ff9900"; RED="#ff4444"; SOFTRED="#ff6b6b"


# ── data loading ──────────────────────────────────────────────────────────────
def load_snapshots(path):
    rows=[]
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if not (r.get("snap_date") or "").strip(): continue
            rows.append(dict(date=r["snap_date"].strip(), nav=float(r["nav"]),
                             npu=float(r["nav_per_unit"]), contrib=float(r["contributed"]),
                             realized=float(r["realized_pnl"]), unreal=float(r["unreal_pnl"])))
    rows.sort(key=lambda x: x["date"])
    for r in rows: r["pl"]=r["realized"]+r["unreal"]   # total P&L (deposit-neutral)
    return rows


def load_positions(path):
    out=[]
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if not (r.get("ticker") or "").strip(): continue
            def num(k):
                v=(r.get(k) or "").replace("$","").replace(",","").replace("~","").strip()
                try: return float(v)
                except ValueError: return None
            out.append(dict(ticker=r["ticker"].strip(), position=(r.get("position") or "").strip(),
                            expiry=(r.get("expiry") or "").strip(), qty=(r.get("qty") or "").strip(),
                            entry=num("entry"), mid=num("current_mid"),
                            prem=num("premium_dollars"), pnl=num("current_pnl")))
    return out


# ── stats ─────────────────────────────────────────────────────────────────────
def fetch_qqq(dates):
    import yfinance as yf
    d0=(datetime.fromisoformat(dates[0])-timedelta(days=4)).date().isoformat()
    d1=(datetime.fromisoformat(dates[-1])+timedelta(days=2)).date().isoformat()
    h=yf.Ticker("QQQ").history(start=d0, end=d1)
    cl={d.isoformat(): float(c) for d,c in zip(h.index.date, h["Close"])}
    miss=[d for d in dates if d not in cl]
    if miss: raise RuntimeError(f"QQQ close missing for {miss[:3]} (market-data gap)")
    q0=cl[dates[0]]
    return [cl[d]/q0*100 for d in dates]


def benchmark_stats(npu, qqq, dates):
    f=np.array(npu); q=np.array(qqq)
    fr=np.diff(f)/f[:-1]; qr=np.diff(q)/q[:-1]; n=len(fr)
    days=max((datetime.fromisoformat(dates[-1])-datetime.fromisoformat(dates[0])).days,1)
    ann=math.sqrt(365/(days/n)); mdd=lambda x:(np.array(x)/np.maximum.accumulate(x)-1).min()
    return dict(fund_ret=npu[-1]-100, qqq_ret=qqq[-1]-100,
                vol_f=fr.std(ddof=1)*ann*100, vol_q=qr.std(ddof=1)*ann*100,
                dd_f=mdd(f)*100, dd_q=mdd(q)*100,
                beta=np.cov(fr,qr)[0,1]/np.var(qr,ddof=1), corr=np.corrcoef(fr,qr)[0,1])


# ── formatting ────────────────────────────────────────────────────────────────
def money(v, signed=False):
    if v is None: return "—"
    s="+" if (signed and v>=0) else ("−" if v<0 else "")
    return f"{s}${abs(v):,.0f}"

def pct(v): return f"{'+' if v>=0 else '−'}{abs(v):.2f}%"


# ── svg ───────────────────────────────────────────────────────────────────────
def _xy(vals,x0,x1,ymin,ymax,ytop,ybot):
    N=len(vals); xs=[x0+(x1-x0)*i/(N-1) for i in range(N)]
    ys=[ybot-(v-ymin)/(ymax-ymin)*(ybot-ytop) for v in vals]; return xs,ys
def _yv(v,ymin,ymax,ytop,ybot): return ybot-(v-ymin)/(ymax-ymin)*(ybot-ytop)
def _pts(xs,ys): return " ".join(f"{x:.1f},{y:.1f}" for x,y in zip(xs,ys))
def _xlabels(dates,xs,y=325):
    n=len(dates); idx=sorted(set([0,n-1]+[round(i*(n-1)/5) for i in range(1,5)]))
    return "\n".join(f'<text x="{xs[i]:.1f}" y="{y}" fill="#7a7a7a" font-size="11" '
                     f'text-anchor="middle">{dates[i][5:7].lstrip("0")}/{dates[i][8:10].lstrip("0")}</text>'
                     for i in idx)

def svg_pl(pl, dates, lr):
    ymin=min(min(pl),0)-1000; ymax=max(pl)+max(2000,0.08*max(abs(max(pl)),1))
    xs,ys=_xy(pl,55,865,ymin,ymax,35,300); g=[]; step=10000 if ymax<52000 else 20000; k=0
    while k<=ymax:
        yy=_yv(k,ymin,ymax,35,300); base=(k==0)
        col="#333333" if base else "#1e1e1e"; dash=' stroke-dasharray="4 4"' if base else ''
        g.append(f'<line x1="55" y1="{yy:.1f}" x2="865" y2="{yy:.1f}" stroke="{col}" stroke-width="1"{dash}/>')
        g.append(f'<text x="48" y="{yy+4:.1f}" fill="#7a7a7a" font-size="11" text-anchor="end">${k//1000}k</text>'); k+=step
    area=_pts(xs,ys)+f" {xs[-1]:.1f},300 {xs[0]:.1f},300"
    return f'''<svg viewBox="0 0 900 350" width="100%" xmlns="http://www.w3.org/2000/svg">
{chr(10).join(g)}
<line x1="{xs[lr]:.1f}" y1="35" x2="{xs[lr]:.1f}" y2="300" stroke="#444444" stroke-width="1" stroke-dasharray="3 4"/>
<text x="{xs[lr]-5:.1f}" y="46" fill="#7a7a7a" font-size="9.5" text-anchor="end" letter-spacing="0.5">LAST REVIEW</text>
<polygon points="{area}" fill="{GREEN}" fill-opacity="0.07"/>
<polyline points="{_pts(xs,ys)}" fill="none" stroke="{GREEN}" stroke-width="2.5"/>
<circle cx="{xs[lr]:.1f}" cy="{ys[lr]:.1f}" r="4" fill="#0d0d0d" stroke="{CYAN}" stroke-width="2"/>
<circle cx="{xs[-1]:.1f}" cy="{ys[-1]:.1f}" r="5" fill="{GREEN}"/>
<text x="865" y="{ys[-1]-9:.1f}" fill="{GREEN}" font-size="13" font-weight="700" text-anchor="end">{money(pl[-1],signed=True)}</text>
{_xlabels(dates,xs)}</svg>'''

def svg_bench(npu,qqq,dates):
    lo=min(min(npu),min(qqq)); hi=max(max(npu),max(qqq))
    ymin=math.floor(lo)-0.5; ymax=math.ceil(hi)+0.5
    fx,fy=_xy(npu,60,865,ymin,ymax,35,300); qx,qy=_xy(qqq,60,865,ymin,ymax,35,300); g=[]
    k=math.ceil(ymin)
    while k<=ymax:
        if (k-math.ceil(ymin))%2==0:
            yy=_yv(k,ymin,ymax,35,300); base=(k==100)
            col="#333333" if base else "#1e1e1e"; dash=' stroke-dasharray="4 4"' if base else ''
            g.append(f'<line x1="60" y1="{yy:.1f}" x2="865" y2="{yy:.1f}" stroke="{col}" stroke-width="1"{dash}/>')
            g.append(f'<text x="52" y="{yy+4:.1f}" fill="#7a7a7a" font-size="11" text-anchor="end">{k}</text>')
        k+=1
    return f'''<svg viewBox="0 0 900 350" width="100%" xmlns="http://www.w3.org/2000/svg">
{chr(10).join(g)}
<polyline points="{_pts(qx,qy)}" fill="none" stroke="{ORANGE}" stroke-width="2"/>
<polyline points="{_pts(fx,fy)}" fill="none" stroke="{CYAN}" stroke-width="2.5"/>
<circle cx="865" cy="{fy[-1]:.1f}" r="5" fill="{CYAN}"/><circle cx="865" cy="{qy[-1]:.1f}" r="5" fill="{ORANGE}"/>
<text x="858" y="{fy[-1]-4:.1f}" fill="{CYAN}" font-size="12" font-weight="700" text-anchor="end">{npu[-1]:.2f}</text>
<text x="858" y="{qy[-1]+14:.1f}" fill="{ORANGE}" font-size="12" font-weight="700" text-anchor="end">{qqq[-1]:.2f}</text>
{_xlabels(dates,fx)}</svg>'''


# ── pages ─────────────────────────────────────────────────────────────────────
def render_perf(fund, wend, dates, snaps, lr, week_ret, week_pl, cum_twr, last, realized, npos, pl):
    wc = GREEN if week_ret>=0 else SOFTRED
    navd = money(week_pl, signed=True)
    return f'''<section class="page">
  <div class="brandbar"><div><div class="fund">{fund}</div>
    <div class="sub">Portfolio Update · Week ending {wend}</div></div><div class="tag">CONFIDENTIAL</div></div>
  <div class="hero"><div class="twr" style="color:{wc};">{pct(week_ret)}</div>
    <div class="twrlab">Return this week<b>NAV/unit {snaps[lr]["npu"]:.2f} → {last["npu"]:.2f}</b></div>
    <div class="cum"><div class="n">{pct(cum_twr)}</div><div class="l">Cumulative TWR since inception</div></div></div>
  <div class="kpis">
    <div class="kpi"><div class="l">Current NAV</div><div class="v">${last["nav"]:,.0f}</div><div class="d {"pos" if week_pl>=0 else "neg"}">{navd} this week</div></div>
    <div class="kpi amber"><div class="l">Net Capital In</div><div class="v">${last["contrib"]:,.0f}</div><div class="d">contributed</div></div>
    <div class="kpi green"><div class="l">Total P&amp;L</div><div class="v pos">{money(last["pl"],signed=True)}</div><div class="d pos">+{last["pl"]/last["contrib"]*100:.1f}% on capital</div></div>
    <div class="kpi"><div class="l">NAV / Unit</div><div class="v">${last["npu"]:.2f}</div><div class="d pos">{pct(cum_twr)} vs 100</div></div></div>
  <div class="kpis" style="margin-top:12px;">
    <div class="kpi {"green" if week_pl>=0 else "red"}"><div class="l">Week P&amp;L</div><div class="v {"pos" if week_pl>=0 else "neg"}">{money(week_pl,signed=True)}</div><div class="d">{dates[lr]} → {dates[-1]}</div></div>
    <div class="kpi green"><div class="l">Realized (Cum.)</div><div class="v pos">${realized:,.0f}</div><div class="d">booked</div></div>
    <div class="kpi {"red" if last["unreal"]<0 else "green"}"><div class="l">Unrealized</div><div class="v {"neg" if last["unreal"]<0 else "pos"}">{money(last["unreal"],signed=True)}</div><div class="d">open marks</div></div>
    <div class="kpi"><div class="l">Open Positions</div><div class="v">{npos}</div><div class="d">from the book</div></div></div>
  <div class="charttitle">Cumulative P&amp;L ($) <span>— realized + unrealized, by daily snapshot</span></div>
  <div class="chartwrap">{svg_pl(pl,dates,lr)}</div>
  <div class="foot">{fund} · Prepared {datetime.today().date().isoformat()} · Performance from daily NAV snapshots. Preliminary — not an audited return.</div>
</section>'''

def render_bench(fund, dates, npu, qqq, bs):
    out=bs["fund_ret"]-bs["qqq_ret"]
    return f'''<section class="page">
  <div class="brandbar"><div><div class="fund">Fund vs Benchmark</div>
    <div class="sub">{fund} vs Nasdaq-100 (QQQ) · {dates[0]} → {dates[-1]}</div></div><div class="tag">BENCHMARK</div></div>
  <div class="hero"><div class="twr" style="color:{GREEN if out>=0 else SOFTRED};">{pct(out)}</div>
    <div class="twrlab">{"Ahead of" if out>=0 else "Behind"} QQQ<b>over the tracked window</b></div>
    <div class="cum" style="display:flex; gap:26px;">
      <div><div class="n" style="color:{CYAN};">{pct(bs["fund_ret"])}</div><div class="l">Fund (NAV/unit)</div></div>
      <div><div class="n" style="color:{ORANGE};">{pct(bs["qqq_ret"])}</div><div class="l">QQQ (indexed)</div></div></div></div>
  <div class="charttitle">Fund vs Nasdaq-100 <span>— indexed to 100 at inception</span></div>
  <div class="legend"><span><i style="background:{CYAN};"></i>FUND (NAV/unit)</span><span><i style="background:{ORANGE};"></i>QQQ</span></div>
  <div class="chartwrap">{svg_bench(npu,qqq,dates)}</div>
  <div class="bcmp">
    <div class="bt"><div class="l">Total Return</div>
      <div class="row"><span class="k">Fund</span><span class="fundv">{pct(bs["fund_ret"])}</span></div>
      <div class="row"><span class="k">QQQ</span><span class="qqqv">{pct(bs["qqq_ret"])}</span></div>
      <div class="subt pos">{pct(out)} vs QQQ</div></div>
    <div class="bt"><div class="l">Ann. Volatility</div>
      <div class="row"><span class="k">Fund</span><span class="fundv">{bs["vol_f"]:.1f}%</span></div>
      <div class="row"><span class="k">QQQ</span><span class="qqqv">{bs["vol_q"]:.1f}%</span></div>
      <div class="subt pos">~{bs["vol_f"]/bs["vol_q"]*100:.0f}% of QQQ's</div></div>
    <div class="bt"><div class="l">Max Drawdown</div>
      <div class="row"><span class="k">Fund</span><span class="fundv">{bs["dd_f"]:.1f}%</span></div>
      <div class="row"><span class="k">QQQ</span><span class="qqqv">{bs["dd_q"]:.1f}%</span></div>
      <div class="subt pos">shallower than QQQ</div></div>
    <div class="bt"><div class="l">Beta to QQQ</div>
      <div class="solo">{bs["beta"]:.2f}</div>
      <div class="subt">correlation {bs["corr"]:.2f} — low market sensitivity</div></div></div>
  <div class="cap" style="color:#9a9a9a;">Fund line is NAV/unit; QQQ is the Nasdaq-100 indexed to 100 at inception. The
    strategy gives up upside in strong rallies (capped by the short options) and cushions selloffs — carrying the return
    at roughly a {bs["beta"]:.2f} beta and {bs["vol_f"]/bs["vol_q"]*100:.0f}% of QQQ's volatility. Judge over full cycles.</div>
  <div class="foot">Benchmark = Invesco QQQ (Nasdaq-100), total price return, indexed to 100 at inception. Risk stats from
    snapshot-interval returns — indicative, not an annualized track record.</div>
</section>'''

def render_book(positions, open_unreal, open_prem, realized, week_pl, last):
    rows=[]
    for p in positions:
        entry=f"${p['entry']:.2f}" if p['entry'] is not None else "—"
        mid=f"${p['mid']:.2f}" if p['mid'] is not None else "—"
        prem=f"${p['prem']:,.0f}" if p['prem'] is not None else "—"
        cls="pos" if (p["pnl"] or 0)>=0 else "neg"
        pnl=money(p["pnl"],signed=True) if p["pnl"] is not None else "—"
        rows.append(f'<tr><td class="l tk">{p["ticker"]}</td><td class="l">{p["position"]}</td>'
                    f'<td>{p["expiry"] or "—"}</td><td>{p["qty"]}</td><td>{entry}</td><td>{mid}</td>'
                    f'<td>{prem}</td><td class="{cls}">{pnl}</td></tr>')
    return f'''<section class="page">
  <div class="brandbar"><div><div class="fund">The Book</div>
    <div class="sub">Holdings &amp; current P&amp;L</div></div><div class="tag">Page 3 / 3</div></div>
  <table><thead><tr><th class="l">Ticker</th><th class="l">Position</th><th>Expiry</th><th>Qty</th>
    <th>Entry</th><th>Cur. Mid</th><th>Prem $</th><th>Current P&amp;L</th></tr></thead><tbody>
    {chr(10).join(rows)}
    <tr class="tot"><td class="l">OPEN TOTAL</td><td class="l">{len(positions)} positions</td><td>—</td><td>—</td><td>—</td><td>—</td><td>${open_prem:,.0f}</td><td class="{"pos" if open_unreal>=0 else "neg"}">{money(open_unreal,signed=True)}</td></tr>
    <tr class="realized"><td class="l">REALIZED (INCEPTION)</td><td class="l" colspan="6">Cumulative booked P&amp;L</td><td class="pos">${realized:,.0f}</td></tr>
  </tbody></table>
  <div class="notes">
    <div class="note"><div class="h">Positioning</div><p><b>{len(positions)} open positions</b>, <b>${open_prem:,.0f}</b>
      premium at risk. Open marks total <b>{money(open_unreal,signed=True)}</b>. Reconcile against the broker before acting.</p></div>
    <div class="note"><div class="h">Week P&amp;L</div><p>Net <b>{money(week_pl,signed=True)}</b> this week. Cumulative realized
      <b>${realized:,.0f}</b>; total P&amp;L <b>{money(last["pl"],signed=True)}</b>, NAV/unit <b>${last["npu"]:.2f}</b>.</p></div>
  </div>
  <div class="foot">Decision-support summary — not an offer or solicitation. Marks are live-feed prices; reconcile with the
    broker. Past performance does not guarantee future results.</div>
</section>'''


PAGE_WRAP='''<!doctype html><html><head><meta charset="utf-8"><style>
@page { size: Letter; margin: 0; }
* { margin:0; padding:0; box-sizing:border-box; -webkit-print-color-adjust:exact; print-color-adjust:exact; }
html,body { background:#0a0a0a; color:#cccccc; font-family:"IBM Plex Mono","SFMono-Regular",Menlo,Consolas,monospace; }
.page { width:8.5in; height:11in; padding:0.55in 0.6in; position:relative; overflow:hidden; page-break-after:always; }
.page:last-child { page-break-after:auto; }
.brandbar { display:flex; justify-content:space-between; align-items:flex-end; border-bottom:2px solid #00c8ff; padding-bottom:10px; }
.fund { font-size:23px; font-weight:700; color:#fff; letter-spacing:0.5px; }
.sub { font-size:11px; color:#7a7a7a; margin-top:3px; letter-spacing:1px; text-transform:uppercase; }
.tag { font-size:10px; color:#00c8ff; border:1px solid #00c8ff; padding:4px 9px; letter-spacing:1px; }
.hero { margin-top:24px; display:flex; align-items:baseline; gap:16px; }
.hero .twr { font-size:60px; font-weight:700; line-height:1; }
.hero .twrlab { font-size:12px; color:#8a8a8a; text-transform:uppercase; letter-spacing:1px; }
.hero .twrlab b { color:#ccc; display:block; font-size:15px; margin-top:2px; }
.hero .cum { margin-left:auto; text-align:right; }
.hero .cum .n { font-size:30px; font-weight:700; color:#00c8ff; }
.hero .cum .l { font-size:10px; color:#7a7a7a; text-transform:uppercase; letter-spacing:1px; }
.kpis { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-top:22px; }
.kpi { background:#141414; border:1px solid #1e1e1e; border-left:3px solid #00c8ff; padding:12px 14px; }
.kpi .l { font-size:9.5px; color:#7a7a7a; text-transform:uppercase; letter-spacing:0.8px; }
.kpi .v { font-size:21px; color:#fff; margin-top:6px; font-weight:600; }
.kpi .d { font-size:10px; margin-top:3px; }
.pos { color:#00e676; } .neg { color:#ff4444; }
.kpi.green { border-left-color:#00e676; } .kpi.amber { border-left-color:#ff9900; } .kpi.red { border-left-color:#ff4444; }
.charttitle { margin-top:26px; font-size:12px; color:#ccc; text-transform:uppercase; letter-spacing:1px; }
.charttitle span { color:#7a7a7a; text-transform:none; letter-spacing:0; }
.chartwrap { background:#0d0d0d; border:1px solid #1e1e1e; margin-top:10px; padding:12px 8px 4px; }
.cap { font-size:10px; color:#7a7a7a; margin-top:10px; line-height:1.5; }
.legend { display:flex; gap:20px; margin:2px 0 4px 12px; font-size:10.5px; }
.legend i { display:inline-block; width:16px; height:3px; vertical-align:middle; margin-right:6px; }
table { width:100%; border-collapse:collapse; margin-top:14px; font-size:11px; }
th { text-align:right; font-size:9px; color:#7a7a7a; text-transform:uppercase; letter-spacing:0.5px; padding:7px 8px; border-bottom:1px solid #2a2a2a; }
th.l, td.l { text-align:left; }
td { text-align:right; padding:7.5px 8px; border-bottom:1px solid #171717; color:#ddd; }
tr.tot td { border-top:1px solid #00c8ff; border-bottom:none; font-weight:700; color:#fff; padding-top:10px; }
tr.realized td { background:#141414; color:#bbb; font-size:11px; }
.tk { color:#00c8ff; font-weight:600; }
.bcmp { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-top:18px; }
.bt { background:#141414; border:1px solid #1e1e1e; padding:12px 14px; }
.bt .l { font-size:9.5px; color:#7a7a7a; text-transform:uppercase; letter-spacing:0.8px; margin-bottom:8px; }
.bt .row { display:flex; justify-content:space-between; align-items:baseline; margin-top:5px; }
.bt .row .k { color:#8a8a8a; font-size:10px; }
.bt .fundv { color:#00c8ff; font-weight:700; font-size:15px; } .bt .qqqv { color:#ff9900; font-weight:700; font-size:15px; }
.bt .solo { color:#fff; font-weight:700; font-size:22px; } .bt .subt { font-size:9.5px; color:#7a7a7a; margin-top:6px; }
.notes { margin-top:16px; display:grid; grid-template-columns:1fr 1fr; gap:12px; }
.note { background:#141414; border:1px solid #1e1e1e; padding:12px 15px; }
.note .h { font-size:10px; color:#00c8ff; text-transform:uppercase; letter-spacing:0.8px; margin-bottom:6px; }
.note p { font-size:10.5px; line-height:1.55; color:#bbb; } .note p b { color:#fff; }
.foot { position:absolute; bottom:0.45in; left:0.6in; right:0.6in; font-size:8.5px; color:#5a5a5a; border-top:1px solid #1e1e1e; padding-top:8px; line-height:1.5; }
</style></head><body>%%PAGES%%</body></html>'''


def find_chrome():
    for c in ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              "google-chrome","chromium","chromium-browser",
              "/Applications/Chromium.app/Contents/MacOS/Chromium"]:
        if os.path.isfile(c) or which(c): return c
    raise RuntimeError("Google Chrome not found — install it for HTML→PDF.")


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--snapshots", required=True); ap.add_argument("--positions", required=True)
    ap.add_argument("--fund", default="Messi se toma una pesi")
    ap.add_argument("--week-ending", required=True); ap.add_argument("--last-review", default=None)
    ap.add_argument("--realized-live", type=float, default=None)
    ap.add_argument("--out", required=True); ap.add_argument("--no-benchmark", action="store_true")
    a=ap.parse_args()

    snaps=load_snapshots(a.snapshots)
    if len(snaps)<2: sys.exit("Need at least 2 snapshots.")
    dates=[s["date"] for s in snaps]; npu=[s["npu"] for s in snaps]; pl=[s["pl"] for s in snaps]; last=snaps[-1]

    if a.last_review and a.last_review in dates: lr=dates.index(a.last_review)
    else:
        target=(datetime.fromisoformat(dates[-1])-timedelta(days=7)).date().isoformat()
        lr=max((i for i,d in enumerate(dates) if d<=target), default=max(0,len(dates)-2))

    week_ret=(last["npu"]/snaps[lr]["npu"]-1)*100; week_pl=last["pl"]-snaps[lr]["pl"]; cum_twr=last["npu"]-100
    positions=load_positions(a.positions)
    open_unreal=sum(p["pnl"] for p in positions if p["pnl"] is not None)
    open_prem=sum(p["prem"] for p in positions if p["prem"] is not None)
    realized=a.realized_live if a.realized_live is not None else last["realized"]

    pages=render_perf(a.fund,a.week_ending,dates,snaps,lr,week_ret,week_pl,cum_twr,last,realized,len(positions),pl)
    if not a.no_benchmark:
        try:
            qqq=fetch_qqq(dates); pages+=render_bench(a.fund,dates,npu,qqq,benchmark_stats(npu,qqq,dates))
        except Exception as e:
            print(f"[benchmark skipped] {e}", file=sys.stderr)
    pages+=render_book(positions,open_unreal,open_prem,realized,week_pl,last)

    out=os.path.abspath(os.path.expanduser(a.out))
    tmp=os.path.join(os.path.dirname(out) or ".", ".messi_report.html")
    with open(tmp,"w") as f: f.write(PAGE_WRAP.replace("%%PAGES%%",pages))
    subprocess.run([find_chrome(),"--headless=new","--disable-gpu","--no-pdf-header-footer",
                    f"--print-to-pdf={out}", f"file://{tmp}"], check=True, capture_output=True)
    os.remove(tmp); print(f"wrote {out}")


if __name__=="__main__":
    main()
