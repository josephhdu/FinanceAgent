# Intent Extraction

## Overview

Intent extraction is the first step of every user turn. A dedicated `intent_agent` runs before the orchestrator decides which pipeline to invoke. The agent uses Gemini 2.5-flash to parse the user's query into a structured JSON object containing the intent type, extracted entities, and output preferences.

Critically, the intent agent runs **before guardrails block the query** so the orchestrator always has routing information even when the query is eventually rejected downstream.

---

## Design Principles

- **LLM-based NLP, Python-based routing**: The intent agent converts natural language to a structured schema; the orchestrator uses pure Python to act on it. Routing never relies on the LLM making a follow-up decision.
- **Single pass**: One LLM call extracts intent + all entities simultaneously — no chained calls.
- **Silent output**: The JSON response is consumed by the orchestrator and never shown to the user.
- **Bypass mode for eval**: `run_intent_extraction()` in `eval_harness.py` calls Gemini directly with the skill body, bypassing ADK entirely, so `transfer_to_agent` is never available and the model can only produce JSON.

---

## Intent Schema

```json
{
  "intent":                  "PRICE | PREDICTION | ALERT | FINANCIAL_REPORT |
                              VISUALIZATION | PDF_REPORT | ANNUAL_REPORT |
                              STOCK_COMPARISON | PRICE_PREDICTION |
                              PRICE_PREDICT_CHART | ANNUAL_FINANCIAL | TRADE_ANALYSIS | UNKNOWN",
  "companies":               ["MSFT", "AAPL"],
  "time_horizon":            "2 weeks | today | last 90 days | null",
  "metrics":                 ["revenue", "margins", "EPS"],
  "alert_threshold_percent": 5.0,
  "chart_type":              "price_history | prediction | comparison | financials | null",
  "output_format":           "pdf | text",
  "raw_query":               "<original user message>"
}
```

Companies are always normalised to uppercase ticker symbols (MSFT, AAPL, NVDA…).

---

## Intent Types and Trigger Conditions

| Intent              | Triggered when                                                          |
|---------------------|-------------------------------------------------------------------------|
| `PRICE`             | User asks for current price, daily change, market cap, sector overview  |
| `PREDICTION`        | User asks for forecast, projection, trend, prediction                   |
| `ALERT`             | User asks about drops, alerts, threshold breaches                       |
| `FINANCIAL_REPORT`  | User asks for financials, earnings, revenue, margins, balance sheet     |
| `VISUALIZATION`     | User explicitly requests a chart, graph, plot                           |
| `PDF_REPORT`        | User asks for a PDF or downloadable report                              |
| `ANNUAL_REPORT`     | User asks about 10-K, annual report, SEC filing, risk factors           |
| `STOCK_COMPARISON`  | User asks to compare two or more stocks by price trend                  |
| `PRICE_PREDICTION`  | Query combines current price AND forecast (no chart explicit)           |
| `PRICE_PREDICT_CHART`| Query combines current price AND forecast AND chart                   |
| `ANNUAL_FINANCIAL`  | Query combines 10-K filing insights AND financial report                |
| `TRADE_ANALYSIS`   | User asks to buy/sell a stock, get a trading recommendation, execute a paper trade, show portfolio, or view trade history |
| `UNKNOWN`           | Query cannot be mapped to any supported intent                          |

---

## Classification Priority Rules

The system prompt enforces a strict precedence order to resolve ambiguous queries:

```
Priority (highest → lowest):

0. PDF / export        → PDF_REPORT
   (if "PDF", "download", "export", "generate a report", or
    "save as a file" appears in the query — explicit output-format
    keywords override all topic-based rules below)

1. Trade requests       → TRADE_ANALYSIS
   (if "buy", "sell", "trade", "paper trade", "portfolio", "trade history" in query
    AND user is asking for a trading decision or mock execution)

2. Chart requests       → VISUALIZATION or PRICE_PREDICT_CHART
   (if "chart"/"graph"/"plot" in query)

3. Combined requests    → PRICE_PREDICTION / PRICE_PREDICT_CHART / ANNUAL_FINANCIAL
   (if query mentions two distinct capabilities)

4. 10-K / filing       → ANNUAL_REPORT
   (if query mentions "annual report", "10-K", "SEC", "filing", "risk factors")

5. Multi-stock trend   → STOCK_COMPARISON
   (if two or more tickers and comparison language)

6. Cross-section / multimodal report analysis → INVESTMENT_RESEARCH

7. Single-capability   → PRICE / PREDICTION / ALERT / FINANCIAL_REPORT

8. Fallback            → UNKNOWN
```

