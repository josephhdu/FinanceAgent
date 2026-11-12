"""Mock (paper) trading tools.

A composite BUY/SELL/HOLD signal, an in-memory pending-trade store keyed by chat
session, and an append-only trade log. NO real orders are ever placed — this is
paper trading only, and a human must approve before anything is recorded.

Signal = 0.4·forecast + 0.4·analyst + 0.2·upside (each sub-score clamped to
[-1, 1]).  BUY if score ≥ 0.3, SELL if ≤ -0.3, else HOLD.
"""
from __future__ import annotations

import json
import math
import os
import random
import threading
from datetime import datetime, timezone

import yfinance as yf

from .audit import current_session_id, current_user_id
from .tools import fetch_and_forecast

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_TRADES_PATH = os.path.join(_DATA_DIR, "trades.jsonl")
_NOTIONAL_USD = 2000.0
# Paper account starting cash — every user's balance is measured against this.
STARTING_CASH = 10_000.0

# Serializes check-then-append on the trade log so two concurrent orders can't
# both pass the cash/holdings check (single-process server).
_trade_lock = threading.Lock()

# recommendationKey (yfinance) -> analyst sub-score in [-1, 1].
_ANALYST_MAP = {
    "strong_buy": 1.0, "buy": 0.7, "outperform": 0.6, "hold": 0.0,
    "underperform": -0.6, "sell": -0.7, "strong_sell": -1.0,
}

# "{user}::{session_id}" -> pending trade dict (lost on restart — intentional).
_pending: dict[str, dict] = {}


def _sid() -> str:
    return current_session_id.get() or "default"


def _uid() -> str:
    """The authenticated owner of the current request (JWT `sub`)."""
    return current_user_id.get() or "anonymous"


def _pkey() -> str:
    """Pending-trade key: scoped to both the user and their chat session."""
    return f"{_uid()}::{_sid()}"


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def get_trade_signals(ticker: str) -> dict:
    """Compute a BUY/SELL/HOLD signal for a ticker from a weighted blend of an OLS
    forecast, analyst consensus, and analyst price-target upside."""
    fc = fetch_and_forecast(ticker)
    if fc.get("status") != "success":
        return {"status": "error", "message": f"could not compute a signal for {ticker}"}
    price = fc["current_price"]
    forecast_pct = fc["pct_change"]

    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:  # noqa: BLE001
        info = {}
    rec_key = (info.get("recommendationKey") or "hold").lower()
    analyst = _ANALYST_MAP.get(rec_key, 0.0)
    target = info.get("targetMeanPrice")
    upside_pct = ((target - price) / price * 100) if (target and price) else 0.0

    forecast_score = _clamp(forecast_pct / 10.0)
    analyst_score = _clamp(analyst)
    upside_score = _clamp(upside_pct / 20.0)
    score = 0.4 * forecast_score + 0.4 * analyst_score + 0.2 * upside_score
    action = "BUY" if score >= 0.3 else "SELL" if score <= -0.3 else "HOLD"
    shares = max(1, math.floor(_NOTIONAL_USD / price)) if price else 1

    return {
        "status": "success",
        "ticker": ticker.upper(),
        "action": action,
        "signal_score": round(score, 3),
        "confidence_pct": round(min(abs(score) * 100, 100), 1),
        "current_price": round(price, 2),
        "suggested_shares": shares,
        "drivers": {
            "forecast_return_14d_pct": forecast_pct,
            "analyst_recommendation": rec_key,
            "analyst_score": round(analyst_score, 2),
            "price_target": target,
            "upside_pct": round(upside_pct, 2),
        },
    }


def store_pending_trade(ticker: str, action: str, shares: int, price: float, reasoning: str) -> dict:
    """Hold a proposed trade in memory pending the user's explicit approval."""
    _pending[_pkey()] = {
        "ticker": ticker.upper(),
        "action": action.upper(),
        "shares": int(shares),
        "price": round(float(price), 2),
        "reasoning": reasoning,
    }
    return {"status": "success", "message": "trade proposal stored, awaiting approval"}


def get_pending_trade() -> dict:
    """Return the pending trade for this session, or a not-found status."""
    p = _pending.get(_pkey())
    return {"status": "success", "pending": p} if p else {"status": "success", "pending": None}


def has_pending_trade() -> bool:
    return _pkey() in _pending


def cancel_pending_trade() -> dict:
    """Discard the pending trade without recording it."""
    existed = _pending.pop(_pkey(), None) is not None
    return {"status": "success", "cancelled": existed}


def _trade_id() -> str:
    return f"TRD-{datetime.now(timezone.utc):%Y%m%d}-{random.randint(0, 0xFFFFFF):06X}"


def _shares_held(ticker: str) -> int:
    """Net shares of `ticker` currently held by the requesting user (BUY − SELL)."""
    tk = ticker.upper()
    held = 0
    for t in _read_trades():
        if t.get("ticker") != tk:
            continue
        held += t["shares"] if t["action"] == "BUY" else -t["shares"]
    return held


