# 10-K Agent (tenk_agent)

## Purpose

Answers questions about SEC 10-K annual filings using Retrieval-Augmented Generation (RAG). Retrieves semantically relevant passages from an indexed ChromaDB collection and synthesises answers with citations. For international companies that file 20-F forms, the same mechanism applies.

---

## Configuration

| Field                | Value                                                         |
|----------------------|---------------------------------------------------------------|
| Name                 | `tenk_agent`                                                  |
| Model                | `gemini-2.5-flash`                                            |
| Runs in pipelines    | `ANNUAL_REPORT`, `ANNUAL_FINANCIAL`                           |
| Direct Python tools  | `resolve_ticker`, `list_indexed_companies`, `search_10k`      |
| MCP tools            | None (RAG tools use direct Python — see below)                |

---

## Why No MCP for RAG

The `all-MiniLM-L6-v2` sentence transformer takes 3–8 seconds to load. MCP subprocess timeout in ADK is ~5 seconds. The first tool call would fail before the model is ready. Instead, RAG tools are imported as direct Python tools. The embedding model is pre-warmed in a daemon thread at module import time so it is ready before the first agent query.

---

## Tools

### `list_indexed_companies() -> dict`

Returns all companies with indexed 10-K data in ChromaDB.

```
Output: {
  "indexed_companies": [
    { "ticker": "MSFT", "chunks": 142 },
    { "ticker": "GOOGL", "chunks": 138 },
    { "ticker": "AAPL",  "chunks": 119 },
    ...
  ]
}
```

Used to confirm whether a company has filings before attempting a search.

### `search_10k(ticker: str, query: str, n_results: int = 3) -> dict`

Performs a semantic vector search over indexed 10-K chunks for a given company.

```
Input:  { "ticker": "SNOW", "query": "revenue growth strategy", "n_results": 6 }
Output: {
  "status": "success",
  "ticker": "SNOW",
  "results": [
    {
      "chunk_index": 47,
      "form": "10-K",
      "relevance": 0.847,
      "text": "Snowflake's product revenue grew 38% year-over-year driven by..."
    },
    ...  (up to 6 passages)
  ]
}
```

Relevance = `1 - cosine_distance` (0–1 scale, higher is more relevant). `n_results` is clamped to 1–20.

---

## Multi-Query Strategy

For complex questions, the agent breaks the query into focused sub-queries:

```
User: "What are Snowflake's main risks and how is their revenue growing?"

Agent calls:
  search_10k("SNOW", "risk factors regulatory competitive",    n_results=3)
  search_10k("SNOW", "revenue growth strategy product",       n_results=3)
```

Each sub-query targets a specific aspect, improving relevance over a single broad query. The agent makes at most **3 `search_10k` calls total** across all sub-queries to stay within the context budget. Each call always uses `n_results=3`.

---

## Citation Pattern

Responses always cite the section of the filing from which information was drawn:

```
"According to the Risk Factors section of Snowflake's 10-K:
 'The markets in which we operate are intensely competitive...'

 In the MD&A section:
 'Product revenue of $3.2B represented 95% of total revenue...'"
```

---

## Workflow

```
tenk_agent
    │
    ├─ Step 1: list_indexed_companies()
    │     Confirm the requested company is in the index
    │     If not indexed: tell user which companies are available
    │
    ├─ Step 2: resolve_ticker(company_name)
    │     Get canonical ticker
    │
    ├─ Step 3: search_10k(ticker, query, n_results=3)
    │     For complex queries: decompose into sub-queries and call multiple times
    │     Collect passages
    │
    └─ Step 4: LLM synthesises answer
          • Cite source section (Risk Factors, MD&A, Business, etc.)
          • Note the form type (10-K or 20-F for international filers)
          • Include informational disclaimer
```

---

## Message Flow

**Query**: "What are the key risk factors in Snowflake's annual report?"

```
stock_orchestrator
    ├─► intent_agent → { "intent": "ANNUAL_REPORT", "companies": ["SNOW"] }
    └─► tenk_agent
          │
          ├─► list_indexed_companies()
          │     → [MSFT, GOOGL, AAPL, NVDA, META, CRM, ADBE, NOW, SNOW, CRWD, SAP, ...]
          │     Confirms SNOW is indexed ✓
          │
          ├─► resolve_ticker("Snowflake") → "SNOW"
          │
          ├─► search_10k("SNOW", "risk factors regulatory competitive", n_results=3)
          │     ChromaDB cosine similarity search
          │     → 3 passages with relevance scores 0.71–0.89
          │       [ {form:"10-K", section:"Risk Factors",
          │          text:"We operate in competitive markets...", relevance:0.89},
          │         {form:"10-K", section:"Risk Factors",
          │          text:"We are subject to cybersecurity threats...", relevance:0.83},
          │         ... ]
          │
          └─► LLM synthesises:
                "According to Snowflake's 10-K annual report, the key risk factors include:

                 1. **Competitive Landscape** (Risk Factors section):
                    'We operate in highly competitive markets including Amazon Redshift,
                    Google BigQuery, and Microsoft Fabric...'

                 2. **Cybersecurity** (Risk Factors section):
                    'We are subject to cybersecurity threats that could disrupt
                    our services...'

                 Source: Snowflake Inc. Form 10-K, FY2025.
                 This is informational only and not investment advice."
```

---

## Message Flow: ANNUAL_FINANCIAL Compound Pipeline

**Query**: "Give me Snowflake's 10-K insights and financial report"

```
stock_orchestrator
    ├─► intent_agent → { "intent": "ANNUAL_FINANCIAL", "companies": ["SNOW"] }
    │
    ├─► tenk_agent (runs first)
    │     ... (as above, produces 10-K passages + synthesised answer)
    │     Streams 10-K analysis to user
    │
    └─► financial_report_agent (runs second, sees tenk_agent output in history)
          resolve_ticker + get-ticker-info + ticker-earning
          Streams quantitative financial report to user

User sees: qualitative 10-K insights followed by quantitative financial metrics
```
