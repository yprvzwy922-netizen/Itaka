# Weekly Report — How To Generate It

This produces the 3-page PDF (Performance · Benchmark vs QQQ · The Book) from two
inputs. Anyone with the repo, Python, and Google Chrome can run it — or hand this
file plus the two inputs to Claude and it will do the whole thing.

**Generator:** [`scripts/messi_report.py`](scripts/messi_report.py) (self-contained).

---

## What you need each week (2 inputs)

### 1. `snapshots.csv` — the NAV history
In **Supabase → SQL Editor**, run (use `messi_` prefix for Messi, no prefix for Itaka):

```sql
select snap_date, nav, units, nav_per_unit, contributed, realized_pnl, unreal_pnl
from messi_fund_snapshots
order by snap_date;
```
Click **Export → CSV**. That file *is* `snapshots.csv` — columns must be exactly:
`snap_date,nav,units,nav_per_unit,contributed,realized_pnl,unreal_pnl`

> Run the **MESSI snapshot GitHub Action** for the week's trading days first, so
> the latest points exist.

### 2. `positions.csv` — the current book
Open the app → **Portfolio & Risk** → the **OPEN POSITIONS** table, and transcribe
each row into a CSV with these columns:

```
ticker,position,expiry,qty,entry,current_mid,premium_dollars,current_pnl
OUST,Long Stock (assigned),,1200 sh,40.00,35.05,,-5940
OUST,Covered Call,10/16/26,12 cts,1.15,1.25,1380,-120
ACN,Short Put,10/16/26,2 cts,10.04,15.00,2008,-992
```
- **position**: `Short Put` / `Covered Call` / `Long Stock (assigned)` / `Long Call` …
  (a short call = negative DELTA in the app; a short put = positive DELTA)
- **entry** = PREM RECEIVED column (for stock, the cost basis / share)
- **current_mid** = CURRENT MID (for stock, the current share price)
- **premium_dollars** = TOTAL $ PREM RECEIVED (blank for stock)
- **current_pnl** = UNREAL PNL column
- Sanity check: the `current_pnl` values should **sum to the app's UNREAL PNL (MID)** total.

---

## Run it

```bash
python scripts/messi_report.py \
  --snapshots snapshots.csv \
  --positions positions.csv \
  --fund "Messi se toma una pesi" \
  --week-ending "Sep 25, 2026" \
  --out ~/Desktop/messi_week.pdf
```

Options:
- `--last-review 2026-09-18` — the previous report's end date (sets the chart's
  "last review" marker + the week-over-week comparison). Defaults to the snapshot
  ~7 days back.
- `--realized-live 48983` — if an option **expired/settled on report day** (after
  the last snapshot captured it), pass the updated cumulative realized so the book
  page shows it. Otherwise omit.
- `--no-benchmark` — skip page 2 if QQQ data can't be fetched.

**Prerequisites:** `pip install numpy yfinance` and Google Chrome installed
(used to render HTML → PDF). The benchmark page pulls real QQQ closes via yfinance.

---

## Giving it to Claude (easiest path)

Hand Claude this repo (or just `scripts/messi_report.py`), the **snapshot CSV**, and
a **screenshot of the OPEN POSITIONS table**, and paste:

> Generate this week's fund report. Use `scripts/messi_report.py`.
> - `snapshots.csv` is attached (the fund_snapshots export).
> - Transcribe the OPEN POSITIONS screenshot into `positions.csv` with columns
>   `ticker,position,expiry,qty,entry,current_mid,premium_dollars,current_pnl`
>   (entry = PREM RECEIVED, current_mid = CURRENT MID, premium_dollars = TOTAL $
>   PREM RECEIVED, current_pnl = UNREAL PNL; short call = negative delta).
> - Confirm the positions' current_pnl sums to the app's UNREAL PNL (MID) total.
> - Run the script with `--fund "Messi se toma una pesi"`, `--week-ending <date>`,
>   `--last-review <prev report end>`, and `--realized-live <value>` if an option
>   settled on report day. Output to my Desktop, then send me the PDF.

Claude will read the screenshot, build `positions.csv`, run the generator, sanity-
check the totals, and hand back the PDF.

---

## Notes
- The chart y-axes and the "last review" marker auto-scale — no hand-tuning.
- **Timing:** performance uses the daily snapshots; the book uses your live marks.
  If an option settles on report day, the snapshot may lag the live book by that
  amount — `--realized-live` reconciles the realized figure.
- The narrative notes on the pages are intentionally factual/auto-generated. For a
  richer write-up (e.g. "the OUST wheel is turning"), edit the generated PDF's
  source or ask Claude to add color to the notes.
- Same script works for **Itaka**: `--fund "ITAKA FUND"` and the un-prefixed
  `fund_snapshots` query.
