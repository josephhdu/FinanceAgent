# Misinterpretation Prevention

**Version:** 2.0  
**Date:** 2026-05-06  
**Scope:** All measures — existing and new — taken to prevent the system from misunderstanding user intent, resolving the wrong entities, or producing output users could misread.

---

## Table of Contents

1. [Overview](#1-overview)
2. [What We Already Had](#2-what-we-already-had)
   - [Intent Misinterpretation — Existing Defences](#21-intent-misinterpretation--existing-defences)
   - [Entity Misinterpretation — Existing Defences](#22-entity-misinterpretation--existing-defences)
   - [Output Misinterpretation — Existing Defences](#23-output-misinterpretation--existing-defences)
3. [New Fixes — Five Remaining Gaps](#3-new-fixes--five-remaining-gaps)
   - [Gap 1 — Ambiguous Query Clarification](#gap-1--ambiguous-query-clarification)
   - [Gap 2 — Ticker Disambiguation](#gap-2--ticker-disambiguation)
   - [Gap 3 — Trade Quantity Confirmation](#gap-3--trade-quantity-confirmation)
   - [Gap 4 — Multi-Turn Context Drift](#gap-4--multi-turn-context-drift)
   - [Gap 5 — Financial Jargon Explanation](#gap-5--financial-jargon-explanation)
4. [End-to-End Flow](#4-end-to-end-flow)
5. [Complete Summary Table](#5-complete-summary-table)
6. [Known Limitations](#6-known-limitations)

---

## 1. Overview

Misinterpretation failures fall into three categories:

```
┌─────────────────────────────────────────────────────────────────────┐
│                      MISINTERPRETATION RISK                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  1. INTENT          Did the system understand what                  │
│     MISINTERPRETATION  the user is asking for?                      │
│                                                                     │
│     Already had:  9 ordered priority rules, UNKNOWN clarification,  │
│                   routing audit, goal verification, pipeline abort  │
│     New fixes:    Confidence-gated clarification (Gap 1)            │
│                   Multi-turn context drift detection (Gap 4)        │
│                                                                     │
│  2. ENTITY          Did the system identify the right               │
│     MISINTERPRETATION  real-world object?                           │
│                                                                     │
│     Already had:  Full company name in every response,              │
│                   GOOG→GOOGL normalisation, resolve_ticker tool     │
│     New fix:      Ticker disambiguation list (Gap 2)                │
│                                                                     │
│  3. OUTPUT          Could the response itself mislead               │
│     MISINTERPRETATION  the user?                                    │
│                                                                     │
│     Already had:  R² uncertainty, staleness labels, NaN sanitation, │
│                   RAG relevance threshold, passage citations,       │
│                   cross-pipeline consistency, multi-entity coverage │
│     New fixes:    Trade quantity disclosure (Gap 3)                 │
│                   Financial jargon definitions (Gap 5)              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. What We Already Had

### 2.1 Intent Misinterpretation — Existing Defences

#### 9 Ordered Classification Priority Rules
**File:** `prompts/intent_agent_v1.md`

The intent agent operates under nine explicit, ordered rules that resolve the most common intent overlaps. First match wins:

| Priority | Rule | Example |
|---|---|---|
| 1 | Any mention of "PDF / download / export" → `PDF_REPORT` | "Export AAPL as a PDF" |
| 2 | Trading / buy / sell / portfolio → `TRADE_ANALYSIS` | "Should I buy MSFT?" |
| 3 | Chart of forecast → `PRICE_PREDICT_CHART` | "Show me a forecast chart" |
| 4 | Price + prediction, no chart → `PRICE_PREDICTION` | "AAPL price and outlook" |
| 5 | 10-K + financial metrics combined → `ANNUAL_FINANCIAL` | "Annual report and P/E" |
| 6 | Explicit chart/graph keyword → `VISUALIZATION` | "Bar chart of FAANG prices" |
| 7 | Comparison + explicit time horizon → `STOCK_COMPARISON` | "MSFT vs AAPL last year" |
| 8 | Cross-section PDF analysis → `INVESTMENT_RESEARCH` | "Compare table vs MD&A" |
| 9 | Single-purpose intents → match individually | "AAPL revenue" → `FINANCIAL_REPORT` |

These rules exist because the intents frequently share keywords (e.g. "compare" appears in PRICE, VISUALIZATION, and STOCK_COMPARISON). Without explicit priority, the model would be inconsistent.

#### Three-Way Disambiguation for Similar Intents
**File:** `prompts/intent_agent_v1.md`

A dedicated section clarifies the three most-confused intents with canonical examples:

```
PRICE          — comparing current/today's prices, no time period
VISUALIZATION  — user explicitly asks for a chart or graph
STOCK_COMPARISON — only when a time horizon is explicitly stated

Key signal: no time period + no chart keyword → PRICE
            chart keyword + today → VISUALIZATION
            time period present → STOCK_COMPARISON
```

This prevents queries like "compare Apple and Microsoft" from routing to `STOCK_COMPARISON` (which requires historical price data) when the user simply wants current prices side by side.

#### UNKNOWN Intent → Clarification Message
**File:** `stock_agent/agent.py`

When the intent agent cannot classify a query, the orchestrator catches `pipeline = None` and returns a clarification event instead of an error:

```python
if pipeline is None:
    yield _clarification_event(ctx, alternatives or None)
    return
```

Before this was in place, unclassifiable queries would either crash or be silently dropped.

#### Routing Decision Audit
**File:** `stock_agent/agent.py`, `stock_agent/audit.py`

Every routing decision — including misclassification warnings — is written to `audit.log`:

```python
_audit_emit(
    "routing_decision",
    intent=intent,
    companies=companies,
    pipeline=[a.name for a in pipeline],
    session_id=ctx.session.id,
)
```

On UNKNOWN intent, a `warning` field is added:

```python
warning="intent_parse_failed" if _parse_failed else "unknown_intent"
```

This creates a queryable record of every routing decision, enabling post-hoc analysis of misclassification patterns without relying on user feedback.

#### Pipeline Abort with Reason
**File:** `stock_agent/agent.py`

When a multi-step pipeline's intermediate stage fails (empty output or error markers in text), the orchestrator aborts and tells the user exactly which stage failed and why, rather than silently passing broken data to the next agent:

```python
def _abort_event(ctx, agent_name, reason):
    return Event(
        content=types.Content(parts=[types.Part(text=(
            f"I couldn't continue because the previous step ({agent_name}) "
            f"didn't return usable data: {reason}. "
            "Please try rephrasing your request or check that the ticker is valid."
        ))])
    )
```

The `_validate_step_output()` function runs three checks before any pipeline handoff:
1. At least one non-empty text part was produced
2. No ADK safety/recitation finish reason
3. No error-marker phrases ("unable to fetch", "not found", "failed to", etc.)

#### Empty Pipeline Step Warning
**File:** `stock_agent/agent.py`

Even when the pipeline is not aborted (e.g. the empty step is the last one), the orchestrator tracks whether each agent produced any text and emits a visible warning if not:

```python
if not step_text_produced and step < total:
    yield _progress_event(
        ctx,
        f"⚠️ {agent.name} produced no output — continuing with available data."
    )
```

This prevents silent gaps in compound pipeline responses (e.g. `PRICE_PREDICTION` where `prediction_agent` quietly fails).

#### Goal Verification — LLM-as-Judge
**File:** `web_server.py`

After every response, an async judge scores 1–5 whether the response actually addressed the user's original question. Score and pass/fail are stored in `audit.log` as `goal_score` events and surfaced in the eval dashboard as `mean_goal_score` (threshold ≥ 3.5). A runtime length heuristic runs synchronously as a lightweight first check even when the full LLM judge is disabled.

#### Pending Trade Auto-Cancel on Pivot
**File:** `stock_agent/agent.py`

If a user sends an unrelated message while a pending trade is awaiting approval, the orchestrator detects the pivot (message length > 30 or no approval/cancel keyword), auto-cancels the pending trade, and surfaces a progress event:

```python
cancel_pending_trade()
yield _progress_event(
    ctx, "Previous trade proposal cancelled — handling new request…"
)
```

This prevents the trading pipeline from silently hijacking unrelated queries.

---

### 2.2 Entity Misinterpretation — Existing Defences

#### Full Company Name at Top of Every Response
**Files:** `prompts/price_agent_v1.md`, `prompts/financial_report_agent_v1.md`

Every agent that resolves a company name to a ticker is instructed to state the full company name at the very top of its response:

> "Always state the full company name (e.g. 'Microsoft Corporation') at the very top of your response, followed by the ticker symbol in parentheses, so the user can confirm the correct company was resolved."

This means a user who asked about "Alphabet" sees "Alphabet Inc. (GOOGL)" at the top — they can immediately spot if the wrong company was resolved before reading any data.

#### GOOG → GOOGL Normalisation
**File:** `stock_agent/agent.py`

The intent parser applies a code-level normalisation that the model frequently gets wrong — Alphabet has two share classes (`GOOG` class C, `GOOGL` class A) and the model inconsistently returns both:

```python
if "companies" in data and isinstance(data["companies"], list):
    data["companies"] = [
        "GOOGL" if c == "GOOG" else c for c in data["companies"]
    ]
```

This runs deterministically after LLM output, so it cannot be overridden by a bad model response.

#### `resolve_ticker` Tool
**Files:** `stock_agent/price_agent.py`, `stock_agent/financial_report_agent.py`

Agents that call financial APIs use a `resolve_ticker` tool as their mandatory first step. This converts any company name or alias ("Google", "Alphabet", "GOOG") to the canonical ticker before any data fetch, ensuring the API call uses the correct symbol even if the intent agent returned a name rather than a ticker.

---

### 2.3 Output Misinterpretation — Existing Defences

#### R² and Forecast Uncertainty Band
**Files:** `stock_agent/tools.py`, `prompts/prediction_agent_v1.md`

Every OLS price forecast now computes and exposes three quality metrics:

```python
r_squared        = 1 - ss_res / ss_tot
std_err          = statistics.stdev(residuals)
forecast_band_pct = (std_err / mean_price) * 100
```

The prediction agent is required to display:

```
R²: 0.21  (±8.4% band)
⚠️ Low R² — trend is weak, treat this forecast with caution.
```

The ⚠️ warning fires when R² < 0.30. Without this, a forecast derived from a flat or noisy price series would look as authoritative as one derived from a clear trend.

#### Data Staleness Labels
**File:** `stock_agent/finance_mcp_server.py`, `prompts/financial_report_agent_v1.md`

Every `get-ticker-info` response includes:

```python
"price_as_of":       "2026-05-06 14:32 UTC"   # from regularMarketTime
"financials_period": "2025-12-31"               # from mostRecentQuarter
```

Financial report agents are instructed to surface these in a mandatory section:

```
Data as of:
  Price data:            2026-05-06 14:32 UTC
  Financial statements:  2025-12-31
```

Users who rely on live trading decisions can see immediately whether the price is intraday or delayed.

#### NaN / None Sanitisation
**File:** `stock_agent/finance_mcp_server.py`

The `_clean()` helper replaces every missing `yfinance` field with the explicit string `"N/A (not reported)"` before the data reaches the LLM:

```python
def _clean(value: Any) -> Any:
    if value is None:
        return "N/A (not reported)"
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return "N/A (not reported)"
    return value
```

Without this, `null` or `NaN` values in the JSON payload could be silently interpreted as 0 by the model, producing incorrect statements like "the company has $0 debt" when the field is simply unavailable.

#### RAG Relevance Threshold
**File:** `stock_agent/tenk_tools.py`

10-K passage retrieval filters out any passage with cosine similarity below 0.40 before it reaches the LLM:

```python
_RELEVANCE_THRESHOLD = 0.40
filtered = [p for p in passages if p["score"] >= _RELEVANCE_THRESHOLD]
```

When all retrieved passages fall below the threshold, a `low_relevance_warning: true` flag is returned and the agent surfaces a visible warning. This prevents the LLM from generating plausible-sounding but irrelevant answers from loosely-matched passages.

#### Passage Snippet Citations
**Files:** `web_server.py`, `static/index.html`

Each 10-K citation chip carries the top 120-character source passage as a hover tooltip:

```python
# web_server.py
"snippet": passage_text[:120]

# index.html
chip.title = s.snippet || '';
```

Users can hover over any cited passage to verify what text the answer was grounded in, and judge its relevance for themselves. This makes the RAG evidence transparent to end users, not just logged internally.

#### Cross-Pipeline Fact Consistency
**Files:** `stock_agent/agent.py`, `prompts/financial_report_agent_v1.md`

In the `ANNUAL_FINANCIAL` compound pipeline (10-K + financial report), the orchestrator emits a cross-check cue before the financial report agent runs:

```
"Cross-checking 10-K insights against financial data…"
```

The `financial_report_agent` prompt instructs the model to flag any contradiction between filing text and live yfinance data:

> "If your yfinance data contradicts a figure from the 10-K by more than 5%, add a ⚠️ Data Note."

This catches the common case where a 10-K states one revenue figure and yfinance (which may use a different reporting period) states another.

#### Multi-Entity Coverage Enforcement
**File:** `prompts/comparison_insights_agent_v1.md`

When comparing multiple companies, the comparison agent is required to produce a paragraph for every company in the dataset. Companies with no 10-K data must be explicitly stated as unavailable, never silently omitted:

> "If a company has no indexed 10-K data, write: '[Company] — No 10-K data available' rather than omitting it from the analysis."

Without this, a user asking to compare five companies might silently receive analysis of only three.

#### Tool Injection Scan
**File:** `stock_agent/audit.py`

Tool responses are scanned against a 6-pattern blocklist before being injected into the LLM context. If a match is found (e.g. "ignore previous instructions" in a tool result), the tool result is replaced with a sanitised error dict and a `tool_injection_attempt` audit event is emitted. This prevents adversarial tool responses from steering the model's output toward incorrect or dangerous content.

---

## 3. New Fixes — Five Remaining Gaps

---

### Gap 1 — Ambiguous Query Clarification

#### Problem

The intent classifier always picks exactly one pipeline and routes to it, even when the query is genuinely ambiguous. A query like **"analyse Apple"** could reasonably mean:

- `FINANCIAL_REPORT` — revenue, margins, P/E ratios
- `ANNUAL_REPORT` — 10-K filing, MD&A, risk factors
- `PRICE` — live stock price
- `PRICE_PREDICTION` — price + 2-week forecast

Before this fix, the system would silently pick whichever scored highest.

#### Risk

The user gets a financial report when they wanted the 10-K, or a price quote when they wanted a forecast. No signal is given that the system guessed.

#### Fix

**File: `prompts/intent_agent_v1.md`**

Two new fields added to the JSON output schema:

```json
{
  "confidence": 0.62,
  "alternatives": ["ANNUAL_REPORT", "PRICE"]
}
```

Scoring rules:

| Confidence range | Meaning | `alternatives` |
|---|---|---|
| 0.8 – 1.0 | Unambiguous | `[]` |
| 0.5 – 0.79 | Two or more plausible intents | Populated |
| 0.0 – 0.49 | Genuinely unclear | `intent = UNKNOWN`, alternatives populated |

**File: `stock_agent/agent.py`**

Threshold of **0.65** introduced. When `confidence < 0.65` and a pipeline was found, routing stops and the user is asked to confirm:

```python
_CONFIDENCE_THRESHOLD = 0.65
if pipeline is not None and confidence < _CONFIDENCE_THRESHOLD:
    _audit_emit("low_confidence_intent", intent=intent, confidence=confidence, ...)
    yield _ambiguous_intent_event(ctx, intent, alternatives)
    return
```

`_ambiguous_intent_event()` produces a human-readable confirmation prompt:

```
I think you're asking for a financial report — but it could also be
a 10-K annual filing Q&A or current stock price. Should I proceed with
the financial report, or did you mean something else?
```

When intent is `UNKNOWN`, `_clarification_event()` now names the specific alternatives rather than giving a generic fallback.

**Audit trail:** `low_confidence_intent` event written to `audit.log` on every ambiguous routing decision.

---

### Gap 2 — Ticker Disambiguation

#### Problem

Company names are resolved to tickers by the intent agent. Some names are genuinely ambiguous:

| Name typed | Could mean |
|---|---|
| "Apple" | `AAPL` (Apple Inc., NASDAQ) or `APLE` (Apple Hospitality REIT, NYSE) |
| "SAP" | `SAP` (SAP SE) or SAP-prefixed ETFs |

Before this fix, the system would silently pick the most likely ticker.

#### Risk

A user asking about "Apple" for REIT research receives a tech-company financial report. The mistake may not be visible until they see iPhone revenue figures deep in the response.

#### Fix

**File: `prompts/intent_agent_v1.md`**

Two new fields:

```json
{
  "ticker_ambiguous": true,
  "ticker_disambiguation_options": [
    {"ticker": "AAPL", "company": "Apple Inc.", "exchange": "NASDAQ"},
    {"ticker": "APLE", "company": "Apple Hospitality REIT", "exchange": "NYSE"}
  ]
}
```

Rules: well-known tech names (MSFT, GOOGL, AMZN, NVDA) are never flagged. Only genuinely confusable names trigger the flag.

**File: `stock_agent/agent.py`**

Check runs **before** any pipeline:

```python
if ticker_ambiguous and ticker_options:
    _audit_emit("ticker_disambiguation", options=ticker_options, ...)
    yield _ticker_disambiguation_event(ctx, ticker_options)
    return
```

User sees a numbered list:

```
I found multiple companies that could match your request. Which one did you mean?

  1. Apple Inc. [AAPL]  (NASDAQ)
  2. Apple Hospitality REIT [APLE]  (NYSE)

Please reply with the ticker symbol (e.g. AAPL) to continue.
```

**Audit trail:** `ticker_disambiguation` event written to `audit.log` with all candidate options.

---

### Gap 3 — Trade Quantity Confirmation

#### Problem

When a user says "buy Google" with no share count, `trading_agent` auto-calculates a quantity targeting ~$2,000 notional. Before this fix:
1. The quantity was not labelled as auto-calculated — it looked like a deliberate recommendation.
2. There was no way to change the quantity without cancelling and restarting.
3. The only options were "yes" or "no".

#### Risk

The user replies "yes" intending to buy 5 shares and receives a trade for 12 shares.

#### Fix

**File: `prompts/trading_agent_v1.md`**

Recommendation format updated to label the auto-calculated quantity and offer a third option:

```
Order (mock):  BUY 12 shares × $167.34 = $2,008.08
               ↑ auto-calculated to ~$2,000 notional

Reply yes to execute · no to cancel · or specify a different quantity (e.g. 5 shares).
```

**File: `stock_agent/trade_tools.py`**

New function `update_pending_trade_shares()` mutates the in-memory pending trade:

```python
def update_pending_trade_shares(shares: int) -> dict:
    session_id = audit_session_id.get("unknown")
    trade = _pending_trades.get(session_id)
    if not trade:
        return {"status": "error", "message": "No pending trade found."}
    shares = int(shares)
    if shares < 1:
        return {"status": "error", "message": "shares must be >= 1"}
    trade["shares"]   = shares
    trade["notional"] = round(shares * trade["price"], 2)
    return {"status": "updated", "trade": trade}
```

**File: `stock_agent/agent.py`**

Pending-trade bypass now detects share-count override messages before yes/no approval:

```python
_share_override_m = _re.search(r'\b(\d+)\s*(?:shares?)?\b', msg_lower)
looks_like_share_override = (
    len(msg_lower) <= 40
    and _share_override_m is not None
    and (_re.search(r'\bshares?\b', msg_lower) or msg_lower.strip().isdigit())
    and not any(kw in msg_lower for kw in ("no", "cancel", "stop", "don't", "dont"))
)
if looks_like_share_override and not looks_like_approval:
    new_shares = int(_share_override_m.group(1))
    result = update_pending_trade_shares(new_shares)
    if result.get("status") == "updated":
        yield _progress_event(ctx,
            f"Updated to {new_shares} shares — ready to execute. "
            "Reply yes to confirm or no to cancel.")
        return
```

Detection patterns: `"5 shares"`, `"10"` (bare integer), `"use 20 shares"`, `"change to 15 shares"`.

**Example interaction:**

> System: "Order: BUY 12 shares × $167.34 = $2,008.08 ↑ auto-calculated…"  
> User: `5 shares`  
> System: "Updated to 5 shares — ready to execute. Reply **yes** to confirm or **no** to cancel."  
> User: `yes`  
> System: "✅ Mock Trade Executed — BUY 5 shares × $167.34 = $836.70"

---

### Gap 4 — Multi-Turn Context Drift

#### Problem

Session state accumulates context across turns. If a user discusses `AAPL` for several turns and switches to `MSFT`, there is no visible acknowledgement. The user has no way to confirm whether the system followed the pivot.

#### Risk

User: "Tell me Apple's margins" → AAPL  
User: "Now compare with Microsoft" → MSFT  
User: "What's the P/E?" → Which company? The system answers silently.

#### Fix

**File: `stock_agent/agent.py`**

After every successful routing, the orchestrator persists the current company set as `_anchor_companies` in session state. On subsequent turns where the company set is **fully disjoint** from the anchor, a visible progress event fires:

```python
if companies:
    prior_anchor = ctx.session.state.get("_anchor_companies", [])
    if prior_anchor and set(companies).isdisjoint(set(prior_anchor)):
        yield _progress_event(
            ctx, f"Context: switching focus from {', '.join(prior_anchor)} → {', '.join(companies)}"
        )
        _audit_emit("context_anchor_shift",
                    prior_companies=prior_anchor, new_companies=companies, ...)
    ctx.session.state["_anchor_companies"] = companies
```

Trigger logic:

```
Turn 1: anchor = ["AAPL"]
Turn 2: anchor = ["AAPL"]           → same, silent
Turn 3: companies = ["MSFT","NVDA"] → {"MSFT","NVDA"}.isdisjoint({"AAPL"}) = True
                                       → emit "Context: switching from AAPL → MSFT, NVDA"
Turn 4: companies = ["MSFT"]        → {"MSFT"}.isdisjoint({"MSFT","NVDA"}) = False
                                       → partial overlap — silent (still in same context)
```

The **full disjoint** condition prevents noise when a user narrows from a comparison to a single company.

**Audit trail:** `context_anchor_shift` event written to `audit.log` with `prior_companies` and `new_companies`.

---

### Gap 5 — Financial Jargon Explanation

#### Problem

Financial reports and trading recommendations contain technical terms opaque to non-expert users:

- "P/E ratio of 28.4x" — is 28.4 high or low?
- "EBITDA margin expanded 200bps" — what is EBITDA? What is a basis point?
- "OLS forecast return: +4.2%" — what is OLS?
- "Signal score: 0.72" — what scale?

#### Risk

Users make decisions based on numbers they don't understand. A non-expert seeing "P/E: 28.4" has no frame of reference to evaluate the stock's valuation.

#### Fix

A **financial term definitions** section was added to three agent prompts. Rule: *on first use of each technical term in a response, add a brief parenthetical definition. Skip if already defined earlier in the same response.*

**File: `prompts/financial_report_agent_v1.md`** — 18 terms:

| Term | Definition added |
|---|---|
| P/E ratio | (price-to-earnings: share price ÷ EPS) |
| Forward P/E | (P/E based on next 12 months' estimated earnings) |
| P/S ratio | (price-to-sales: market cap ÷ annual revenue) |
| P/B ratio | (price-to-book: market cap ÷ book value of equity) |
| EPS | (earnings per share: net income ÷ shares outstanding) |
| EBITDA | (earnings before interest, taxes, depreciation & amortisation) |
| Gross margin | (revenue minus cost of goods sold, as % of revenue) |
| Operating margin | (operating income as % of revenue) |
| Net margin | (net income as % of revenue) |
| ROE | (return on equity: net income ÷ shareholders' equity) |
| ROA | (return on assets: net income ÷ total assets) |
| Free cash flow | (operating cash flow minus capital expenditure) |
| Debt-to-equity | (total debt ÷ total shareholders' equity) |
| Market cap | (total market value: share price × shares outstanding) |
| CAGR | (compound annual growth rate) |
| YoY | (year-over-year comparison) |
| QoQ | (quarter-over-quarter comparison) |
| EV/EBITDA | (enterprise value ÷ EBITDA — a valuation multiple) |

**File: `prompts/price_agent_v1.md`** — 6 terms: market cap, P/E, 52-week high/low, daily change, volume, beta.

**File: `prompts/trading_agent_v1.md`** — 8 terms: signal score, OLS forecast, analyst consensus, notional value, 14-day forecast, upside to target, forward P/E, paper trade.

**Example output before this fix:**

```
Valuation Ratios
P/E: 28.4 | P/S: 7.2 | P/B: 11.3
```

**Example output after this fix:**

```
Valuation Ratios
P/E ratio (price-to-earnings: share price ÷ earnings per share): 28.4
P/S ratio (price-to-sales: market cap ÷ annual revenue): 7.2
P/B ratio (price-to-book: market cap ÷ book value of equity): 11.3
```

---

## 4. End-to-End Flow

```
User sends message
        │
        ▼
  ┌─────────────────────────────────────────────────────────┐
  │  EXISTING: Has pending trade?                           │
  │  ├── Yes, looks like approval/cancel → trading_agent   │
  │  ├── Yes, looks like share count (Gap 3 NEW)           │
  │  │         → update_pending_trade_shares()             │
  │  │         → "Updated to N shares — reply yes/no"      │
  │  └── Yes, unrelated → auto-cancel, continue            │
  └─────────────────────────────────────────────────────────┘
        │
        ▼
  EXISTING: intent_agent classifies (9 priority rules)
        │
        ▼
  ┌─────────────────────────────────────────────────────────┐
  │  NEW (Gap 2): ticker_ambiguous?                         │
  │  ├── Yes → show disambiguation list → return            │
  │  └── No  → continue                                     │
  └─────────────────────────────────────────────────────────┘
        │
        ▼
  ┌─────────────────────────────────────────────────────────┐
  │  NEW (Gap 1): confidence < 0.65?                        │
  │  ├── Yes → "I think you mean X, could be Y" → return   │
  │  └── No  → continue                                     │
  └─────────────────────────────────────────────────────────┘
        │
        ▼
  EXISTING: intent = UNKNOWN?
  ├── Yes → clarification event (now with named alternatives)
  └── No  → continue
        │
        ▼
  EXISTING: RBAC check
        │
        ▼
  ┌─────────────────────────────────────────────────────────┐
  │  NEW (Gap 4): companies changed from prior anchor?      │
  │  ├── Yes (fully disjoint) → emit context-switch notice  │
  │  └── No / partial overlap → silent                      │
  └─────────────────────────────────────────────────────────┘
        │
        ▼
  Route to pipeline
        │
        ▼
  EXISTING: per-step validation → abort if step fails
  EXISTING: empty-step warning if agent produces no text
        │
        ▼
  Agent generates response
  ├── EXISTING: full company name at top (entity verification)
  ├── EXISTING: staleness labels (price_as_of, financials_period)
  ├── EXISTING: R² + forecast uncertainty band
  ├── EXISTING: ⚠️ Low R² warning when R² < 0.30
  ├── EXISTING: cross-pipeline consistency note if figures conflict
  ├── EXISTING: multi-entity coverage (no silent omissions)
  └── NEW (Gap 5): jargon definitions on first use
        │
        ▼
  EXISTING: output PII scan + advice disclaimer check
  EXISTING: goal verification (length check + optional LLM judge)
        │
        ▼
  Response delivered to user
```

---

## 5. Complete Summary Table

### Existing Defences (pre-fix)

| Measure | Category | What it prevents | File(s) |
|---|---|---|---|
| 9 ordered priority rules | Intent | Wrong pipeline for ambiguous keywords | `prompts/intent_agent_v1.md` |
| PRICE / VISUALIZATION / STOCK_COMPARISON disambiguation | Intent | Routing "compare stocks" to wrong pipeline | `prompts/intent_agent_v1.md` |
| UNKNOWN → clarification message | Intent | Silent failure on unclassifiable queries | `stock_agent/agent.py` |
| Routing decision audit event | Intent | Undetected misclassification in production | `stock_agent/agent.py`, `audit.py` |
| Pipeline abort with reason | Intent | Broken data silently passed to next stage | `stock_agent/agent.py` |
| Empty pipeline step warning | Intent | Silent gaps in compound pipeline output | `stock_agent/agent.py` |
| Goal verification (LLM judge) | Intent | Response doesn't address the original question | `web_server.py` |
| Pending trade auto-cancel on pivot | Intent | Trading pipeline hijacking unrelated queries | `stock_agent/agent.py` |
| Full company name at top of response | Entity | User can't verify the right company was resolved | `prompts/price_agent_v1.md`, `prompts/financial_report_agent_v1.md` |
| GOOG → GOOGL normalisation | Entity | Wrong share class used for Alphabet queries | `stock_agent/agent.py` |
| `resolve_ticker` tool | Entity | Company name aliases not resolved before API call | Multiple agent files |
| R² + forecast uncertainty band | Output | Users treat weak-trend forecasts as reliable | `stock_agent/tools.py`, `prompts/prediction_agent_v1.md` |
| Data staleness labels | Output | Users rely on stale prices as current | `stock_agent/finance_mcp_server.py` |
| NaN / None sanitisation | Output | Missing values silently read as zero | `stock_agent/finance_mcp_server.py` |
| RAG relevance threshold (≥ 0.40) | Output | LLM answers from loosely-matched passages | `stock_agent/tenk_tools.py` |
| Passage snippet citations | Output | Users can't verify what the answer is grounded in | `web_server.py`, `static/index.html` |
| Cross-pipeline consistency check | Output | Contradictions between 10-K text and live data | `stock_agent/agent.py`, `prompts/financial_report_agent_v1.md` |
| Multi-entity coverage enforcement | Output | Companies silently omitted from comparison | `prompts/comparison_insights_agent_v1.md` |
| Tool injection scan | Output | Tool results steering model toward wrong answers | `stock_agent/audit.py` |

### New Fixes

| Gap | Category | Root Cause | Fix | Files |
|---|---|---|---|---|
| **1** | Intent | Ambiguous queries silently routed | `confidence` + `alternatives`; halt routing when confidence < 0.65 | `prompts/intent_agent_v1.md`, `stock_agent/agent.py` |
| **2** | Entity | Ambiguous company names resolved without asking | `ticker_ambiguous` flag; numbered disambiguation list before routing | `prompts/intent_agent_v1.md`, `stock_agent/agent.py` |
| **3** | Output | Auto-calculated trade quantity not disclosed; no override | `↑ auto-calculated` label; share-count override detection; `update_pending_trade_shares()` | `prompts/trading_agent_v1.md`, `stock_agent/agent.py`, `stock_agent/trade_tools.py` |
| **4** | Intent | Company pivot mid-conversation not surfaced | `_anchor_companies` session state; context-switch progress event on full disjoint pivot | `stock_agent/agent.py` |
| **5** | Output | Technical terms shown without explanation | Jargon glossary (18 + 6 + 8 terms) in three agent prompts; definitions on first use | `prompts/financial_report_agent_v1.md`, `prompts/price_agent_v1.md`, `prompts/trading_agent_v1.md` |

---

## 6. Known Limitations

| Limitation | Impact |
|---|---|
| Confidence is self-reported by the LLM | The model may overstate confidence on truly ambiguous queries, bypassing the clarification gate. |
| Ticker disambiguation relies on LLM training knowledge | Newly listed companies or obscure tickers may not be flagged as ambiguous. |
| Share-count override regex is heuristic | Phrasings like "a dozen shares" or "half a lot" are not detected. |
| Context anchor uses exact company set, not semantic similarity | "Alphabet" and "GOOGL" are treated as different anchors despite being the same company. |
| Jargon definitions are LLM-instructed, not enforced | If the model omits a definition, there is no hard fallback. |
| Clarification requires a follow-up turn | Every clarification pause adds latency. High-traffic sessions with many ambiguous queries will feel slow. |
| UNKNOWN intent clarification is not domain-aware | The fallback message lists all capabilities regardless of what the user was trying to do. |
