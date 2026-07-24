-- ITAKA FUND — Supabase schema (single-beneficiary put-selling tracker)
-- Run this once in the new Supabase project: SQL Editor -> paste -> Run.
-- Isolated from the original fund app: its own project, its own keys.

-- trades (identical to the main app; includes all the added columns)
create table if not exists trades (
  id             bigint primary key,
  date_opened    date,  ticker text,  strategy text,
  short_strike   double precision, long_strike double precision,
  expiry date,  dte_open integer,  contracts integer,
  premium        double precision, cash_secured double precision,
  max_loss       double precision, status text,
  date_closed    date, close_price double precision, realized_pnl double precision,
  signal text, recommended_by text, consensus boolean,
  manual_mark    double precision, net_credit_basis double precision, notes text
);

-- single-owner cash flows (deposits +, withdrawals −)
-- units_delta = amount / nav_per_unit at the flow date (negative redeems units)
create table if not exists cash_flows (
  id            bigserial primary key,
  flow_date     date not null,
  amount        double precision not null,     -- negative = withdrawal
  units_delta   double precision not null,     -- amount / nav_per_unit_at_flow
  nav_per_unit  double precision not null
);

-- watchlist (still needed for Portfolio marking + Trade Log ticker helper)
create table if not exists watchlist (
  ticker text primary key, company text, sector text,
  bucket text, conviction integer, delta_band text
);

-- history (written daily by scripts/daily_snapshot.py)
create table if not exists snapshots (
  snap_date date, ticker text, spot double precision,
  rv21 double precision, rv_rank double precision,
  primary key (snap_date, ticker)
);
create table if not exists portfolio_snapshots (
  snap_date date primary key, open_positions integer,
  total_credits double precision, unreal_pnl double precision,
  realized_pnl double precision, cash_secured double precision
);
create table if not exists fund_snapshots (
  snap_date date primary key, nav double precision, units double precision,
  nav_per_unit double precision, contributed double precision,   -- contributed = net contributed
  realized_pnl double precision, unreal_pnl double precision
);

-- App auth is a shared password gate (fails closed), not Supabase RLS.
-- The anon key is used server-side by Streamlit; disable RLS so it can read/write.
alter table trades              disable row level security;
alter table cash_flows          disable row level security;
alter table watchlist           disable row level security;
alter table snapshots           disable row level security;
alter table portfolio_snapshots disable row level security;
alter table fund_snapshots      disable row level security;
