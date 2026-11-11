# Comparison Pipeline

## Overview

The `STOCK_COMPARISON` pipeline uses **two sequential agents** to compare multiple stocks:

1. **`comparison_trend_agent`** — fetches multi-year price trends, renders a comparison chart, outputs a trend table
2. **`comparison_insights_agent`** — reads the trend table from conversation history, performs targeted 10-K RAG searches per company, writes insight paragraphs and a comparative narrative

The pipeline was refactored from a single `comparison_agent` (still in codebase for reference) into two specialised agents to avoid token budget exhaustion when combining chart rendering, price trend data, and RAG search in one LLM context.

---

## Pipeline Diagram

```
User query: "Compare MSFT and NVDA over 1 year"
    │
    ▼
comparison_trend_agent
    ├─ resolve_ticker (all companies)
    ├─ fetch_price_trends([MSFT, NVDA])
    │    → multi-period % changes
    ├─ render_comparison_trend_chart([MSFT, NVDA])
    │    → PNG chart (not copied to text response)
    └─ Outputs: trend table (markdown)
         ──► Streamed to user

         ↓ (conversation history carries trend table forward)

comparison_insights_agent
    ├─ Reads trend table from history
    ├─ list_indexed_companies()              → confirm which companies have indexed 10-K data
    ├─ Classifies each company by trend direction
    ├─ search_10k(company, query_based_on_trend) — once per company
    └─ Outputs: per-company paragraphs + comparative summary
         ──► Streamed to user
```

---

## comparison_trend_agent

### Configuration

| Field                | Value                                     |
|----------------------|-------------------------------------------|
| Name                 | `comparison_trend_agent`                  |
| Model                | `gemini-2.5-flash`                        |
| Direct Python tools  | `resolve_ticker`, `fetch_price_trends`, `render_comparison_trend_chart` |

### Tool: `fetch_price_trends(tickers: list[str]) -> dict`

Fetches 5 years of daily history (yfinance) and computes percentage changes over 6 time windows in one call:

```
Input:  ["MSFT", "NVDA"]
Output: {
  "MSFT": {
    "current_price": 425.30,
    "company_name":  "Microsoft Corporation",
    "changes": { "1W": 0.8, "1M": 3.2, "3M": 8.4, "YTD": 12.1, "1Y": 28.5, "5Y": 187.3 },
    "trends":  { "1W": "up", "1M": "up", "3M": "up", "YTD": "up", "1Y": "up", "5Y": "up" }
  },
  "NVDA": {
    "current_price": 887.60,
    "changes": { "1W": 2.1, "1M": -4.3, "3M": 18.7, "YTD": 31.2, "1Y": 196.4, "5Y": 1840.2 },
    "trends":  { "1W": "up", "1M": "down", "3M": "up", "YTD": "up", "1Y": "up", "5Y": "up" }
  }
}
```

Period calculations use trailing trading days: 5 (1W), 21 (1M), 63 (3M), 252 (1Y), 1260 (5Y). YTD uses the first trading day of the current calendar year.

### Tool: `render_comparison_trend_chart`

Renders normalised cumulative return curves for all companies on one chart — each series starts at 0% on the left edge and shows how it grew or shrank from that baseline. Uses the same 5-year history fetched by `fetch_price_trends`.

```
Output: "![MSFT vs NVDA](data:image/png;base64,...)"
(chart displayed via tool response; NOT copied into LLM text)
```

### Trend Table Output

```
| Company   | Ticker | Price    |  1W   |  1M   |  3M   | YTD   |  1Y   |  5Y    |
|-----------|--------|----------|-------|-------|-------|-------|-------|--------|
| Microsoft | MSFT   | $425.30  | ▲0.8% | ▲3.2% | ▲8.4% | ▲12.1%| ▲28.5%|▲187.3% |
| NVIDIA    | NVDA   | $887.60  | ▲2.1% | ▼4.3% | ▲18.7%| ▲31.2%|▲196.4%|▲1840.2%|
```

---

## comparison_insights_agent

### Configuration

| Field                | Value                                    |
|----------------------|------------------------------------------|
| Name                 | `comparison_insights_agent`              |
| Model                | `gemini-2.5-flash`                       |
| Direct Python tools  | `resolve_ticker`, `list_indexed_companies`, `search_10k`           |

