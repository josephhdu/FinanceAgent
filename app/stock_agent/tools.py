"""Direct-Python tools shared by the specialist agents.

- resolve_ticker: name/alias -> canonical ticker (Chunk 1)
- compute_linear_regression_forecast + fetch_and_forecast: OLS forecast (Chunk 3)
- render_*_chart_for_ticker: one-shot chart tools (Chunk 3)

The chart tools follow the ONE-SHOT pattern: each fetches its own data, computes,
and renders a PNG entirely inside the function, returning a compact dict whose
``markdown`` field holds a ~50KB base64 image. The audit after_tool_callback
strips that field before the response reaches the LLM (a raw base64 PNG tokenises
to ~170K tokens and hangs the model); the image reaches the browser out-of-band.
"""
from __future__ import annotations

import base64
import io
import math
from datetime import datetime, timedelta

import matplotlib

matplotlib.use("Agg")  # headless backend — no display needed
import matplotlib.pyplot as plt  # noqa: E402
import yfinance as yf  # noqa: E402

# --- ticker resolution (Chunk 1) ------------------------------------------

_TICKER_TABLE: dict[str, str] = {
    "microsoft": "MSFT", "msft": "MSFT",
    "apple": "AAPL", "aapl": "AAPL",
    "google": "GOOGL", "alphabet": "GOOGL", "googl": "GOOGL", "goog": "GOOGL",
    "amazon": "AMZN", "amzn": "AMZN",
    "nvidia": "NVDA", "nvda": "NVDA",
    "meta": "META", "facebook": "META", "meta platforms": "META",
    "tesla": "TSLA", "tsla": "TSLA",
    "netflix": "NFLX", "nflx": "NFLX",
    "salesforce": "CRM", "crm": "CRM",
    "adobe": "ADBE", "adbe": "ADBE",
    "servicenow": "NOW", "now": "NOW",
    "snowflake": "SNOW", "snow": "SNOW",
    "crowdstrike": "CRWD", "crwd": "CRWD",
    "palantir": "PLTR", "pltr": "PLTR",
    "oracle": "ORCL", "orcl": "ORCL",
    "sap": "SAP",
    "intel": "INTC", "intc": "INTC",
    "amd": "AMD", "advanced micro devices": "AMD",
    "qualcomm": "QCOM", "qcom": "QCOM",
    "broadcom": "AVGO", "avgo": "AVGO",
    "cisco": "CSCO", "csco": "CSCO",
    "ibm": "IBM",
    "shopify": "SHOP", "shop": "SHOP",
    "uber": "UBER",
    "airbnb": "ABNB", "abnb": "ABNB",
    "paypal": "PYPL", "pypl": "PYPL",
    "datadog": "DDOG", "ddog": "DDOG",
    "zoom": "ZM", "zm": "ZM",
    "atlassian": "TEAM", "team": "TEAM",
    "workday": "WDAY", "wday": "WDAY",
    "twilio": "TWLO", "twlo": "TWLO",
    "okta": "OKTA",
    "mongodb": "MDB", "mdb": "MDB",
    "cloudflare": "NET", "net": "NET",
    "docusign": "DOCU", "docu": "DOCU",
    "palo alto": "PANW", "palo alto networks": "PANW", "panw": "PANW",
}


def resolve_ticker(ticker_or_name: str) -> dict:
    """Resolve a company name or ticker to its canonical stock symbol.

    Args:
        ticker_or_name: A company name (e.g. "Microsoft") or ticker (e.g. "msft").

    Returns:
        A dict with the canonical ``ticker`` and the ``original_input``.
    """
    raw = (ticker_or_name or "").strip()
    ticker = _TICKER_TABLE.get(raw.lower(), raw.upper())
    return {"ticker": ticker, "original_input": raw}


# --- OLS forecast (Chunk 3) -----------------------------------------------