### Why PDF is at the top

Explicit output-format keywords ("export … as a PDF", "download a report") describe **how** the user wants the answer delivered, not **what** the answer is about. A query like *"Export a full analysis of AAPL as a PDF"* contains both an explicit format ("PDF") and a topic-ish word ("analysis") that previously matched TRADE_ANALYSIS — so the classifier mis-routed it to the trading agent, which has no PDF capability and refused.

Promoting PDF to priority 0 ensures the format always wins. The PDF agent then internally orchestrates whichever data agent (financial_report, trade_signals, etc.) is needed, rather than letting topic-based misclassification short-circuit the workflow.

---

## Skill Body (System Prompt Structure)

The `intent_agent`'s instruction is loaded from `skills/intent-extraction/SKILL.md`. Key sections:

```
# Role
You are a financial query classifier for a software-stock analysis assistant.

# Task
Extract the intent and all entities from the user query.
Always output a single JSON object — no prose, no markdown fences.

# Intent Types
[table of all 12 intents with trigger phrases]

# Entity Extraction Rules
- companies: resolve to ticker symbols; empty list if none mentioned
- time_horizon: standardise to "N days/weeks/months"; null if unspecified
- alert_threshold_percent: numeric; default null (agent uses 5.0 if null)
- chart_type: only set when chart is explicitly requested
- output_format: "pdf" if user says PDF/report/download, else "text"

# Classification Priority
[ordered rules as above]
```

---

## Eval Bypass Mode

For intent accuracy evaluation, `eval_harness.py` exposes `run_intent_extraction()`:

```python
def run_intent_extraction(question: str) -> str:
    skill_body = _load_skill_body("intent-extraction")   # reads skills/intent-extraction/SKILL.md
    client = Client(api_key=os.environ["GOOGLE_API_KEY"])
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=question,
        config=GenerateContentConfig(system_instruction=skill_body),
    )
    return response.text or ""
```

This bypasses ADK entirely — `transfer_to_agent` is never in the tool list and the model cannot escape the JSON-only instruction.

---

## Message Flow: Single Query

**Query**: "Compare the performance of Apple, Google, and NVIDIA"

```
eval_harness / ADK Web
    │
    ▼
intent_agent  (LlmAgent, no tools)
    │
    ├─ System instruction: skill body from skills/intent-extraction/SKILL.md
    ├─ User message: "Compare the performance of Apple, Google, and NVIDIA"
    │
    └─ Gemini 2.5-flash call
         │
         └─ Response:
            {
              "intent": "STOCK_COMPARISON",
              "companies": ["AAPL", "GOOGL", "NVDA"],
              "time_horizon": null,
              "metrics": [],
              "alert_threshold_percent": null,
              "chart_type": "comparison",
              "output_format": "text",
              "raw_query": "Compare the performance of Apple, Google, and NVIDIA"
            }

stock_orchestrator._route()
    │
    └─ pipeline = _ROUTE_MAP["STOCK_COMPARISON"]
                = [comparison_trend_agent, comparison_insights_agent]
```

---

## Message Flow: Ambiguous Combined Query

**Query**: "What's MSFT's price and give me a chart of the 2-week forecast"

```
intent_agent
    │
    ├─ Contains "price"  → would be PRICE alone
    ├─ Contains "forecast" → would be PREDICTION alone
    ├─ Contains "chart" → highest-priority trigger fires
    │
    └─ Output: { "intent": "PRICE_PREDICT_CHART", "companies": ["MSFT"],
                 "chart_type": "prediction", "output_format": "text" }

stock_orchestrator._route()
    └─ pipeline = [price_agent, prediction_agent, visualization_agent]
```

---

## Intent Accuracy Evaluation

The eval harness tests 33 intent cases covering all 11 categories (TRADE_ANALYSIS was added as a new category). For each case it checks:

| Check            | What it validates                                              |
|------------------|----------------------------------------------------------------|
| `intent`         | Exact match to expected intent string                          |
| `companies`      | All expected tickers appear in extracted list (subset match)   |
| `output_format`  | "pdf" vs "text" correctly identified                           |
| `alert_threshold`| Numeric threshold extracted correctly (when present)           |
| `chart_type`     | Chart type correctly identified (when present)                 |

A case passes only when **all applicable checks pass**.
