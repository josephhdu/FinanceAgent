# Prediction Agent

## Purpose

Generates a 14-day price forecast for a given stock using OLS linear regression on the past 3 months of daily closing prices. Presents the projection as a day-by-day table with trend direction and percentage change estimate.

---

## Configuration

| Field                | Value                              |
|----------------------|------------------------------------|
| Name                 | `prediction_agent`                 |
| Model                | `gemini-2.5-flash`                 |
| Runs in pipelines    | `PREDICTION`, `PRICE_PREDICTION`, `PRICE_PREDICT_CHART` |
| Direct Python tools  | `resolve_ticker`, `fetch_and_forecast` |
| MCP tools            | None                               |

---

## Tool Descriptions

### `fetch_and_forecast(ticker: str) -> dict`

One-shot tool: fetches 3 months of daily closing prices from yfinance and runs OLS regression to project 14 trading days forward. Never passes raw price arrays through the LLM.

```
Input:  { "ticker": "NVDA" }
Output: {
  "status": "success",
  "ticker": "NVDA",
  "company_name": "NVIDIA Corporation",
  "current_price": 887.60,
  "last_date": "2026-05-01",
  "forecast_table": [
    { "date": "2026-05-02", "predicted_price": 895.20 },
    { "date": "2026-05-05", "predicted_price": 902.80 },
    ...  (14 rows, weekdays only)
  ],
  "trend": "up",
  "pct_change": 4.32
}
```

Returns `{ "status": "error", "message": "..." }` if fewer than 10 data points are available.

---

## OLS Regression Algorithm

Implemented in pure Python (no numpy), in `tools.py`:

```
Given n closing prices [p_0, p_1, ..., p_{n-1}]:

  x_i       = i  (day index 0..n-1)
  x_mean    = (n-1) / 2.0
  y_mean    = mean(prices)

  slope     = Σ (x_i - x_mean)(p_i - y_mean)
              ─────────────────────────────────
              Σ (x_i - x_mean)²

  intercept = y_mean - slope × x_mean

  predicted day k = intercept + slope × (n + k - 1)
                    where k = 1..14 (next 14 trading days)
```

Weekend days are skipped using `datetime.weekday() < 5`. The last 3 months of data provides ~63 data points for the regression.

---

## Workflow

```
prediction_agent
    │
    ├─ Step 1: resolve_ticker(name_or_ticker)
    │
    ├─ Step 2: fetch_and_forecast(ticker)
    │     Internally:
    │       yf.download(ticker, period="3mo", interval="1d")
    │       Handle MultiIndex columns (yfinance quirk)
    │       Extract Close prices → list[float]
    │       Run compute_linear_regression_forecast()
    │       Return compact dict (no raw price arrays)
    │
    └─ Step 3: LLM formats response
          • Current price
          • Forecast table (date | predicted price) — 14 rows
          • Trend direction (upward / downward / flat)
          • Projected % change from today to day 14
          • Disclaimer: statistical projection, not investment advice
```

---

## System Prompt Key Rules

- Always include the disclaimer that forecasts are statistical projections and not investment advice.
- Present the day-by-day table in full (14 rows).
- State both the start price (current) and end price (day 14) to make the trend concrete.
- Do not call any tools other than `resolve_ticker` and `fetch_and_forecast`.

---

## Message Flow

**Query**: "What will NVDA's price be in 2 weeks?"

```
stock_orchestrator
    ├─► intent_agent → { "intent": "PREDICTION", "companies": ["NVDA"],
    │                     "time_horizon": "2 weeks" }
    └─► prediction_agent
          │
          ├─► resolve_ticker("NVDA") → "NVDA"
          │
          ├─► fetch_and_forecast("NVDA")
          │     yf.download("NVDA", period="3mo", interval="1d")
          │       → 63 trading-day close prices
          │     OLS: slope = 3.81 $/day, intercept = 821.30
          │     Forecast days 1–14:
          │       2026-05-02: $895.20
          │       2026-05-05: $902.80
          │       ...
          │       2026-05-19: $950.30
          │     Returns: { trend: "up", pct_change: 4.32 }
          │
          └─► LLM response:
                "Based on the past 3 months, NVIDIA (NVDA) shows an upward
                 trend. Starting from the current price of $887.60, the
                 linear regression model projects the following:

                 | Date       | Projected Price |
                 |------------|----------------|
                 | 2026-05-02 | $895.20         |
                 | 2026-05-05 | $902.80         |
                 | ...        | ...             |
                 | 2026-05-19 | $950.30         |

                 Projected change over 14 trading days: +4.32% ↑

                 Disclaimer: This is a statistical projection based on
                 historical data and is not investment advice."
```

---

## Notes

- The `fetch_and_forecast` tool is deliberately one-shot: it fetches data AND runs regression AND formats the table internally. This avoids passing 63 rows of OHLCV JSON through the LLM context just to have the LLM extract the Close column.
- In the `PRICE_PREDICT_CHART` pipeline, `visualization_agent` runs after `prediction_agent` and renders the forecast as a chart using `render_prediction_chart_for_ticker`, which re-runs the forecast internally to produce the PNG.
