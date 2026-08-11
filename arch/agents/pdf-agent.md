# PDF Agent

## Purpose

Compiles a comprehensive, downloadable PDF report for a single stock. The report bundles current price, 90-day price chart, 14-day forecast, financial metrics, and drop-alert status into a single ReportLab document. Financial data is fetched directly via MCP tools — no external service required.

---

## Configuration

| Field                | Value                                                                  |
|----------------------|------------------------------------------------------------------------|
| Name                 | `pdf_agent`                                                            |
| Model                | `gemini-2.5-flash`                                                     |
| Runs in pipeline     | `PDF_REPORT`                                                           |
| Direct Python tools  | `resolve_ticker`, `compile_pdf_report`                                 |
| MCP tools            | `get-ticker-info`, `ticker-earning`                                    |
| Sub-agents           | None                                                                   |

---

## Tool: `compile_pdf_report`

```python
compile_pdf_report(
    ticker_or_name:          str,
    financial_summary:       str,    # 2–4 sentence narrative built from MCP data
    include_prediction:      bool = True,
    include_financials:      bool = True,
    include_alerts:          bool = True,
    alert_threshold_percent: float = 5.0,
) -> dict   # { "message": "...", "file_path": "/output/MSFT_report_20260502.pdf" }
```

Internally this tool:
1. Fetches current price and 90-day OHLCV history (yfinance)
2. Renders 90-day price history chart (matplotlib PNG)
3. If `include_prediction`: runs OLS forecast, renders prediction chart, builds forecast table
4. If `include_financials`: fetches key metrics (yfinance), renders financial metrics chart
5. If `include_alerts`: evaluates drop alert against threshold
6. Assembles all sections into a ReportLab PDF
7. Saves to `/output/{TICKER}_report_{timestamp}.pdf`
8. Returns file path

---

## PDF Report Structure

```
┌─────────────────────────────────────────────────────┐
│  [HEADER]  Stock Analysis Report — MSFT              │
│            Microsoft Corporation   2026-05-02        │
├─────────────────────────────────────────────────────┤
│  Current Price     $425.30  ↑ +1.24%                │
│  Market Cap        $3.16T                            │
├─────────────────────────────────────────────────────┤
│  [CHART]  90-Day Price History                       │
│           (matplotlib dark line chart, embedded PNG) │
├─────────────────────────────────────────────────────┤
│  [CHART]  14-Day Forecast                            │
│           (historical + OLS projection, dashed line) │
│                                                      │
│  Forecast Table: date | predicted price (14 rows)    │
├─────────────────────────────────────────────────────┤
│  [SECTION]  Financial Summary (if include_financials)│
│             Narrative built by pdf_agent from MCP    │
│             (income statement, balance sheet, etc.)  │
│                                                      │
│  [CHART]  Financial Metrics Chart                    │
│           (revenue / margins bars)                   │
├─────────────────────────────────────────────────────┤
│  [SECTION]  Drop Alert Status (if include_alerts)    │
│             Threshold: 5%                            │
│             Status: SAFE ✅  / ALERT 🚨              │
├─────────────────────────────────────────────────────┤
│  Disclaimer: Not investment advice.                  │
└─────────────────────────────────────────────────────┘
```

---

## Workflow

```
pdf_agent
    │
    ├─ Step 1: resolve_ticker(company_name)
    │     Get canonical ticker (e.g. "Microsoft" → "MSFT")
    │
    ├─ Step 2: get-ticker-info(ticker)   [MCP]
    │     Fetches current price, market cap, P/E ratio, revenue,
    │     operating margin, total debt, and other key metrics
    │
    ├─ Step 3: ticker-earning(ticker)    [MCP]
    │     Fetches quarterly earnings history
    │
    ├─ Step 4: Build financial_summary string
    │     2–4 sentences from steps 2–3 data.
    │     Example: "MSFT reported TTM revenue of $245B with a 45% operating
    │     margin. P/E ratio is 32x. Earnings have grown for 6 consecutive quarters."
    │
    └─ Step 5: compile_pdf_report(ticker, financial_summary, options)
          → Fetches price + OHLCV internally (yfinance)
          → Runs OLS forecast
          → Renders 3 charts (price history, forecast, financials)
          → Evaluates drop alert
          → ReportLab → /output/*.pdf
          → Returns: {
              "status":       "success",
              "file_name":    "MSFT_report_20260502_114237.pdf",
              "file_path":    "/output/MSFT_report_20260502_114237.pdf",
              "download_url": "/api/downloads/MSFT_report_20260502_114237.pdf",
              "message":      "📄 PDF report for **Microsoft Corporation (MSFT)** is ready.\n\n[📥 Download MSFT_report_20260502_114237.pdf](/api/downloads/MSFT_report_20260502_114237.pdf)"
            }

LLM relays the `message` field unchanged. The frontend renders the markdown
link as an `<a>` tag; a delegated click handler in static/index.html
intercepts the click, fetches the file with the JWT, and triggers a real
browser download via a Blob URL — the file lands in the user's Downloads
folder. See arch/10-web-ui.md → "GET /api/downloads/{filename}".
```

---

## Message Flow

**Query**: "Generate a PDF report for SAP"

```
stock_orchestrator
    ├─► intent_agent → { "intent": "PDF_REPORT", "companies": ["SAP"] }
    └─► pdf_agent
          │
          ├─► resolve_ticker("SAP") → "SAP"
          │
          ├─► get-ticker-info("SAP")
          │     [MCP → yfinance]
          │     → { currentPrice: 220.40, marketCap: 271B, revenueGrowth: 9.4%,
          │         operatingMargin: 22.1%, trailingPE: 41.2, totalDebt: 10.2B, ... }
          │
          ├─► ticker-earning("SAP")
          │     [MCP → yfinance]
          │     → quarterly EPS for last 4 quarters
          │
          ├─► [LLM builds financial_summary]
          │     "SAP reported TTM revenue of €34.2B with a 22% operating margin.
          │      P/E ratio is 41x. Quarterly earnings have been stable."
          │
          └─► compile_pdf_report(
                  ticker_or_name="SAP",
                  financial_summary="SAP reported TTM revenue of €34.2B...",
                  include_prediction=True,
                  include_financials=True,
                  include_alerts=True,
                  alert_threshold_percent=5.0
              )
              │
              ├─ yf.download("SAP", period="3mo") → 90-day history
              ├─ render price history chart (PNG)
              ├─ OLS regression → 14-day forecast
              ├─ render forecast chart (PNG)
              ├─ fetch key metrics → render financial chart (PNG)
              ├─ evaluate_drop_alerts(SAP, 5.0) → safe
              ├─ ReportLab assembles PDF
              └─ Saves /output/SAP_report_20260501_143833.pdf

Final response: "📄 PDF report for SAP is ready. [📥 Download SAP_report_20260501_143833.pdf](...)"
```

---

## Output Directory

PDFs are saved to `/output/` at the project root:
```
/output/SAP_report_20260501_143833.pdf
/output/MSFT_report_20260502_114237.pdf
```
