"""Market-data helpers for the platform REST layer.

The chat/agent path fetches data through tools and the MCP server. The dashboard
UI, by contrast, needs plain JSON for its watchlist, stock header, chart, and
signal card — served by the REST endpoints in web_server.py. Those endpoints call
the functions here.

yfinance is unofficial, synchronous, and rate-limits aggressively, so every fetch
goes through a small in-memory TTL cache. The watchlist alone polls ~6 tickers on
each refresh; without caching that would hammer Yahoo and stall the UI.
"""
from __future__ import annotations

import threading
import time

import yfinance as yf

from .tools import (
    _future_weekdays,
    compute_linear_regression_forecast,
    resolve_ticker,
)

# --- tiny TTL cache -------------------------------------------------------

_cache: dict[str, tuple[float, object]] = {}
_cache_lock = threading.Lock()


def _cached(key: str, ttl: float, producer):
    """Return a cached value for `key`, or compute+store it if stale/missing."""
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    value = producer()  # computed outside the lock — network call
    with _cache_lock:
        _cache[key] = (now, value)
    return value


# --- formatting -----------------------------------------------------------

def _fmt_cap(cap: float | None) -> str:
    if not cap:
        return "—"
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if cap >= div:
            return f"{cap / div:.2f}{suf}"
    return f"{cap:.0f}"


def _round(x, ndigits=2):
    return round(x, ndigits) if isinstance(x, (int, float)) else None


# --- quotes (watchlist + ticker strip) ------------------------------------

def get_quote(ticker: str) -> dict:
    """A lightweight quote: last price, absolute and percent day change.

    Uses yfinance ``fast_info`` (a cheap endpoint) so the watchlist stays snappy.
    """
    tk = resolve_ticker(ticker)["ticker"]

    def _fetch() -> dict:
        try:
            fi = yf.Ticker(tk).fast_info
            last = float(fi["last_price"])
            prev = float(fi["previous_close"])
        except Exception:  # noqa: BLE001 - degrade to a null quote
            return {"ticker": tk, "last": None, "change": None, "pct": None}
        change = last - prev
        pct = (change / prev * 100) if prev else 0.0
        return {"ticker": tk, "last": _round(last), "change": _round(change), "pct": _round(pct)}

    return _cached(f"quote:{tk}", ttl=30, producer=_fetch)


def get_quotes(tickers: list[str]) -> list[dict]:
    return [get_quote(t) for t in tickers]


# --- full stock detail (Markets page header + stat strip) -----------------

def get_stock_detail(ticker: str) -> dict:
    """Header + key stats for one stock: name, price, day change, cap, P/E, 52-wk."""
    tk = resolve_ticker(ticker)["ticker"]

    def _fetch() -> dict:
        try:
            info = yf.Ticker(tk).info or {}
        except Exception:  # noqa: BLE001
            info = {}
        last = info.get("currentPrice") or info.get("regularMarketPrice")
        prev = info.get("previousClose")
        change = (last - prev) if (last and prev) else None
        pct = (change / prev * 100) if (change is not None and prev) else None
        return {
            "ticker": tk,
            "name": info.get("shortName") or info.get("longName") or tk,
            "last": _round(last),
            "change": _round(change),
            "pct": _round(pct),
            "market_cap": _fmt_cap(info.get("marketCap")),
            "pe": _round(info.get("trailingPE"), 1),
            "low_52w": _round(info.get("fiftyTwoWeekLow")),
            "high_52w": _round(info.get("fiftyTwoWeekHigh")),
            "sector": info.get("sector"),
        }

    return _cached(f"detail:{tk}", ttl=120, producer=_fetch)


# --- price history + forecast (the chart) ---------------------------------

# UI timeframe -> (yfinance period, interval, whether to attach the OLS forecast).
_TF_MAP = {
    "1D": ("1d", "5m", False),
    "1W": ("5d", "30m", False),
    "1M": ("1mo", "1d", True),
    "3M": ("3mo", "1d", True),
    "1Y": ("1y", "1d", True),
}


def get_price_series(ticker: str, timeframe: str = "1M") -> dict:
    """Return {points, forecast} for charting.

    ``points`` is the historical close series for the timeframe. ``forecast`` is a
    14-trading-day OLS projection (from 3-month daily closes), attached only for
    the daily timeframes where it reads sensibly on the x-axis.
    """
    tk = resolve_ticker(ticker)["ticker"]
    tf = timeframe if timeframe in _TF_MAP else "1M"
    period, interval, want_fc = _TF_MAP[tf]

    def _fetch() -> dict:
        try:
            df = yf.Ticker(tk).history(period=period, interval=interval)
            df = df.dropna(subset=["Close"])
            points = [
                {"t": idx.isoformat(), "c": round(float(row["Close"]), 2)}
                for idx, row in df.iterrows()
            ]
        except Exception:  # noqa: BLE001
            points = []

        forecast: list[dict] = []
        if want_fc and points:
            try:
                dfd = yf.Ticker(tk).history(period="3mo", interval="1d").dropna(subset=["Close"])
                closes = [float(v) for v in dfd["Close"].tolist()]
                dates = [d.to_pydatetime() for d in dfd.index]
                reg = compute_linear_regression_forecast(closes, horizon=14)
                if reg["status"] == "success" and dates:
                    for d, p in zip(_future_weekdays(dates[-1], 14), reg["forecast"]):
                        forecast.append({"t": d.isoformat(), "c": round(p, 2)})
            except Exception:  # noqa: BLE001 - forecast is optional
                forecast = []

        return {"ticker": tk, "timeframe": tf, "points": points, "forecast": forecast}

    return _cached(f"hist:{tk}:{tf}", ttl=120, producer=_fetch)