def compute_linear_regression_forecast(prices: list[float], horizon: int = 14) -> dict:
    """Fit an ordinary-least-squares trend line to a price series and project it.

    Pure Python (no numpy) so the math is transparent and dependency-light.

    Returns a dict with the fitted ``slope``/``intercept``, the ``forecast`` list
    (length ``horizon``), the residual ``std`` (for a confidence band), and ``r2``.
    """
    n = len(prices)
    if n < 10:
        return {"status": "error", "message": f"need >=10 data points, got {n}"}

    x_mean = (n - 1) / 2.0
    y_mean = sum(prices) / n
    num = sum((i - x_mean) * (prices[i] - y_mean) for i in range(n))
    den = sum((i - x_mean) ** 2 for i in range(n))
    slope = num / den if den else 0.0
    intercept = y_mean - slope * x_mean

    fitted = [intercept + slope * i for i in range(n)]
    ss_res = sum((prices[i] - fitted[i]) ** 2 for i in range(n))
    ss_tot = sum((p - y_mean) ** 2 for p in prices)
    r2 = 1 - ss_res / ss_tot if ss_tot else 0.0
    std = math.sqrt(ss_res / n)

    forecast = [intercept + slope * (n + k - 1) for k in range(1, horizon + 1)]
    return {
        "status": "success",
        "slope": slope,
        "intercept": intercept,
        "forecast": forecast,
        "std": std,
        "r2": r2,
    }


def _future_weekdays(start: datetime, count: int) -> list[datetime]:
    """`count` business days strictly after `start` (skipping weekends)."""
    days, cur = [], start
    while len(days) < count:
        cur = cur + timedelta(days=1)
        if cur.weekday() < 5:
            days.append(cur)
    return days


def _closes_3mo(ticker: str) -> tuple[list[float], list[datetime]]:
    df = yf.Ticker(ticker).history(period="3mo", interval="1d")
    # yfinance occasionally returns a NaN Close on the most recent (incomplete)
    # row. NaN is not valid JSON, so it would poison the tool response sent to
    # the LLM (400 INVALID_ARGUMENT). Drop those rows up front.
    df = df.dropna(subset=["Close"])
    closes = [float(v) for v in df["Close"].tolist()]
    dates = [d.to_pydatetime() for d in df.index]
    return closes, dates


def fetch_and_forecast(ticker: str) -> dict:
    """One-shot: fetch 3mo of daily closes, fit OLS, project 14 trading days.

    Returns a compact dict (no raw price arrays) the LLM can format into a table.
    """
    try:
        closes, dates = _closes_3mo(ticker)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": f"could not fetch history for {ticker}: {exc}"}
    if len(closes) < 10:
        return {"status": "error", "message": f"not enough price history for {ticker}"}

    reg = compute_linear_regression_forecast(closes, horizon=14)
    if reg["status"] != "success":
        return {"status": "error", "message": reg["message"]}

    last_date = dates[-1] if dates else datetime.utcnow()
    future = _future_weekdays(last_date, 14)
    table = [
        {"date": d.strftime("%Y-%m-%d"), "predicted_price": round(p, 2)}
        for d, p in zip(future, reg["forecast"])
    ]
    current = round(closes[-1], 2)
    target = round(reg["forecast"][-1], 2)
    if not (math.isfinite(current) and math.isfinite(target)):
        return {"status": "error", "message": f"price data for {ticker} was incomplete"}
    pct = round((target - current) / current * 100, 2) if current else 0.0
    trend = "up" if pct > 1 else "down" if pct < -1 else "flat"
    return {
        "status": "success",
        "ticker": ticker.upper(),
        "current_price": current,
        "last_date": last_date.strftime("%Y-%m-%d"),
        "forecast_table": table,
        "target_price_14d": target,
        "pct_change": pct,
        "trend": trend,
        "r2": round(reg["r2"], 3),
    }


# --- one-shot chart renderers (Chunk 3) -----------------------------------

_BG = "#0f131a"
_FG = "#e9e7e1"
_AMBER = "#f0a93d"
_TEAL = "#56beb8"
_GRID = "#262d38"


def _style_ax(ax) -> None:
    ax.set_facecolor(_BG)
    ax.tick_params(colors=_FG, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(_GRID)
    ax.grid(True, color=_GRID, linewidth=0.5, alpha=0.6)
    ax.title.set_color(_FG)
    ax.xaxis.label.set_color(_FG)
    ax.yaxis.label.set_color(_FG)


def _fig_to_markdown(fig, title: str) -> dict:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, facecolor=_BG, bbox_inches="tight")
    plt.close(fig)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return {"status": "success", "title": title, "markdown": f"![{title}](data:image/png;base64,{b64})"}


