# MCP Integration

## Overview

The system uses the **Model Context Protocol (MCP)** to expose Yahoo Finance data as tools that ADK agents can call. MCP runs as a **subprocess** (stdio transport), which isolates the data-fetching process from the ADK runtime and provides a clean tool-discovery mechanism.

A second MCP server wraps the RAG tools, though in practice the RAG tools are called as direct Python functions due to a startup-time constraint (see below).

---

## Architecture

```
ADK Agent (in-process)
    │
    │  McpToolset (ADK)
    │  StdioConnectionParams
    │
    ├──── subprocess spawn ────────────────────────────────────────┐
    │                                                              │
    │   finance_mcp_server.py  (FastMCP, stdio transport)         │
    │                                                              │
    │   Tools:                                                     │
    │     get-ticker-info       ──► yf.Ticker(symbol).info        │
    │     get-price-history     ──► yf.download(period, interval) │
    │     ticker-earning        ──► yf.Ticker(symbol).earnings_… │
    │                                                              │
    └──────────────────────────────────────────────────────────────┘
```

The subprocess is spawned once per agent instance and kept alive for the agent's lifetime. Tool calls travel over stdin/stdout as JSON-RPC.

---

## Finance MCP Server

**File**: `stock_agent/finance_mcp_server.py`
**Entry point**: `python -m stock_agent.finance_mcp_server`
**Transport**: stdio (subprocess from `mcp_config.py`)

### Tools

#### `get-ticker-info`

Fetches current price, market cap, financial ratios, and company metadata.

```
Input:  { "symbol": "MSFT" }
Output: JSON string with fields:
  symbol, shortName, currentPrice, previousClose, open, dayHigh, dayLow,
  volume, marketCap, currency, exchange,
  trailingPE, forwardPE, priceToSalesTrailing12Months, priceToBook,
  enterpriseToEbitda, pegRatio, trailingEps, forwardEps,
  totalRevenue, grossProfits, grossMargins, operatingMargins, profitMargins,
  returnOnEquity, totalDebt, totalCash, debtToEquity,
  regularMarketChangePercent, fiftyTwoWeekHigh, fiftyTwoWeekLow,
  dividendYield, beta, sector, industry, longBusinessSummary
  (all timestamp fields converted to ISO 8601)
```

#### `get-price-history`

Downloads OHLCV history using yfinance.

```
Input:  {
  "symbol":   "AAPL",
  "period":   "3mo",     # 1d|5d|1mo|3mo|6mo|1y|2y|5y|10y|ytd|max
  "interval": "1d"       # 1m|2m|5m|15m|30m|60m|90m|1h|1d|5d|1wk|1mo|3mo
}
Output: JSON array of OHLCV objects:
  [ {"date":"2026-02-01","open":420.1,"high":425.5,
     "low":418.3,"close":423.7,"volume":22450000}, ... ]
```

#### `ticker-earning`

Returns earnings history and forward estimates.

```
Input:  {
  "symbol": "NVDA",
  "period": "annual",    # annual | quarterly
  "date":   null         # optional ISO date filter
}
Output: JSON object:
  {
    "symbol": "NVDA",
    "earnings_data": [
      {"year": 2024, "revenue": 60922000000, "earnings": 29760000000}
    ],
    "upcoming_earnings": {
      "date": "2026-05-28",
      "eps_estimate": 0.89,
      "eps_reported": null
    },
    "trailing_eps": 2.94,
    "forward_eps": 3.20,
    "trailing_pe": 45.2,
    "forward_pe": 38.7
  }
```

### Async Pattern

All three tools wrap yfinance (synchronous) with `asyncio.get_event_loop().run_in_executor(None, ...)` to avoid blocking the FastMCP event loop:

```python
@mcp.tool()
async def get_ticker_info(symbol: str) -> str:
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, _fetch_ticker_info, symbol)
    return json.dumps(data)
```

### Error Handling

