# Visualization Agent

## Purpose

Renders inline charts as base64-encoded PNG images embedded in Markdown. Supports four chart types: price history, prediction overlay, multi-stock comparison, and financial metrics. All chart tools are one-shot — they fetch data and render the image internally to avoid passing large OHLCV arrays through the LLM context.

---

## Configuration

| Field                | Value                                |
|----------------------|--------------------------------------|
| Name                 | `visualization_agent`                |
| Model                | `gemini-2.5-flash`                   |
| Runs in pipelines    | `VISUALIZATION`, `PRICE_PREDICT_CHART` |
| Direct Python tools  | `resolve_ticker`, `render_price_chart_for_ticker`, `render_prediction_chart_for_ticker`, `render_comparison_chart_for_tickers`, `render_financial_chart_for_ticker` |
| MCP tools            | _(none — all data fetched inside one-shot wrappers)_ |

---

## Chart Types

### 1. Price History (`render_price_chart_for_ticker`)

3-month daily price history as a line chart.

```
Input:  { "ticker": "AAPL" }
Output: "![AAPL Price History](data:image/png;base64,iVBORw0KGgo...)"

Data flow (internal to the tool):
  yf.download("AAPL", period="3mo", interval="1d")  → OHLCV data
  Extract dates[] and close prices[]
  yf.Ticker("AAPL").info["shortName"]               → "Apple Inc."
  render_price_chart(ticker, dates, prices, company_name)
    → matplotlib dark-themed line chart
    → base64 PNG embed in markdown image tag
```

This tool is fully self-contained — raw OHLCV arrays never pass through the LLM context.

### 2. Prediction Overlay (`render_prediction_chart_for_ticker`)

Historical price line + linear regression forecast line with confidence band.

```
Input:  { "ticker": "NVDA" }
Output: "![NVDA Forecast](data:image/png;base64,...)"

Data flow (internal to the tool):
  yf.download("NVDA", period="3mo")  → historical closes
  OLS regression                     → 14-day forecast
  matplotlib: historical line (solid) + forecast line (dashed)
             + shaded confidence band (±1 std dev)
  → base64 PNG embed
```

This tool is fully self-contained — it takes only the ticker symbol and produces the chart without any intermediate data passing through the LLM.

### 3. Comparison Bar Chart (`render_comparison_chart_for_tickers`)

Multi-stock daily percentage change as a horizontal bar chart, sorted best performer to worst.

```
Input:  { "tickers": ["MSFT","AAPL","NVDA"],
          "company_names": ["Microsoft","Apple","NVIDIA"] }   ← optional
Output: "![Comparison](data:image/png;base64,...)"

Data flow (internal to the tool):
  for each ticker:
    yf.Ticker(ticker).fast_info → last_price, previous_close
    pct_change = (last_price - previous_close) / previous_close × 100
  render_comparison_chart(tickers, change_percents, company_names)
    → green bars (positive) / red bars (negative)
    → sorted descending by change %
    → base64 PNG embed
```

Raw ticker-info JSON never passes through the LLM context.

### 4. Financial Metrics Charts (`render_financial_chart_for_ticker`)

Two-panel chart: absolute dollar metrics (revenue, gross profit, net income) as a bar chart, and percentage margins as a line chart.

```
Input:  { "ticker": "MSFT" }
Output: "![MSFT Financials](data:image/png;base64,...)"

Data flow (internal to the tool):
  yf.Ticker("MSFT").info → revenue, grossProfit, netIncomeToCommon,
                            operatingMargins, grossMargins, profitMargins,
                            shortName, mostRecentQuarter
  income_metrics = {Revenue, Gross Profit, Net Income}   (÷1 000 000 → $M)
  margin_metrics  = {Gross Margin, Operating Margin, Net Margin} (×100 → %)
  render_financial_chart(ticker, income_metrics, margin_metrics, company_name, fiscal_year)
    → two-panel matplotlib chart (bars + lines)
    → base64 PNG embed
```

The 50+ field `yf.Ticker.info` dict never enters LLM context.

---

## Workflow