def cash_balance(trades: list[dict] | None = None) -> float:
    """Starting cash, net of every buy/sell notional in this user's trade log."""
    cash = STARTING_CASH
    for t in _read_trades() if trades is None else trades:
        cash += -t["notional"] if t["action"] == "BUY" else t["notional"]
    return cash


def _record_trade(ticker: str, action: str, shares: int, price: float) -> dict:
    """Validate a trade against cash and holdings, then append it — atomically.

    The single write path for both the chat approval and the GUI ticket: a BUY
    can't exceed available cash and a SELL can't exceed shares held.
    """
    tk = ticker.upper()
    with _trade_lock:
        if action == "BUY":
            cost = shares * price
            cash = cash_balance()
            if cost > cash:
                return {
                    "status": "error",
                    "message": f"not enough cash: {shares} {tk} costs ${cost:,.2f} "
                    f"but you have ${cash:,.2f}",
                }
        else:
            held = _shares_held(tk)
            if shares > held:
                return {"status": "error", "message": f"can't sell {shares} {tk} — you only hold {held}"}
        return {"status": "success", **_append_trade(tk, action, shares, price)}


def _append_trade(ticker: str, action: str, shares: int, price: float) -> dict:
    """Write one executed (mock) paper-trade record to the append-only log,
    stamped with the current user, and return it."""
    record = {
        "trade_id": _trade_id(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user": _uid(),
        "ticker": ticker.upper(),
        "action": action.upper(),
        "shares": int(shares),
        "price": round(float(price), 2),
        "notional": round(int(shares) * float(price), 2),
    }
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_TRADES_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    return record


def execute_pending_trade() -> dict:
    """Record the pending trade (chat path) as an executed paper trade.

    Called only by the orchestrator after the user's message parses as an
    approval — deliberately NOT exposed as a tool to any LLM agent.
    """
    p = _pending.pop(_pkey(), None)
    if p is None:
        return {"status": "error", "message": "no pending trade to execute"}
    return _record_trade(p["ticker"], p["action"], p["shares"], p["price"])


def execute_trade_now(ticker: str, action: str, shares: int, price: float | None = None) -> dict:
    """Directly execute a paper trade from the GUI trade ticket.

    The UI's confirmation dialog is the human-in-the-loop step here (mirroring the
    chat flow's explicit "yes"). If no price is supplied, the live price is used.
    """
    action = (action or "").upper()
    if action not in ("BUY", "SELL"):
        return {"status": "error", "message": "action must be BUY or SELL"}
    try:
        shares = int(shares)
    except (TypeError, ValueError):
        return {"status": "error", "message": "shares must be a whole number"}
    if shares <= 0:
        return {"status": "error", "message": "shares must be a positive whole number"}

    if price is None:
        fc = fetch_and_forecast(ticker)
        price = fc.get("current_price") if fc.get("status") == "success" else None
        if price is None:
            return {"status": "error", "message": f"could not price {ticker.upper()}"}
    return _record_trade(ticker, action, shares, price)


def _read_trades() -> list[dict]:
    """Read this user's trades from the shared append-only log.

    The log is one global file, but each record carries a ``user`` field; we
    return only the current user's rows so portfolios and history are per-owner.
    Legacy rows written before per-user scoping have no ``user`` and belong to
    no one (they're skipped).
    """
    if not os.path.exists(_TRADES_PATH):
        return []
    uid = _uid()
    out = []
    with open(_TRADES_PATH, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("user") == uid:
                    out.append(rec)
    return out


def replay_positions(trades: list[dict]) -> list[dict]:
    """Replay a trade log into open positions using **average-cost accounting**.

    A SELL reduces cost basis by the *average cost* of the shares sold — NOT their
    sale price — so the shares that remain keep a correct basis (and therefore a
    correct unrealized P/L). Reducing basis by the sale notional instead would let
    a profitable partial sale zero out the basis of the shares still held and
    invent phantom gains. Selling a position down to zero clears its basis exactly.

    Pure function (no I/O) so the accounting is unit-testable in isolation.
    """
    positions: dict[str, dict] = {}
    for t in trades:
        pos = positions.setdefault(t["ticker"], {"shares": 0, "cost_basis": 0.0})
        if t["action"] == "BUY":
            pos["shares"] += t["shares"]
            pos["cost_basis"] += t["notional"]
        elif t["action"] == "SELL":
            avg_cost = pos["cost_basis"] / pos["shares"] if pos["shares"] else 0.0
            pos["shares"] -= t["shares"]
            pos["cost_basis"] -= avg_cost * t["shares"]
            if pos["shares"] <= 0:  # fully closed (oversell is guarded upstream)
                pos["shares"] = 0
                pos["cost_basis"] = 0.0
    return [
        {"ticker": k, "shares": v["shares"], "cost_basis": round(v["cost_basis"], 2)}
        for k, v in positions.items()
        if v["shares"] != 0
    ]


def get_portfolio() -> dict:
    """Compute this user's current paper positions by replaying their trade log."""
    return {"status": "success", "positions": replay_positions(_read_trades())}


def get_trade_history(limit: int = 10) -> dict:
    """Return the most recent executed paper trades (newest first)."""
    trades = _read_trades()
    trades.reverse()
    return {"status": "success", "trades": trades[: max(1, min(int(limit), 100))]}