On any exception, tools return a JSON error object instead of raising:

```json
{ "symbol": "INVALID", "error": "No data found for symbol INVALID" }
```

---

## MCP Configuration (`mcp_config.py`)

The `make_finance_toolset()` factory creates an `McpToolset` with a filtered tool list:

```python
def make_finance_toolset(tool_filter: list[str]) -> McpToolset:
    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command="python",
                args=["-m", "stock_agent.finance_mcp_server"],
                env={
                    "PYTHONPATH": str(project_root),
                    **os.environ
                },
            )
        ),
        tool_filter=tool_filter,
    )
```

Each agent requests only the tools it needs:

| Agent                   | Tool filter                                      |
|-------------------------|--------------------------------------------------|
| `price_agent`           | `["get-ticker-info"]`                            |
| `alert_agent`           | `["get-ticker-info"]`                            |
| `financial_report_agent`| `["get-ticker-info", "ticker-earning"]`          |
| `visualization_agent`   | `["get-ticker-info", "get-price-history"]`       |
| `prediction_agent`      | *(no MCP tools — uses direct Python)*            |
| `tenk_agent`            | *(no MCP tools — uses direct Python)*            |

Filtering prevents agents from calling tools they should not use and reduces the LLM's tool selection surface area.

---

## RAG MCP Server (Dormant)

**File**: `stock_agent/rag_mcp_server.py`
**Entry point**: `python -m stock_agent.rag_mcp_server`

This server wraps `list_indexed_companies` and `search_10k` as MCP tools with identical schemas. It exists for completeness but is **not used by production agents** because:

> The `all-MiniLM-L6-v2` embedding model takes ~3–8 seconds to load on first use. MCP subprocess startup times out at ~5 seconds in ADK. By the time the subprocess is ready the agent's first tool call has already failed.

**Workaround**: RAG tools (`list_indexed_companies`, `search_10k`) are imported directly into `tenk_agent` and `comparison_insights_agent` as Python function tools. The embedding model is pre-warmed in a daemon thread at module import time using a `threading.Event` (`_init_done`), so the first `search_10k` call blocks only until initialization completes.

---

## Direct Python vs MCP — Decision Table

| Criterion             | MCP (subprocess)        | Direct Python           |
|-----------------------|-------------------------|-------------------------|
| Startup time          | ~200 ms (Python import) | Instant (shared process)|
| Isolation             | Full process isolation  | Same process            |
| Blocking risk         | Run in executor         | Run in ADK thread pool  |
| Suitable for          | Stateless, fast APIs    | Heavy initialization    |
| Examples              | yfinance (fast)         | ChromaDB + embeddings   |

---

## Tool Call Message Flow

**Query**: price_agent calls `get-ticker-info("MSFT")`

```
price_agent (ADK, in-process)
    │
    ├─► before_tool_callback fires
    │     audit.log: {"event":"tool_start","tool":"get-ticker-info","args":{"symbol":"MSFT"}}
    │     tracing._metrics[inv_id]["tool_spans"].append({"name":"get-ticker-info","succeeded":None})
    │
    ├─► McpToolset sends JSON-RPC over stdin to finance_mcp_server subprocess:
    │     {"jsonrpc":"2.0","method":"tools/call",
    │      "params":{"name":"get-ticker-info","arguments":{"symbol":"MSFT"}}}
    │
    ├─► finance_mcp_server.get_ticker_info("MSFT")
    │     run_in_executor → yf.Ticker("MSFT").info
    │     Convert timestamps → JSON string
    │
    ├─► Response arrives back via stdout:
    │     {"jsonrpc":"2.0","result":{"content":[{"type":"text","text":"{...}"}]}}
    │
    ├─► ADK unwraps result; passes dict to LLM as function_response
    │
    └─► after_tool_callback fires
          tracing._metrics[inv_id] span marked succeeded=True
          audit.log: {"event":"tool_end","tool":"get-ticker-info","result_status":"success"}
```
