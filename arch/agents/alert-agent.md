# Alert Agent

## Purpose

Monitors a set of software-sector stocks and reports which ones have dropped by more than a configurable threshold percentage from their previous close. Categorises each stock as "alert" (triggered) or "safe".

---

## Configuration

| Field                | Value                               |
|----------------------|-------------------------------------|
| Name                 | `alert_agent`                       |
| Model                | `gemini-2.5-flash`                  |
| Runs in pipeline     | `ALERT`                             |
| Direct Python tools  | `resolve_ticker`, `evaluate_drop_alerts` |
| MCP tools            | `get-ticker-info`                   |
| Default threshold    | 5%                                  |

---

## Tool Descriptions

### `evaluate_drop_alerts(stocks: list[dict], threshold_percent: float) -> dict`

Pure computation — no network calls. Takes a list of stocks with current price and previous close, computes percentage change, and classifies each as alert or safe.

```
Input:
  stocks = [
    { "ticker": "SNOW", "current_price": 123.40, "previous_close": 137.80 },
    { "ticker": "MSFT", "current_price": 425.30, "previous_close": 420.08 }
  ]
  threshold_percent = 5.0

Output: {
  "status": "success",
  "threshold_percent": 5.0,
  "alerts": [
    { "ticker": "SNOW", "company": "Snowflake Inc.", "current_price": 123.40,
      "previous_close": 137.80, "change_percent": -10.44 }
  ],
  "safe": [
    { "ticker": "MSFT", "company": "Microsoft Corporation", "current_price": 425.30,
      "previous_close": 420.08, "change_percent": +1.24 }
  ]
}
```

---

## Default Watchlist

When the user doesn't specify particular stocks, the agent monitors a short default list to avoid context overflow on large batches:

```
MSFT  NVDA  CRM
```

---

## Workflow

```
alert_agent
    │
    ├─ Step 1: Determine ticker list
    │     • Use tickers from intent JSON ("companies") if provided
    │     • Otherwise use short default watchlist (3 tickers: MSFT, NVDA, CRM)
    │
    ├─ Step 2: For each ticker:
    │     resolve_ticker(name_or_ticker)
    │     get-ticker-info(ticker)
    │       → currentPrice, previousClose, regularMarketChangePercent
    │
    ├─ Step 3: evaluate_drop_alerts(stocks, threshold)
    │     Pure Python: classify each stock as alert / safe
    │
    └─ Step 4: LLM formats response
          • Header: threshold used, date
          • Triggered alerts: company, ticker, price, % drop (sorted most severe first)
          • Safe summary: count or list of safe stocks
```

---

## Message Flow

**Query**: "Are any software stocks down more than 8% today? Check MSFT, SNOW, NVDA"

```
stock_orchestrator
    ├─► intent_agent → { "intent": "ALERT", "companies": ["MSFT","SNOW","NVDA"],
    │                     "alert_threshold_percent": 8.0 }
    └─► alert_agent
          │
          ├─► resolve_ticker("MSFT") → "MSFT"
          ├─► get-ticker-info("MSFT") → { currentPrice: 425.30, previousClose: 420.08 }
          │
          ├─► resolve_ticker("SNOW") → "SNOW"
          ├─► get-ticker-info("SNOW") → { currentPrice: 123.40, previousClose: 137.80 }
          │
          ├─► resolve_ticker("NVDA") → "NVDA"
          ├─► get-ticker-info("NVDA") → { currentPrice: 887.60, previousClose: 862.00 }
          │
          ├─► evaluate_drop_alerts(
          │     stocks=[
          │       {"ticker":"MSFT", "current_price":425.30, "previous_close":420.08},
          │       {"ticker":"SNOW", "current_price":123.40, "previous_close":137.80},
          │       {"ticker":"NVDA", "current_price":887.60, "previous_close":862.00}
          │     ],
          │     threshold_percent=8.0
          │   )
          │   → alerts: [SNOW -10.44%]
          │   → safe:   [MSFT +1.24%, NVDA +2.97%]
          │
          └─► LLM response:
                "Drop Alert Check (threshold: 8%) — 2026-05-02

                 🚨 TRIGGERED:
                 • Snowflake (SNOW): $123.40 ↓ -10.44%
                   (prev. close: $137.80)

                 ✅ SAFE:
                 • Microsoft (MSFT): $425.30 ↑ +1.24%
                 • NVIDIA (NVDA):    $887.60 ↑ +2.97%"
```

---

## Notes

- The threshold used is always printed in the response so users know which level triggered alerts.
- `evaluate_drop_alerts` is pure Python and never makes network calls — all price data is collected in the `get-ticker-info` step.
- When no stocks breach the threshold, the agent reports all stocks as safe rather than returning an empty response.
