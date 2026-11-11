# Financial Report Agent

## Purpose

Generates a structured financial analysis for a software-sector company covering Income Statement, Balance Sheet, Cash Flow, and Valuation Ratios. The agent is dual-use: it runs as a direct sub-agent in the `FINANCIAL_REPORT` and `ANNUAL_FINANCIAL` pipelines, and as a standalone A2A service for the PDF agent.

---

## Configuration

| Field                | Value                                                            |
|----------------------|------------------------------------------------------------------|
| Name                 | `financial_report_agent`                                         |
| Model                | `gemini-2.5-flash`                                               |
| Runs in pipelines    | `FINANCIAL_REPORT`, `ANNUAL_FINANCIAL`                           |
| Also exposed via     | A2A at `http://localhost:8001/a2a/financial_report_agent`        |
| Direct Python tools  | `resolve_ticker`                                                 |
| MCP tools            | `get-ticker-info`, `ticker-earning`                              |

---

## Tool Descriptions

### `get-ticker-info` (MCP)

Provides all financial ratio and metric data needed for the report:
- Revenue, gross profit, operating profit, net income
- Gross margin, operating margin, profit margin
- Total debt, total cash, debt-to-equity ratio
- P/E (trailing & forward), P/S, P/B, EV/EBITDA, PEG ratio
- Return on equity, trailing EPS, forward EPS

### `ticker-earning` (MCP)

Provides earnings history and analyst estimates:
- Year-over-year revenue and earnings (annual or quarterly)
- Upcoming earnings date and EPS estimate vs reported
- Trailing and forward EPS and PE

---

## Report Sections

```
Financial Report: Microsoft (MSFT)
Fiscal Year: 2025

─────────────────────────────────────────
INCOME STATEMENT
  Revenue:         $245.1B
  Gross Profit:    $166.2B  (67.8% gross margin)
  Operating Income: $112.0B  (45.7% operating margin)
  Net Income:       $88.1B   (36.0% net margin)
  YoY Revenue Growth: +16.0%

─────────────────────────────────────────
BALANCE SHEET
  Cash & Equivalents: $71.6B
  Total Debt:         $47.2B
  Debt-to-Equity:     0.41x
  Net Cash Position:  +$24.4B (net cash)

─────────────────────────────────────────
CASH FLOW
  Operating Cash Flow: $118.5B
  Capital Expenditures: $44.5B
  Free Cash Flow:        $74.0B

─────────────────────────────────────────
VALUATION RATIOS
  P/E (trailing):  35.4x
  P/E (forward):   31.2x
  P/S:              14.2x
  P/B:              12.8x
  EV/EBITDA:        25.1x
  EPS (trailing):  $11.98

─────────────────────────────────────────
OVERALL ASSESSMENT
  [3–4 sentence qualitative summary]

Disclaimer: This is not investment advice.
```

---

## Workflow

```
financial_report_agent
    │
    ├─ Step 1: resolve_ticker(company)
    │
    ├─ Step 2: get-ticker-info(ticker)
    │     Fetch all financial metrics (one MCP call)
    │
    ├─ Step 3: ticker-earning(ticker, period="annual")
    │     Fetch earnings history and forward estimates
    │
    └─ Step 4: LLM synthesises report
          • Four sections with bold headers
          • Monetary values in B (billions) or T (trillions)
          • YoY growth rates where available
          • Overall assessment paragraph
          • Mandatory disclaimer appended
```

---

## Message Flow: Direct Pipeline

**Query**: "Give me Apple's financial report"

```
stock_orchestrator
    ├─► intent_agent → { "intent": "FINANCIAL_REPORT", "companies": ["AAPL"] }
    └─► financial_report_agent
          │
          ├─► resolve_ticker("Apple") → "AAPL"
          │
          ├─► get-ticker-info("AAPL")
          │     → { totalRevenue: 391.0B, grossMargins: 0.462, profitMargins: 0.263,
          │         totalDebt: 96.8B, totalCash: 67.2B, debtToEquity: 141.9,
          │         trailingPE: 33.1, forwardPE: 29.8, trailingEps: 6.43, ... }
          │
          ├─► ticker-earning("AAPL", period="annual")
          │     → { earnings_data: [{year: 2024, revenue: 391.0B, earnings: 93.7B}],
          │         trailing_eps: 6.43, forward_eps: 7.18 }
          │
          └─► LLM formats full four-section report with disclaimer
```

## Notes

- Monetary values use B (billions) or T (trillions) for readability — never raw numbers like 245100000000.
- The disclaimer ("This is not investment advice") is always appended as the final line.
- In the `ANNUAL_FINANCIAL` compound pipeline, `tenk_agent` runs first (10-K RAG search) and `financial_report_agent` follows, giving users both qualitative filing insights and quantitative metrics in a single response.
- `pdf_agent` previously delegated to `financial_report_agent` via A2A (HTTP POST to port 8001). As of May 2026, `pdf_agent` was decoupled and now fetches financial data directly via MCP tools, building a brief `financial_summary` string itself. `financial_report_agent` is no longer called by `pdf_agent`.
