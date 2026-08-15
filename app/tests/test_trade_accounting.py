"""Paper-trade accounting: average-cost position replay + the oversell guard.

The star here is ``test_partial_sell_uses_average_cost`` — a regression test for a
real bug where a SELL reduced cost basis by the *sale* notional instead of the
average cost of the shares sold, which zeroed out the basis of the shares still
held and invented phantom P/L.
"""
import stock_agent.trade_tools as tt
from stock_agent.trade_tools import replay_positions


def _trade(ticker: str, action: str, shares: int, price: float) -> dict:
    return {
        "ticker": ticker,
        "action": action,
        "shares": shares,
        "price": price,
        "notional": round(shares * price, 2),
    }


# --- average-cost replay ---------------------------------------------------

def test_single_buy():
    assert replay_positions([_trade("AAPL", "BUY", 10, 100.0)]) == [
        {"ticker": "AAPL", "shares": 10, "cost_basis": 1000.0}
    ]


def test_partial_sell_uses_average_cost():
    # Buy 10 @ $100, then sell 5 @ $200. The 5 shares that remain must keep a
    # $500 basis (avg cost $100/sh) — NOT $0, which the old sale-notional bug gave.
    trades = [_trade("AAPL", "BUY", 10, 100.0), _trade("AAPL", "SELL", 5, 200.0)]
    assert replay_positions(trades) == [
        {"ticker": "AAPL", "shares": 5, "cost_basis": 500.0}
    ]


def test_full_close_removes_position():
    trades = [_trade("AAPL", "BUY", 10, 100.0), _trade("AAPL", "SELL", 10, 150.0)]
    assert replay_positions(trades) == []


def test_averaging_across_multiple_buys():
    # 10 @ $100 + 10 @ $200 => 20 sh, $3000 basis (avg $150). Sell 10 => 10 sh, $1500.
    trades = [
        _trade("X", "BUY", 10, 100.0),
        _trade("X", "BUY", 10, 200.0),
        _trade("X", "SELL", 10, 175.0),
    ]
    assert replay_positions(trades) == [
        {"ticker": "X", "shares": 10, "cost_basis": 1500.0}
    ]


def test_multiple_tickers_are_independent():
    trades = [_trade("A", "BUY", 1, 10.0), _trade("B", "BUY", 2, 20.0)]
    by_ticker = {p["ticker"]: p for p in replay_positions(trades)}
    assert by_ticker["A"]["cost_basis"] == 10.0
    assert by_ticker["B"]["shares"] == 2


# --- holdings + oversell guard ---------------------------------------------

def test_shares_held_nets_buys_and_sells(monkeypatch):
    monkeypatch.setattr(tt, "_read_trades", lambda: [
        _trade("AAPL", "BUY", 10, 100.0), _trade("AAPL", "SELL", 4, 120.0),
    ])
    assert tt._shares_held("AAPL") == 6
    assert tt._shares_held("MSFT") == 0


def test_oversell_is_blocked(monkeypatch):
    monkeypatch.setattr(tt, "_read_trades", lambda: [_trade("AAPL", "BUY", 3, 100.0)])
    res = tt.execute_trade_now("AAPL", "SELL", 5, price=100.0)
    assert res["status"] == "error"
    assert "only hold 3" in res["message"]


def test_sell_within_holdings_is_allowed(monkeypatch):
    monkeypatch.setattr(tt, "_read_trades", lambda: [_trade("AAPL", "BUY", 5, 100.0)])
    # Stub the append so the test never touches the real trade log on disk.
    monkeypatch.setattr(tt, "_append_trade", lambda *a, **k: {
        "trade_id": "TRD-TEST", "ticker": "AAPL", "action": "SELL",
        "shares": 2, "price": 100.0, "notional": 200.0,
    })
    res = tt.execute_trade_now("AAPL", "SELL", 2, price=100.0)
    assert res["status"] == "success"


def test_rejects_bad_action_and_nonpositive_shares():
    assert tt.execute_trade_now("AAPL", "HOLD", 1, price=1.0)["status"] == "error"
    assert tt.execute_trade_now("AAPL", "BUY", 0, price=1.0)["status"] == "error"