```
visualization_agent
    │
    ├─ Step 1: Determine chart type from conversation context / intent JSON
    │
    ├─ Step 2a (price history):
    │     resolve_ticker → render_price_chart_for_ticker
    │     (yf.download + chart rendered internally)
    │
    ├─ Step 2b (prediction):
    │     resolve_ticker → render_prediction_chart_for_ticker
    │     (yf.download + OLS forecast + chart rendered internally)
    │
    ├─ Step 2c (comparison):
    │     resolve_ticker (each) → render_comparison_chart_for_tickers
    │     (fast_info fetched internally for each ticker)
    │
    ├─ Step 2d (financial):
    │     resolve_ticker → render_financial_chart_for_ticker
    │     (yf.Ticker.info fetched and parsed internally)
    │
    └─ Step 3: LLM writes a one-sentence caption.
          The chart is already displayed to the user via the ADK event stream.
          The LLM never sees the base64 data — after_tool_callback strips it.
```

---

## Base64 Context Isolation

Chart tools return a dict containing a `"markdown"` field with a base64-encoded PNG (≈50 KB). If this reaches the LLM as a tool response, Gemini must tokenise ~170K tokens of base64 as input — causing a hang before it generates a single output token.

**Two-layer defence:**

**Layer 1 — `after_tool_callback` (in `audit.py`)**

For any tool in `_CHART_RENDER_TOOLS`, the callback strips the `"markdown"` field from the tool response before it is appended to the LLM's conversation context. The LLM only sees `{"status": "success", "title": "..."}`.

The full response (with image) was already emitted to the ADK event stream and displayed in the UI before the callback fires — the user sees the chart; the LLM does not.

```
render_price_chart_for_ticker("AAPL")
  └─ returns {"status":"success","title":"AAPL Price History","markdown":"![...](base64 50KB)"}
        │
        ├──► ADK event stream ──► frontend renders image  ✓
        │
        └──► after_tool_callback strips "markdown"
               │
               └──► LLM context receives {"status":"success","title":"AAPL Price History"}
                      ~20 tokens, no hang  ✓
```

**Layer 2 — System prompt instruction**

The agent instruction says "The chart is already displayed to the user. Write a one-sentence caption only." This prevents the LLM from attempting to re-emit image markdown it never received, and keeps the caption response short.

---

## Message Flow: Price History Chart

**Query**: "Show me a 3-month price chart for Apple"

```
stock_orchestrator
    ├─► intent_agent → { "intent": "VISUALIZATION", "companies": ["AAPL"],
    │                     "chart_type": "price_history" }
    └─► visualization_agent
          │
          ├─► resolve_ticker("Apple") → "AAPL"
          │
          ├─► render_price_chart_for_ticker("AAPL")
          │     ┌─ internal ──────────────────────────────────────────┐
          │     │  yf.download("AAPL", period="3mo") → 63 OHLCV rows │
          │     │  extract dates[], close prices[]                    │
          │     │  yf.Ticker("AAPL").info["shortName"] → "Apple Inc." │
          │     │  render_price_chart(...)                            │
          │     │    → matplotlib dark theme line chart               │
          │     │    → {status, title, markdown: "![...](base64)"}    │
          │     └─────────────────────────────────────────────────────┘
          │
          │     after_tool_callback (audit.py):
          │       ├──► ADK event stream → frontend displays image  ✓
          │       └──► strips "markdown" → LLM gets {status, title}
          │
          └─► LLM text response (caption only):
                "This chart shows the 3-month price history for Apple (AAPL)."
```

---

## Notes

- All chart tools use a **dark matplotlib theme** for visual consistency.
- All four chart tools are one-shot wrappers: they accept only a ticker symbol (and optional args), fetch all required data internally, and produce a base64 PNG. Raw OHLCV arrays, ticker-info dicts, and computed forecasts never appear in LLM context.
- The base64 PNG in the tool response is additionally stripped by `after_tool_callback` in `audit.py` before it reaches the LLM — preventing a Gemini hang caused by tokenising ~170K tokens of base64 as input. See the Base64 Context Isolation section above.
- In the `PRICE_PREDICT_CHART` pipeline, the LLM context includes the price summary from `price_agent` and the forecast table from `prediction_agent` before `visualization_agent` runs — the visualization agent uses this history to know what chart to draw.
