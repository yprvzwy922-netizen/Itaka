"""
Order ticket — a session 'cart' of options you want to trade, plus a formatter
that turns it into broker-ready message lines like:
    sell 50 cts NUAI US 07/17/26 P5 at 0.60
"""
import datetime
import streamlit as st


def get_ticket() -> list:
    return st.session_state.setdefault("ticket", [])


def add_to_ticket(action, ticker, expiry, opt_type, strike, price, contracts):
    """opt_type: 'put'/'call' or 'P'/'C'. expiry: 'YYYY-MM-DD'."""
    get_ticket().append({
        "kind":      "single",
        "action":    action.lower(),                 # sell to open / buy to close / ...
        "ticker":    ticker.upper(),
        "expiry":    expiry,                          # ISO; formatted on render
        "type":      "P" if str(opt_type).lower().startswith("p") else "C",
        "strike":    float(strike),
        "price":     float(price),
        "contracts": int(contracts),
    })


def add_roll_to_ticket(ticker, opt_type, contracts,
                       close_expiry, close_strike,
                       open_expiry, open_strike, net_credit):
    """A roll = one line item with two legs, priced as a single net credit."""
    get_ticket().append({
        "kind":         "roll",
        "ticker":       ticker.upper(),
        "type":         "P" if str(opt_type).lower().startswith("p") else "C",
        "contracts":    int(contracts),
        "close_expiry": close_expiry,
        "close_strike": float(close_strike),
        "open_expiry":  open_expiry,
        "open_strike":  float(open_strike),
        "net_credit":   float(net_credit),
    })


def remove_from_ticket(idx):
    t = get_ticket()
    if 0 <= idx < len(t):
        t.pop(idx)


def clear_ticket():
    st.session_state["ticket"] = []


def _fmt_expiry(iso):
    try:
        return datetime.datetime.strptime(str(iso), "%Y-%m-%d").strftime("%m/%d/%y")
    except Exception:
        return str(iso)


def _fmt_strike(k):
    # 45.0 -> "45", 5.5 -> "5.5"
    return f"{k:g}"


def format_line(item) -> str:
    return (f"{item['action']} {item['contracts']} cts {item['ticker']} US "
            f"{_fmt_expiry(item['expiry'])} {item['type']}{_fmt_strike(item['strike'])} "
            f"at {item['price']:.2f}")


def format_roll_block(item, account: str = "") -> str:
    """Exact roll format:
    Account L Roll
    DGXX US buy to close 41 cts 07/17/26 P6
    DGXX US sell to open 41 cts 08/21/26 P6
    at 0.40 net credit
    """
    hdr = f"Account {account.strip()} Roll" if account.strip() else "Roll"
    t, cts = item["ticker"], item["contracts"]
    typ = item["type"]
    nc  = float(item["net_credit"])
    px  = f"at {nc:.2f} net credit" if nc >= 0 else f"at {abs(nc):.2f} net debit"
    return "\n".join([
        hdr,
        f"{t} US buy to close {cts} cts {_fmt_expiry(item['close_expiry'])} {typ}{_fmt_strike(item['close_strike'])}",
        f"{t} US sell to open {cts} cts {_fmt_expiry(item['open_expiry'])} {typ}{_fmt_strike(item['open_strike'])}",
        px,
    ])


def format_message(items, account: str = "") -> str:
    singles = [it for it in items if it.get("kind", "single") == "single"]
    rolls   = [it for it in items if it.get("kind") == "roll"]
    blocks = []
    if singles:
        header = f"Account {account}\n" if account.strip() else ""
        blocks.append(header + "\n".join("• " + format_line(it) for it in singles))
    for r in rolls:
        blocks.append(format_roll_block(r, account))
    return "\n\n".join(blocks)
