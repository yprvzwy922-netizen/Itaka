#!/usr/bin/env python3
"""
Weekly report emailer (runs in GitHub Actions).

Pulls fund_snapshots + trades from Supabase, marks the open book with the same
Massive→Yahoo ladder as the app, generates the 3-page PDF via messi_report.py,
and emails it via Gmail SMTP. No screenshots — the book is reconstructed.

Env:
  SUPABASE_URL, SUPABASE_KEY        (required)
  TABLE_PREFIX                      (e.g. "messi_"; empty for Itaka)
  MASSIVE_API_KEY                   (optional; yfinance fallback)
  FUND_NAME                         (default "Messi se toma una pesi")
  GMAIL_USER, GMAIL_APP_PASSWORD    (required to send)
  EMAIL_TO                          (default: GMAIL_USER)
"""
import csv, datetime, os, smtplib, ssl, subprocess, sys
from email.message import EmailMessage
from zoneinfo import ZoneInfo

import requests
import yfinance as yf

URL=os.environ["SUPABASE_URL"].rstrip("/"); KEY=os.environ["SUPABASE_KEY"]
PREFIX=os.environ.get("TABLE_PREFIX",""); MASSIVE_KEY=os.environ.get("MASSIVE_API_KEY","")
FUND=os.environ.get("FUND_NAME","Messi se toma una pesi")
HDRS={"apikey":KEY,"Authorization":f"Bearer {KEY}"}
HERE=os.path.dirname(os.path.abspath(__file__))

def rest(table, params=None):
    r=requests.get(f"{URL}/rest/v1/{PREFIX}{table}", headers=HDRS, params=params, timeout=30)
    r.raise_for_status(); return r.json()

# ── marking (mirrors scripts/daily_snapshot.py) ───────────────────────────────
_now=datetime.datetime.now(ZoneInfo("America/New_York"))
US_RTH=_now.weekday()<5 and datetime.time(9,30)<=_now.time()<datetime.time(16,0)
_chain={}
def massive_mid(tkr,strike,expiry,opt_type):
    if not MASSIVE_KEY: return None
    ck=(tkr,expiry,opt_type)
    if ck not in _chain:
        m={}
        try:
            r=requests.get(f"https://api.massive.com/v3/snapshot/options/{tkr.upper()}",
                params={"expiration_date":expiry,"contract_type":opt_type,"limit":250,"apiKey":MASSIVE_KEY},timeout=10)
            r.raise_for_status()
            for c in r.json().get("results",[]):
                k=(c.get("details") or {}).get("strike_price"); q=c.get("last_quote") or {}; day=c.get("day") or {}
                bid=float(q.get("bid") or 0); ask=float(q.get("ask") or 0); close=float(day.get("close") or 0)
                mid=(bid+ask)/2 if (bid>0 and ask>0) else (close if close>0 else None)
                if k is not None and mid: m[round(float(k),2)]=mid
        except Exception: pass
        _chain[ck]=m
    return _chain[ck].get(round(float(strike),2))
def yahoo_mid(tkr,strike,expiry,opt_type):
    try:
        raw=yf.Ticker(tkr).option_chain(expiry); chain=raw.puts if opt_type=="put" else raw.calls
        if chain is None or chain.empty: return None
        chain=chain.copy(); chain["dist"]=(chain["strike"]-strike).abs()
        row=chain.loc[chain["dist"].idxmin()]
        if float(row["dist"])>max(0.015*strike,0.50): return None
        bid,ask=float(row["bid"]),float(row["ask"])
        return (bid+ask)/2 if (bid>0 and ask>0) else None
    except Exception: return None
def mark_mid(tkr,strike,expiry,opt_type):
    if US_RTH: return yahoo_mid(tkr,strike,expiry,opt_type) or massive_mid(tkr,strike,expiry,opt_type)
    return massive_mid(tkr,strike,expiry,opt_type) or yahoo_mid(tkr,strike,expiry,opt_type)
def stock_price(tkr):
    try:
        h=yf.Ticker(tkr).history(period="2d")
        return float(h["Close"].iloc[-1]) if not h.empty else None
    except Exception: return None

def fmt_exp(e):
    try: return datetime.date.fromisoformat(str(e)).strftime("%m/%d/%y")
    except Exception: return ""

