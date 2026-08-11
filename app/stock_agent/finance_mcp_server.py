"""Finance MCP server — Yahoo Finance tools exposed over MCP (stdio).

Run as a subprocess by the ADK agents (see mcp_config.py). Each tool wraps the
synchronous ``yfinance`` library in a thread so it never blocks the event loop,
and returns a JSON string. On error it returns a JSON error object rather than
raising — a failed data fetch should degrade gracefully, not crash the turn.

Tool names use underscores (get_ticker_info) rather than the blueprint's hyphens
(get-ticker-info) because Gemini function-calling names must be underscore-safe.

Launch: python -m stock_agent.finance_mcp_server
"""
from __future__ import annotations

import asyncio
import json
import math
from typing import Any

import yfinance as yf
from fastmcp import FastMCP

mcp = FastMCP("finance")


def _clean(obj: Any) -> Any:
    """Recursively replace non-finite floats (NaN/Inf) with None.

    yfinance frequently returns NaN for missing fields. Python's json.dumps emits
    a literal `NaN` token, which is invalid JSON — and when that tool response is
    serialized into the next Gemini request it triggers 400 INVALID_ARGUMENT. So
    every tool response is cleaned before it leaves the server.
    """
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj


def _dumps(obj: Any) -> str:
    return json.dumps(_clean(obj))

# Fields we surface from yf.Ticker(...).info — a curated subset of the ~150
# yfinance exposes, covering price, valuation, margins, and profile.
_INFO_FIELDS = [
    "symbol", "shortName", "currentPrice", "previousClose", "open",
    "dayHigh", "dayLow", "volume", "marketCap", "currency", "exchange",
    "trailingPE", "forwardPE", "priceToSalesTrailing12Months", "priceToBook",
    "trailingEps", "forwardEps", "totalRevenue", "grossMargins",
    "operatingMargins", "profitMargins", "returnOnEquity", "totalDebt",
    "totalCash", "debtToEquity", "regularMarketChangePercent",
    "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "dividendYield", "beta",
    "sector", "industry", "longBusinessSummary",
]


async def _in_thread(fn, *args) -> Any:
    return await asyncio.get_event_loop().run_in_executor(None, fn, *args)


@mcp.tool(name="get_ticker_info")
async def get_ticker_info(symbol: str) -> str:
    """Return current price, valuation multiples, margins, and company profile
    for a stock ticker as a JSON string."""
    def _fetch() -> dict:
        info = yf.Ticker(symbol).info or {}
        out = {k: info.get(k) for k in _INFO_FIELDS if info.get(k) is not None}
        out.setdefault("symbol", symbol.upper())
        return out
    try:
        return _dumps(await _in_thread(_fetch))
    except Exception as exc:  # noqa: BLE001 - degrade gracefully
        return json.dumps({"symbol": symbol.upper(), "error": str(exc)})


@mcp.tool(name="get_price_history")
async def get_price_history(symbol: str, period: str = "3mo", interval: str = "1d") -> str:
    """Return OHLCV price history as a JSON array of {date,open,high,low,close,volume}.
    period: 1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,ytd,max. interval: 1d,1wk,1mo,etc."""
    def _fetch() -> list[dict]:
        df = yf.Ticker(symbol).history(period=period, interval=interval)
        rows = []
        for idx, row in df.iterrows():
            rows.append({
                "date": idx.isoformat(),
                "open": round(float(row["Open"]), 4),
                "high": round(float(row["High"]), 4),
                "low": round(float(row["Low"]), 4),
                "close": round(float(row["Close"]), 4),
                "volume": int(row["Volume"]),
            })
        return rows
    try:
        return _dumps({"symbol": symbol.upper(), "period": period, "history": await _in_thread(_fetch)})
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"symbol": symbol.upper(), "error": str(exc)})


@mcp.tool(name="ticker_earning")
async def ticker_earning(symbol: str, period: str = "annual") -> str:
    """Return earnings/EPS data (revenue and earnings by year, plus trailing/
    forward EPS and P/E) for a ticker as a JSON string."""
    def _fetch() -> dict:
        t = yf.Ticker(symbol)
        info = t.info or {}
        return {
            "symbol": symbol.upper(),
            "trailing_eps": info.get("trailingEps"),
            "forward_eps": info.get("forwardEps"),
            "trailing_pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "total_revenue": info.get("totalRevenue"),
        }
    try:
        return _dumps(await _in_thread(_fetch))
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"symbol": symbol.upper(), "error": str(exc)})


if __name__ == "__main__":
    mcp.run()