### RAG Query Selection by Trend

The agent classifies each company's trend and chooses a targeted RAG query:

| Trend direction | Query used                                |
|-----------------|-------------------------------------------|
| Strong up       | `"revenue growth competitive advantage"`  |
| Moderate up     | `"revenue growth competitive advantage"`  |
| Flat            | `"business strategy growth initiatives"`  |
| Moderate down   | `"risk factors market headwinds"`         |
| Strong down     | `"risk factors market headwinds"`         |

This ensures each search is contextually relevant to why the stock moved as it did.

### One-Call-Per-Company Constraint

The system prompt enforces a maximum of **one `search_10k` call per company** to prevent context budget exhaustion in multi-stock comparisons. With 3–5 companies, unconstrained searches could consume the entire context window.

---

## Message Flow: Full E2E Comparison

**Query**: "Compare MSFT and NVDA — which is the better long-term investment?"

```
stock_orchestrator
    ├─► intent_agent → {
    │     "intent": "STOCK_COMPARISON",
    │     "companies": ["MSFT", "NVDA"]
    │   }
    │
    ├─► comparison_trend_agent
    │     │
    │     ├─► resolve_ticker("MSFT") → "MSFT"
    │     ├─► resolve_ticker("NVDA") → "NVDA"
    │     │
    │     ├─► fetch_price_trends(["MSFT","NVDA"])
    │     │     yf.download each ticker, period="5y"
    │     │     Compute 6 period changes each
    │     │     Returns compact dict (no raw OHLCV arrays)
    │     │
    │     ├─► render_comparison_trend_chart(["MSFT","NVDA"])
    │     │     Normalised cumulative return chart
    │     │     → PNG embed (displayed via tool; NOT in text)
    │     │
    │     └─► LLM outputs:
    │           [chart already displayed above]
    │
    │           | Company   | Ticker | Price    |  1W   |  1Y    |  5Y     |
    │           |-----------|--------|----------|-------|--------|---------|
    │           | Microsoft | MSFT   | $425.30  | ▲0.8% | ▲28.5% | ▲187.3% |
    │           | NVIDIA    | NVDA   | $887.60  | ▲2.1% | ▲196.4%|▲1840.2% |
    │
    └─► comparison_insights_agent
          │
          │ (reads trend table from conversation history)
          ├─► list_indexed_companies()
          │     → confirms MSFT and NVDA are indexed ✓
          │ MSFT: strong up → query "revenue growth competitive advantage"
          │ NVDA: strong up → query "revenue growth competitive advantage"
          │
          ├─► search_10k("MSFT", "revenue growth competitive advantage", n_results=3)
          │     → passages on Azure cloud growth, Copilot AI momentum, Office 365
          │
          ├─► search_10k("NVDA", "revenue growth competitive advantage", n_results=3)
          │     → passages on data center GPU demand, CUDA moat, AI training market
          │
          └─► LLM outputs:
                **Microsoft (MSFT) — Upward trend (+28.5% 1Y)**
                According to Microsoft's 10-K, Azure revenue grew 29% year-over-year
                driven by AI workloads integrated with Copilot. The company's
                diversification across cloud, productivity, and gaming reduces
                single-product concentration risk.

                **NVIDIA (NVDA) — Strong upward trend (+196.4% 1Y)**
                NVIDIA's 10-K highlights data center revenue of $47.5B, up 217%
                year-over-year, reflecting surging demand for H100/H200 GPUs.
                The CUDA software ecosystem creates high switching costs...

                **Comparative Summary**
                Both companies show strong multi-year performance, but NVIDIA's
                growth is driven by a single high-demand category (AI GPUs), while
                Microsoft's diversification provides more stable compounding...

                *Disclaimer: This is not investment advice.*
```

---

## Notes

- `comparison_trend_agent` explicitly must NOT copy chart markdown into its text response — the chart renders automatically from the tool response. Copying the ~50KB base64 string caused a `MAX_TOKENS` (65K output tokens) error that previously broke this pipeline.
- The two-agent split keeps each LLM context focused: trend agent only handles price math and chart rendering; insights agent only handles RAG synthesis.
- `comparison_agent.py` remains in the codebase as the original unified implementation. It is not in the active `_ROUTE_MAP` and is retained for reference only.
