# Price Agent

## Purpose

Retrieves the current market price, daily change, and key metrics for one or more software-sector stocks.

---

## Configuration

| Field                | Value                              |
|----------------------|------------------------------------|
| Name                 | `price_agent`                      |
| Model                | `gemini-2.5-flash`                 |
| Runs in pipelines    | `PRICE`, `PRICE_PREDICTION`, `PRICE_PREDICT_CHART` |
| Direct Python tools  | `resolve_ticker`                   |
| MCP tools            | `get-ticker-info`                  |

---

## Tool Descriptions

### `resolve_ticker(ticker_or_name: str) -> dict`

Normalises company names and fuzzy inputs to canonical ticker symbols using a static lookup table of 37 software companies.

```
Input:  "Microsoft" | "MSFT" | "msft"
Output: { "ticker": "MSFT", "original_input": "Microsoft" }
```

### `get-ticker-info(symbol: str) -> str` (MCP)

Returns current market data from Yahoo Finance via the finance MCP server:
- `currentPrice`, `previousClose`, `regularMarketChangePercent`
- `marketCap`, `volume`, `dayHigh`, `dayLow`
- Financial ratios: `trailingPE`, `forwardPE`, `trailingEps`
- Company metadata: `shortName`, `sector`, `industry`

---

## Workflow

```
price_agent
    │
    ├─ Step 1: resolve_ticker(company_name_or_ticker)
    │     Returns canonical ticker symbol
    │
    ├─ Step 2: get-ticker-info(ticker)
    │     MCP → finance_mcp_server → yf.Ticker(symbol).info
    │     Returns price, change %, market cap, and key ratios
    │
    └─ Step 3: LLM formats response
          • Current price (e.g., $425.30)
          • Daily change: $ amount and %
          • Market capitalisation (in T or B)
          • Optional sector context if query was sector-level
```

---

## System Prompt Key Rules

- Use only `resolve_ticker` and `get-ticker-info` — no other tools.
- For queries about multiple stocks (e.g., sector overview), call `resolve_ticker` + `get-ticker-info` for each ticker.
- Always report both the dollar change and the percentage change.
- State market cap in trillions (T) or billions (B) as appropriate.
- Do not add disclaimers for price queries (factual real-time data).
- **Never comment on forecasting or prediction capabilities.** When running as step 1 in a compound pipeline (`PRICE_PREDICTION`, `PRICE_PREDICT_CHART`), the user's query may mention predictions — price_agent must ignore that part of the query entirely and only deliver price data. It must not say "I cannot provide a prediction" or offer alternatives; prediction_agent handles that in the next step.

---

## Message Flow: Single Stock

**Query**: "What's Microsoft's current price?"

```
stock_orchestrator
    ├─► intent_agent → { "intent": "PRICE", "companies": ["MSFT"] }
    └─► price_agent
          │
          ├─► resolve_ticker("MSFT")
          │     → { "ticker": "MSFT", "original_input": "MSFT" }
          │
          ├─► get-ticker-info("MSFT")
          │     MCP call → yf.Ticker("MSFT").info
          │     → { "currentPrice": 425.30, "regularMarketChangePercent": 1.24,
          │         "previousClose": 420.08, "marketCap": 3160000000000,
          │         "shortName": "Microsoft Corporation" }
          │
          └─► LLM response:
                "Microsoft (MSFT) is trading at $425.30,
                 up $5.22 (+1.24%) from yesterday's close of $420.08.
                 Market capitalisation: $3.16T."
```

---

## Message Flow: Sector Overview

**Query**: "How are software stocks doing today?"

```
price_agent
    │
    ├─► resolve_ticker("MSFT") → "MSFT"
    ├─► get-ticker-info("MSFT") → {price, change}
    │
    ├─► resolve_ticker("GOOGL") → "GOOGL"
    ├─► get-ticker-info("GOOGL") → {price, change}
    │
    │   ... (for each default sector ticker: MSFT GOOGL AAPL NVDA META CRM ADBE NOW SNOW CRWD)
    │
    └─► LLM formats ranked list:
          "Software sector today (top movers):
           ▲ NVDA  +3.4%  $887.60
           ▲ MSFT  +1.2%  $425.30
           ─ AAPL   0.0%  $212.40
           ▼ CRM   -1.8%  $284.10
           ..."
```

---

## Notes

- The agent is kept stateless: each invocation fetches fresh data.
- In compound pipelines (`PRICE_PREDICTION`), the price_agent's output sits in conversation history when prediction_agent runs — prediction_agent sees the current price without re-fetching it.
