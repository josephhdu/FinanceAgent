# Accuracy Architecture — FinanceAI

**Version:** 1.0 | **Date:** 2026-05-06

This document describes every measure taken to ensure the accuracy, trustworthiness, and verifiability of FinanceAI responses. Accuracy is the top concern for users of any financial intelligence product — a wrong number, a stale figure, or a hallucinated claim can lead to real financial harm.

The system addresses accuracy across eight distinct layers: data integrity, RAG grounding, guardrails, forecast transparency, goal verification, cross-pipeline consistency, evaluation gating, and live feedback signals.

---

## Table of Contents

1. [Overview — Complete Accuracy Stack](#1-overview--complete-accuracy-stack)
2. [Data Integrity](#2-data-integrity)
3. [RAG Accuracy](#3-rag-accuracy)
4. [Guardrails — Six-Layer Safety Stack](#4-guardrails--six-layer-safety-stack)
5. [Forecast Transparency](#5-forecast-transparency)
6. [Goal Verification](#6-goal-verification)
7. [Cross-Pipeline Fact Consistency](#7-cross-pipeline-fact-consistency)
8. [Evaluation Gate](#8-evaluation-gate)
9. [Live Feedback & Production Signals](#9-live-feedback--production-signals)
10. [Observability & Audit Trail](#10-observability--audit-trail)
11. [Known Limitations](#11-known-limitations)

---

## 1. Overview — Complete Accuracy Stack

Every user query passes through the following layers in order. No layer can be bypassed by any agent.

```
┌─────────────────────────────────────────────────────────────┐
│  INPUT                                                       │
│  User injection check ──► out-of-scope ──► PII tokenise    │
│  Token limit ──► tool result injection scan                 │
├─────────────────────────────────────────────────────────────┤
│  DATA                                                        │
│  Live yfinance ──► NaN cleaned ──► timestamped             │
│  10-K RAG ──► relevance ≥ 0.40 ──► passage snippet cited  │
│  One-shot tools (OHLCV never in LLM context)               │
├─────────────────────────────────────────────────────────────┤
│  ROUTING                                                     │
│  Deterministic Python router ──► routing_decision audited  │
│  Company name confirmed in response (ticker validation)     │
├─────────────────────────────────────────────────────────────┤
│  GENERATION                                                  │
│  R² + confidence band on forecasts                          │
│  Cross-pipeline fact consistency check                      │
│  Multi-entity coverage enforced                             │
│  Disclaimer tracking on 9 agents                            │
├─────────────────────────────────────────────────────────────┤
│  OUTPUT VERIFICATION                                         │
│  Side-effect assertions (PDF, trade write)                  │
│  Pipeline handoff validation                                │
│  Runtime length check + async LLM judge (opt-in)           │
│  Output PII scan + advice disclaimer                        │
├─────────────────────────────────────────────────────────────┤
│  FEEDBACK                                                    │
│  👍/👎 per response ──► feedback.jsonl ──► thumbs-down rate│
│  goal_score events ──► audit.log ──► mean score dashboard  │
├─────────────────────────────────────────────────────────────┤
│  EVAL GATE                                                   │
│  22 E2E cases (incl. adversarial) ──► blocks regression    │
│  Model version pinned + logged on every call               │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Data Integrity

### The Problem
LLMs can confabulate financial figures from training data. A model that "knows" Apple's 2023 revenue can fabricate a 2025 number that sounds plausible but is completely wrong. Additionally, financial APIs frequently return missing or malformed fields for smaller or newer companies.

### What We Do

**Live data at query time via yfinance + MCP**

Every price, margin, EPS, P/E ratio, debt figure, and earnings number is fetched live from yfinance at the moment of the query — not from the LLM's training weights. The LLM formats and synthesises; it never invents numbers.

**NaN/None sanitisation**

yfinance returns `None` or `float('nan')` for fields that a company has not reported (e.g. `forwardPE` for a company with no analyst coverage, `debtToEquity` for a debt-free company). Without sanitisation, the LLM receives raw Python `None` in its context and may confabulate a value to fill the gap.

Every field in the `get-ticker-info` MCP response is passed through a `_clean()` function before the LLM sees it:

```python
def _clean(v):
    if v is None:
        return "N/A (not reported)"
    if isinstance(v, float) and math.isnan(v):
        return "N/A (not reported)"
    return v

info = {k: _clean(v) for k, v in info.items()}
```

The LLM now sees `"N/A (not reported)"` instead of `None` — an explicit signal that the data does not exist rather than an invitation to guess.

**Data staleness indicator**

Financial statements can be one quarter old; intraday quotes have a 15-minute delay on most yfinance feeds. Without a timestamp, users cannot tell whether they are looking at current or stale data.

Every `get-ticker-info` response now includes:

- `price_as_of`: derived from `regularMarketTime` (Unix timestamp → `"YYYY-MM-DD HH:MM UTC"`)
- `financials_period`: derived from `mostRecentQuarter` or `lastFiscalYearEnd` (→ `"YYYY-MM-DD"`)

Every financial report surfaces these in a "Data as of:" section so users know exactly how fresh the figures are.

**One-shot tools — raw data never traverses the LLM**

Tools like `fetch_and_forecast`, `fetch_price_trends`, and all chart renderers do all computation internally. They accept only a ticker symbol as input and return a compact summary. Raw OHLCV arrays (60+ rows of daily prices) and base64 PNGs (~50 KB) never pass through the LLM context.

```
                      resolve_ticker("Apple") → "AAPL"
                               │
               fetch_and_forecast("AAPL")
                               │
              ┌────────────────▼────────────────┐
              │   INTERNAL (never LLM context)  │
              │                                 │
              │  yfinance.download(90 days)     │
              │  OLS regression                 │
              │  10-day forecast                │
              │  R², std_err, band_pct          │
              └────────────────┬────────────────┘
                               │
              LLM receives compact summary only:
              { ticker, current_price, forecast_prices[],
                trend_direction, r_squared, forecast_band_pct }
```

This means the LLM cannot misread, misround, or hallucinate figures mid-array.

---

## 3. RAG Accuracy

### The Problem
Retrieval-Augmented Generation is only as accurate as its retrieval. If the semantic search returns low-quality passages — or if the agent uses passages that barely relate to the question — the synthesised answer can be wrong while appearing well-cited.

### What We Do

**Semantic search over primary-source SEC filings**

10-K answers are retrieved from the actual indexed SEC filing text stored in ChromaDB, not generated from the model's memory of the filing. The `all-MiniLM-L6-v2` sentence transformer converts both the query and the filing chunks into vector embeddings; ChromaDB returns the most semantically similar passages by cosine similarity.

**Minimum relevance threshold**

Every passage returned by ChromaDB has a relevance score (1 − cosine distance, 0–1 scale). Passages below 0.40 are filtered out before synthesis:

```
ChromaDB returns N passages with relevance scores
           │
    ┌──────▼───────┐
    │ score ≥ 0.40?│
    └──────┬───────┘
          / \
        YES   NO
         │     │
    use  │     └──► discard passage
    passage        (add to filtered_count)
         │
    If ALL passages below 0.40:
         └──► return all + low_relevance_warning: true
              + "Best match relevance is low —
                results may not directly answer the query."
```

This prevents the agent from confidently synthesising an answer from tangentially related passages when the filing simply does not cover the topic well.

**Multi-query strategy — at most 3 calls**

For complex questions, `tenk_agent` decomposes the query into focused sub-queries (e.g. "risk factors regulatory" and "revenue growth strategy" as separate calls). Each call uses `n_results=3`. The agent makes at most 3 `search_10k` calls per turn to stay within the context budget.

**Citation on every tool call**

Every response cites its exact source. Citations are captured in `web_server.py` at the tool callback level and emitted as a structured `citations` SSE event rendered as a "Sources" badge:

| Tool | Citation label | Detail |
|---|---|---|
| `get-ticker-info` | Yahoo Finance | `AAPL · live price` |
| `search_10k` | SEC 10-K · SNOW | `3 passages` |
| `query_investment_research` | LightRAG knowledge graph | `mode: hybrid` |
| `fetch_and_forecast` | Yahoo Finance | `AAPL · 3-month history (OLS)` |

**Passage-level snippet on hover**

The top retrieved passage (first 120 characters) is included as a `snippet` field in the citation. Hovering the citation chip in the UI shows the supporting passage text directly — users can verify which specific filing text supports each claim without leaving the chat.

**Citation pattern in 10-K responses**

```
"According to the Risk Factors section of Snowflake's 10-K:
 'We operate in highly competitive markets...'

 In the MD&A section:
 'Product revenue of $3.2B represented 95% of total revenue...'"

Sources: [SEC 10-K · SNOW · 3 passages]  ← hover to see passage text
```

---

## 4. Guardrails — Six-Layer Safety Stack

### The Problem
LLMs can be manipulated into producing inaccurate, harmful, or out-of-domain responses through injection attacks (in user input or tool results), out-of-scope questions, PII leakage, or overconfident financial advice.

### What We Do

All six checks fire automatically at every LLM boundary via ADK model callbacks. No agent can bypass them.

```
                    User Input
                        │
              ┌─────────▼──────────┐
              │  1. Injection check │  Blocklist of 20 patterns:
              │     (user input)   │  "ignore your instructions",
              └─────────┬──────────┘  "you are now", "developer mode"…
                        │             → Blocked before any LLM call
              ┌─────────▼──────────┐
              │  2. Out-of-scope   │  Rejects sport, food, politics,
              │     rejection      │  health, relationships, etc.
              └─────────┬──────────┘  → Returns allowed-topics message
                        │
              ┌─────────▼──────────┐
              │  3. PII            │  EMAIL, PHONE, SSN, CC, IP
              │     tokenisation   │  replaced with [TYPE_N] tokens
              └─────────┬──────────┘  stored in Fernet-encrypted SQLite
                        │
              ┌─────────▼──────────┐
              │  4. Token limit    │  > 20,000 estimated tokens
              │     enforcement    │  → Blocked with user message
              └─────────┬──────────┘
                        │
                     LLM call
                        │
              ┌─────────▼──────────┐
              │  5. Tool result    │  NEW: scans yfinance data and
              │     injection scan │  10-K passages for 6 dangerous
              └─────────┬──────────┘  patterns before LLM sees them:
                        │             "ignore previous instructions",
                        │             "you are now", "new persona"…
                        │             → Returns error dict + audit event
              ┌─────────▼──────────┐
              │  6. Output: PII    │  [TYPE_N] tokens replaced with
              │     + advice check │  masked values; directive advice
              └─────────┬──────────┘  patterns trigger disclaimer
                        │             prepended to response
                   User sees response
```

**Why tool result injection matters:** A company's SEC filing or yfinance description field could theoretically contain adversarial text. Without scanning tool results, an attacker could craft a company name or filing passage that manipulates the LLM's subsequent behaviour within the same turn. Check 5 closes this gap.

---

## 5. Forecast Transparency

### The Problem
A forecast is only useful if the user understands how reliable it is. A point estimate ("NVDA will be $950 in 10 days") presented without uncertainty bounds gives users false confidence. An OLS regression on 90 days of noisy stock prices can have R² of 0.05 or 0.95 — the user deserves to know which.

### What We Do

**R², standard error, and confidence band on every forecast**

The `fetch_and_forecast` tool computes three additional metrics alongside the 10-day forecast:

```python
# After OLS regression:
ss_res    = sum((actual - predicted) ** 2 for ...)
ss_tot    = sum((actual - mean) ** 2 for ...)
r_squared = 1 - ss_res / ss_tot          # goodness of fit
std_err   = statistics.stdev(residuals)  # spread of residuals
forecast_band_pct = (std_err / mean_price) * 100  # ±% uncertainty
```

All three are returned to the LLM and included in every forecast response:

```
fetch_and_forecast("NVDA")
        │
        ├── 10-day price forecast table
        ├── r_squared = 0.87      ──► "R²: 0.87"
        ├── std_err = 14.20
        └── forecast_band_pct = 1.6 ──► "±1.6% band"

Presented to user:
  Predicted price in 10 days: $950.40
  R²: 0.87 (±1.6% band)

  ── vs ──

  Predicted price in 10 days: $950.40
  R²: 0.12 (±8.4% band)
  ⚠️ Low R² — trend is weak, forecast uncertainty is high.
```

The second example gives the user the same number but honest context. Without R², both would look equally credible.

**Ticker resolution confirmation**

Every agent that resolves a company name to a ticker is instructed to state the full company name at the top of every response:

```
Microsoft Corporation (MSFT)
─────────────────────────────
Revenue: $245.1B ...
```

This allows users to immediately catch a wrong resolution (e.g. "NET" resolving to Cloudflare when the user meant something else) before reading the data.

---

## 6. Goal Verification

### The Problem
Factual accuracy of individual claims is necessary but not sufficient. The agent must also actually accomplish what the user asked. A PDF that was never written, a trade that was never persisted, or a comparison response that silently omits one of three requested companies are all goal failures — and without verification, they look like successes.

### What We Do

**Side-effect assertions**

After every agent action that produces a side effect, the system reads back the result to confirm it happened:

```
compile_pdf_report(ticker)
        │
        ├── reportlab builds PDF
        ├── saves to output/{ticker}_report.pdf
        │
        └── VERIFY:
            filepath.exists() AND filepath.stat().st_size > 0
                    │
              YES ──► return success dict with path
              NO  ──► return {"status": "error",
                              "message": "PDF write verification failed"}

execute_pending_trade()
        │
        ├── writes record to trades.jsonl
        │
        └── VERIFY:
            read back last line of trades.jsonl
            json.loads(last_line)["trade_id"] == trade_id
                    │
              YES ──► return success dict
              NO  ──► return {"status": "error",
                              "message": "Trade write verification failed"}
```

**Pipeline step handoff validation**

In multi-agent pipelines, each agent's output is checked before the next agent runs:

```
ANNUAL_FINANCIAL pipeline:
    tenk_agent runs
         │
         └── step_text_produced = False?
                      │
               NO OUTPUT ──► emit progress:
                              "⚠️ tenk_agent produced no output
                               — continuing with available data."
                              continue to financial_report_agent
               HAS OUTPUT ──► continue normally
```

Without this check, `financial_report_agent` would run silently after a failed `tenk_agent`, producing a half-response with no explanation.

**Multi-entity coverage enforcement**

The `comparison_insights_agent` system prompt includes a coverage check instruction:

> "Before finalising your response, verify that you have produced a paragraph for EVERY company listed in the trend table. If any company is missing, explicitly state: '[Company] — No 10-K data available in the index.' Never silently omit a company from the comparison."

**Runtime goal verification**

After every live response, a `goal_verification` audit event is emitted:

```
Response assembled
        │
        ├── len(response) < 50 chars?
        │       YES ──► audit: {status: "suspect",
        │                       reason: "response_too_short"}
        │       NO  ──► audit: {status: "ok"}
        │
        └── ENABLE_GOAL_JUDGE=true?
                YES ──► asyncio.create_task(_run_goal_judge(...))
                         │
                         └── Gemini call (background, non-blocking):
                             "Question: {question}
                              Answer: {response[:500]}
                              Did the answer address the question?
                              Reply with only a score 1-5."
                                      │
                                      └── audit: {type: "goal_score",
                                                  score: 4,
                                                  session_id: ...}
```

The background judge call does not block the user's response — it fires after the stream completes. Response text is capped at 500 characters to keep cost near zero.

---

## 7. Cross-Pipeline Fact Consistency

### The Problem
In compound pipelines, two different agents may produce contradictory figures from different sources. `tenk_agent` reads from the SEC filing (which may be from a different fiscal period or use different revenue recognition) while `financial_report_agent` reads from yfinance (which reflects TTM or the most recent quarterly data). Silent contradictions between the two erode user trust.

### What We Do

**Progress cue before cross-check**

In the `ANNUAL_FINANCIAL` pipeline, a progress event is emitted before `financial_report_agent` runs to signal cross-checking is happening:

```
User: "Analyse Snowflake's annual report and financial performance"
    │
    ▼
tenk_agent runs
    ├── "Product revenue grew 38% year-over-year" (from 10-K)
    └── streams 10-K insights ──► user sees them
    │
    ▼  [progress: "Cross-checking 10-K insights against financial data…"]
    │
financial_report_agent runs
    ├── get-ticker-info → growth from yfinance
    ├── scans tenk_agent output in conversation history
    │
    └── If figures differ by > 5%:
        ┌──────────────────────────────────────────────────────┐
        │ ⚠️ Data Note: The 10-K filing states 38% revenue     │
        │ growth while current yfinance data shows 34%.        │
        │ This may reflect different reporting periods or      │
        │ restatements.                                        │
        └──────────────────────────────────────────────────────┘
```

The agent is instructed to never silently ignore contradictions between filing text and live data. Discrepancies are surfaced explicitly so users can investigate rather than accepting a number that sounds authoritative.

---

## 8. Evaluation Gate

### The Problem
Accuracy must be measurable, not just aspirational. Without a quantitative gate, prompt changes, model updates, or dependency upgrades can silently degrade response quality.

### What We Do

**Three-level metrics across 22 E2E test cases**

```
python -m eval.run_eval --gate
        │
        ├── 33 intent classification cases
        │       └── intent_accuracy ≥ 80%
        │
        ├── 22 E2E pipeline cases:
        │   ┌─────────────────────────────────────────┐
        │   │ Happy path (15 cases)                   │
        │   │  price, prediction, alert, financial,   │
        │   │  visualization, PDF, 10-K, comparison,  │
        │   │  trading, investment research            │
        │   ├─────────────────────────────────────────┤
        │   │ Compound pipelines (2 cases)             │
        │   │  ANNUAL_FINANCIAL, PRICE_PREDICT_CHART  │
        │   ├─────────────────────────────────────────┤
        │   │ Guardrail cases (2 cases)                │
        │   │  injection attempt, out-of-scope         │
        │   ├─────────────────────────────────────────┤
        │   │ Adversarial / edge cases (5 NEW cases)  │
        │   │  non-existent ticker (ZZZZZ)            │
        │   │  unindexed company 10-K (Zoom Video)    │
        │   │  5-company comparison                   │
        │   │  bare single-word ticker ("NVDA")       │
        │   │  injection attempt via query             │
        │   └─────────────────────────────────────────┘
        │
        ├── RAGAS metrics per case:
        │       answer_relevancy  ≥ threshold (per case)
        │       faithfulness      ≥ threshold (per case)
        │       factual_correctness (stable cases only)
        │
        ├── Aggregate metrics vs thresholds.yaml:
        │       tool_select_accuracy  ≥ 85%
        │       task_complete_rate    ≥ 80%
        │       hallucination_rate    ≤ 5%
        │       thumbs_down_rate      ≤ 15%
        │       mean_goal_score       ≥ 3.5
        │
        └── exit 0 (all pass) or exit 1 (any fail)
             ↑
             CI gate — blocks deployment on regression
```

**Model version pinning**

```python
# stock_agent/model_config.py
MODEL_VERSION = "gemini-2.5-flash"
MODEL_BUILD   = "2026-05-06"   # date this string was last verified
```

Every `llm_request` audit event records both fields. The eval dashboard header shows:

```
Model: gemini-2.5-flash  (build ref: 2026-05-06)
```

If Google silently updates the model and outputs change, the eval gate will catch the regression even though no code changed.

**Hallucination rate measurement**

```
Hallucination Rate = 1 − mean(faithfulness)
                              │
                    computed across all non-guardrail
                    E2E cases by RAGAS

Guardrail cases produce faithfulness ≈ 0.22
(refusal text has no tool context to verify against)
→ excluded from rate calculation to avoid inflation

Current rate: ~3.5% (target ≤ 5%)
```

---

## 9. Live Feedback & Production Signals

### The Problem
The eval gate catches known regressions on a fixed test set. It cannot catch new failure modes that appear in production with real user queries. A separate signal is needed that reflects what real users actually found accurate and useful.

### What We Do

**Per-response thumbs up/down**

Every response bubble has 👍/👎 buttons. On click:
- Both buttons are disabled (prevents double-voting)
- The selected thumb is highlighted
- A `POST /api/feedback` call writes to `feedback.jsonl`:

```json
{
  "username":      "alice",
  "session_id":    "abc-123",
  "message_index": 4,
  "vote":          "down",
  "comment":       "",
  "timestamp":     "2026-05-06T14:23:11Z"
}
```

**Feedback report**

```
python -m stock_agent.feedback_report

┌─────────────────────────────────────────────────────┐
│  FEEDBACK SUMMARY                                    │
│                                                     │
│  Total votes:    47                                 │
│  👍 Helpful:     41  (87.2%)                        │
│  👎 Unhelpful:    6  (12.8%)  ← threshold ≤ 15%    │
│                                                     │
│  Per-user breakdown:                                │
│  alice    12 votes  10👍  2👎  (16.7% down)         │
│  admin     8 votes   8👍  0👎  ( 0.0% down)         │
│  ...                                                │
│                                                     │
│  GOAL SCORE DISTRIBUTION (from audit.log)           │
│  Score 5: ████████████  24                          │
│  Score 4: ████████      16                          │
│  Score 3: ████           8                          │
│  Score 2: ██             4                          │
│  Score 1: █              2                          │
│  Mean: 4.07  (threshold ≥ 3.5)                     │
└─────────────────────────────────────────────────────┘
```

Both `thumbs_down_rate` and `mean_goal_score` feed directly into the eval gate as L2 metrics — the production signal closes the loop back into the offline evaluation.

```
         PRODUCTION                      EVAL GATE
┌─────────────────────┐           ┌──────────────────────┐
│  Real user queries  │           │  run_eval --gate      │
│         │           │           │         │             │
│  feedback.jsonl ────┼──────────►│  thumbs_down_rate     │
│  audit.log      ────┼──────────►│  mean_goal_score      │
│  (goal_score)       │           │         │             │
└─────────────────────┘           │  exit 1 if regressed  │
                                  └──────────────────────┘
```

---

## 10. Observability & Audit Trail

### What We Log

Every LLM call, tool call, routing decision, and safety event is written to `audit.log` as structured JSON with daily rotation and 90-day retention.

```
Every LLM call:
{
  "type":          "llm_request",
  "agent":         "financial_report_agent",
  "model_version": "gemini-2.5-flash",
  "model_build":   "2026-05-06",
  "tokens_in":     1240,
  "tokens_out":    380,
  "session_id":    "abc-123",
  "user_id":       "alice",
  "timestamp":     "2026-05-06T14:23:11Z"
}

Every routing decision:
{
  "type":      "routing_decision",
  "intent":    "FINANCIAL_REPORT",
  "companies": ["AAPL"],
  "pipeline":  ["financial_report_agent"]
}

── or on misclassification ──
{
  "type":    "routing_decision",
  "intent":  "UNKNOWN",
  "warning": "intent_parse_failed"
}

Tool injection attempt:
{
  "type":    "tool_injection_attempt",
  "tool":    "search_10k",
  "pattern": "ignore previous instructions"
}

Disclaimer missing:
{
  "type":       "disclaimer_missing",
  "agent":      "prediction_agent",
  "session_id": "abc-123"
}

Goal verification:
{
  "type":   "goal_verification",
  "status": "suspect",
  "reason": "response_too_short",
  "length": 12
}

LLM-as-judge score:
{
  "type":       "goal_score",
  "score":      4,
  "session_id": "abc-123"
}
```

**LangFuse distributed tracing**

Every conversation creates a root trace with nested spans for each agent, LLM call, and tool. Any inaccurate response can be fully replayed: exact input context, tool responses, and model output are all captured. Cost per call is recorded to `cost.jsonl`.

---

## 11. Known Limitations

These limitations are explicitly acknowledged and disclosed to users:

| Limitation | Impact | Disclosed How |
|---|---|---|
| **Linear regression forecast** | Naive OLS — ignores earnings, news, macro events | R² + band shown on every forecast; low-R² warning |
| **Single financial data source** | All figures from yfinance only — no cross-validation | Noted in PRD §9; staleness timestamp shown |
| **10-K coverage limited to indexed companies** | Cannot answer filing questions for non-indexed companies | `list_indexed_companies` called first; user told which are available |
| **Paper trading only** | No real broker integration; no real money | Disclaimer on every trade confirmation |
| **15-minute quote delay** | Intraday prices are not real-time | `price_as_of` timestamp shown on every price response |
| **Cross-source validation not implemented** | yfinance errors (wrong fiscal year mapping, stale TTM) undetected | Future work — EDGAR XBRL API cross-check |

---

## Summary Table — All Accuracy Measures

| # | Measure | Layer | File(s) |
|---|---|---|---|
| 1 | Live data at query time | Data | `finance_mcp_server.py` |
| 2 | NaN/None sanitisation | Data | `finance_mcp_server.py` |
| 3 | Data staleness timestamp | Data | `finance_mcp_server.py`, `financial_report_agent_v1.md` |
| 4 | One-shot tools (no raw data in LLM context) | Data | `tools.py`, `visualization_tools.py` |
| 5 | RAG over primary-source SEC filings | RAG | `tenk_tools.py`, ChromaDB |
| 6 | Minimum relevance threshold (0.40) | RAG | `tenk_tools.py` |
| 7 | Low-relevance warning | RAG | `tenk_tools.py` |
| 8 | Source citations on every response | RAG | `web_server.py` |
| 9 | Passage snippet on hover | RAG | `web_server.py`, `index.html` |
| 10 | User input injection check | Guardrails | `guardrails.py` |
| 11 | Tool result injection scan | Guardrails | `audit.py` |
| 12 | Out-of-scope rejection | Guardrails | `guardrails.py` |
| 13 | PII tokenisation / detokenisation | Guardrails | `guardrails.py`, `pii_store.py` |
| 14 | Token limit enforcement | Guardrails | `guardrails.py` |
| 15 | Financial advice disclaimer | Guardrails | `guardrails.py` |
| 16 | Disclaimer tracking on 9 agents | Guardrails | `audit.py` |
| 17 | R² + confidence band on forecasts | Forecast | `tools.py`, `prediction_agent_v1.md` |
| 18 | Low-R² warning | Forecast | `tools.py`, `prediction_agent_v1.md` |
| 19 | Full company name confirmation | Routing | `price_agent_v1.md`, `financial_report_agent_v1.md` |
| 20 | Routing decision audit events | Routing | `agent.py` |
| 21 | PDF side-effect assertion | Goal verification | `pdf_tools.py` |
| 22 | Trade write read-back assertion | Goal verification | `trade_tools.py` |
| 23 | Pipeline step handoff validation | Goal verification | `agent.py` |
| 24 | Multi-entity coverage enforcement | Goal verification | `comparison_insights_agent_v1.md` |
| 25 | Runtime response length check | Goal verification | `web_server.py` |
| 26 | Async LLM-as-judge (opt-in) | Goal verification | `web_server.py` |
| 27 | Cross-pipeline fact consistency | Consistency | `agent.py`, `financial_report_agent_v1.md` |
| 28 | 22 E2E eval cases (incl. adversarial) | Evaluation | `eval/cases.py` |
| 29 | RAGAS gate (relevancy + faithfulness) | Evaluation | `eval/run_eval.py` |
| 30 | Hallucination rate measurement | Evaluation | `eval/metrics.py` |
| 31 | Model version + build pinned | Evaluation | `model_config.py`, `audit.py` |
| 32 | Per-response thumbs up/down | Feedback | `index.html`, `web_server.py` |
| 33 | Feedback report + thumbs-down rate metric | Feedback | `feedback_report.py`, `run_eval.py` |
| 34 | Goal score aggregation in eval | Feedback | `run_eval.py`, `feedback_report.py` |
| 35 | Full LangFuse distributed tracing | Observability | `tracing.py` |
| 36 | 90-day structured audit logs | Observability | `audit.py` |