def render_price_chart_for_ticker(ticker: str) -> dict:
    """Render a 3-month price line chart for a ticker (one-shot)."""
    try:
        closes, dates = _closes_3mo(ticker)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": f"could not fetch history for {ticker}: {exc}"}
    if not closes:
        return {"status": "error", "message": f"no price history for {ticker}"}
    fig, ax = plt.subplots(figsize=(7, 3.6))
    _style_ax(ax)
    ax.plot(dates, closes, color=_AMBER, linewidth=1.8)
    ax.set_title(f"{ticker.upper()} — 3-Month Price")
    ax.set_ylabel("Price ($)")
    fig.autofmt_xdate()
    return _fig_to_markdown(fig, f"{ticker.upper()} 3-Month Price")


def render_prediction_chart_for_ticker(ticker: str) -> dict:
    """Render 3-month history plus a 14-day OLS forecast with a confidence band."""
    try:
        closes, dates = _closes_3mo(ticker)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": f"could not fetch history for {ticker}: {exc}"}
    reg = compute_linear_regression_forecast(closes, horizon=14)
    if reg["status"] != "success":
        return {"status": "error", "message": reg["message"]}
    future = _future_weekdays(dates[-1], 14)
    fc = reg["forecast"]
    std = reg["std"]
    fig, ax = plt.subplots(figsize=(7, 3.6))
    _style_ax(ax)
    ax.plot(dates, closes, color=_AMBER, linewidth=1.8, label="History")
    ax.plot(future, fc, color=_TEAL, linewidth=1.8, linestyle="--", label="Forecast")
    ax.fill_between(
        future,
        [f - std for f in fc],
        [f + std for f in fc],
        color=_TEAL,
        alpha=0.15,
        label="±1σ band",
    )
    ax.set_title(f"{ticker.upper()} — Price & 14-Day Forecast")
    ax.set_ylabel("Price ($)")
    leg = ax.legend(fontsize=7, facecolor=_BG, edgecolor=_GRID, labelcolor=_FG)
    fig.autofmt_xdate()
    return _fig_to_markdown(fig, f"{ticker.upper()} Forecast")


def render_comparison_chart_for_tickers(tickers: list[str], company_names: list[str] | None = None) -> dict:
    """Render a bar chart of today's percent change across several tickers."""
    labels, changes = [], []
    for t in tickers:
        try:
            fi = yf.Ticker(t).fast_info
            last, prev = float(fi["last_price"]), float(fi["previous_close"])
            changes.append((last - prev) / prev * 100 if prev else 0.0)
            labels.append(t.upper())
        except Exception:  # noqa: BLE001 - skip a ticker that fails
            continue
    if not changes:
        return {"status": "error", "message": "no data for the requested tickers"}
    order = sorted(range(len(changes)), key=lambda i: changes[i], reverse=True)
    labels = [labels[i] for i in order]
    changes = [changes[i] for i in order]
    colors = ["#5fb97e" if c >= 0 else "#e06b69" for c in changes]
    fig, ax = plt.subplots(figsize=(7, 3.6))
    _style_ax(ax)
    ax.bar(labels, changes, color=colors)
    ax.axhline(0, color=_GRID, linewidth=1)
    ax.set_title("Daily % Change")
    ax.set_ylabel("% change")
    return _fig_to_markdown(fig, "Comparison — Daily % Change")


def render_financial_chart_for_ticker(ticker: str) -> dict:
    """Render revenue and margin bars from the ticker's fundamentals."""
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": f"could not fetch fundamentals for {ticker}: {exc}"}
    margins = {
        "Gross": info.get("grossMargins"),
        "Operating": info.get("operatingMargins"),
        "Net": info.get("profitMargins"),
    }
    margins = {k: v * 100 for k, v in margins.items() if isinstance(v, (int, float))}
    if not margins:
        return {"status": "error", "message": f"no margin data for {ticker}"}
    fig, ax = plt.subplots(figsize=(7, 3.6))
    _style_ax(ax)
    ax.bar(list(margins.keys()), list(margins.values()), color=_AMBER)
    ax.set_title(f"{ticker.upper()} — Margins")
    ax.set_ylabel("%")
    return _fig_to_markdown(fig, f"{ticker.upper()} Margins")