# ── build the two CSV inputs ──────────────────────────────────────────────────
def write_snapshots(path):
    rows=rest("fund_snapshots", {"select":"*","order":"snap_date"})
    cols=["snap_date","nav","units","nav_per_unit","contributed","realized_pnl","unreal_pnl"]
    with open(path,"w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=cols); w.writeheader()
        for r in rows: w.writerow({c:r.get(c) for c in cols})
    return len(rows)

def write_positions(path):
    trades=rest("trades",{"select":"*"})
    open_t=[t for t in trades if t.get("status")=="OPEN"]
    rows=[]
    for t in open_t:
        strat=str(t.get("strategy") or ""); ctrs=int(t.get("contracts") or 0); prem=float(t.get("premium") or 0)
        tkr=t.get("ticker"); mmark=t.get("manual_mark"); mmark=float(mmark) if mmark not in (None,"",0) else None
        if strat=="Long Stock":
            price=mmark if (mmark and prem>0) else stock_price(tkr)
            pnl=(price-prem)*ctrs if (price and prem>0) else None
            rows.append(dict(ticker=tkr,position="Long Stock",expiry="",qty=f"{ctrs} sh",
                entry=f"{prem:.2f}",current_mid=(f"{price:.2f}" if price else ""),premium_dollars="",
                current_pnl=(f"{pnl:.0f}" if pnl is not None else ""))); continue
        is_short = strat not in ("Long Put (Hedge)","Long Call")
        strike=float(t.get("short_strike") or 0); expiry=t.get("expiry")
        opt_type="put" if "Put" in strat else "call"
        mid = mmark if mmark else (mark_mid(tkr,strike,expiry,opt_type) if (strike and expiry) else None)
        pnl=(((prem-mid) if is_short else (mid-prem))*100*ctrs) if mid is not None else None
        pos = strat if strat in ("Covered Call","Long Call","Long Put (Hedge)") else ("Short Put" if "Put" in strat else "Short Call")
        rows.append(dict(ticker=tkr,position=pos,expiry=fmt_exp(expiry),qty=f"{ctrs} cts",
            entry=f"{prem:.2f}",current_mid=(f"{mid:.2f}" if mid is not None else ""),
            premium_dollars=f"{prem*100*ctrs:.0f}",current_pnl=(f"{pnl:.0f}" if pnl is not None else "")))
    cols=["ticker","position","expiry","qty","entry","current_mid","premium_dollars","current_pnl"]
    with open(path,"w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=cols); w.writeheader()
        for r in rows: w.writerow(r)
    return len(rows)

# ── email ─────────────────────────────────────────────────────────────────────
def send_email(pdf, today):
    user=os.environ["GMAIL_USER"]; pw=os.environ["GMAIL_APP_PASSWORD"].replace(" ","")
    to=os.environ.get("EMAIL_TO") or user
    msg=EmailMessage()
    msg["Subject"]=f"{FUND} — Weekly Report ({today.isoformat()})"
    msg["From"]=user; msg["To"]=to
    msg.set_content(f"Automated weekly report for {FUND}, week ending {today.isoformat()}.\n\n"
                    "Positions are reconstructed from the trade log and marked with a live data feed, "
                    "so they can differ slightly from the app at the moment you open it. "
                    "Reconcile with the broker before acting.\n")
    with open(pdf,"rb") as f:
        msg.add_attachment(f.read(),maintype="application",subtype="pdf",filename=os.path.basename(pdf))
    with smtplib.SMTP("smtp.gmail.com",587) as s:
        s.starttls(context=ssl.create_default_context()); s.login(user,pw); s.send_message(msg)

def main():
    snaps=os.path.join(HERE,"_snapshots.csv"); poss=os.path.join(HERE,"_positions.csv")
    slug="".join(ch for ch in FUND.lower() if ch.isalnum())[:12] or "fund"
    pdf=os.path.join(HERE,f"{slug}_weekly.pdf")
    n=write_snapshots(snaps); k=write_positions(poss)
    if n<2: sys.exit("Not enough snapshots to build a report.")
    print(f"snapshots={n} positions={k}")
    today=datetime.date.today()
    subprocess.run([sys.executable, os.path.join(HERE,"messi_report.py"),
        "--snapshots",snaps,"--positions",poss,"--fund",FUND,
        "--week-ending",today.strftime("%b %d, %Y").replace(" 0"," "),
        "--out",pdf], check=True)
    send_email(pdf, today)
    print(f"emailed {pdf} -> {os.environ.get('EMAIL_TO') or os.environ['GMAIL_USER']}")

if __name__=="__main__": main()
