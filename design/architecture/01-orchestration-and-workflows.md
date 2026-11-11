# Orchestration and Workflows

## Overview

The stock analysis system uses a **deterministic graph-based orchestration** pattern built on Google ADK. A single root agent (`stock_orchestrator`) classifies intent via an LLM sub-agent, then routes to one or more specialist agents using pure Python logic — no LLM dispatch for routing.

This design gives predictable latency, zero routing hallucinations, and makes adding new epics trivial (add a route entry, not another LLM prompt). The system currently supports **13 intents**.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        User / ADK Web                           │
│                  (HTTP / adk web --port 8080)                   │
└───────────────────────────────┬─────────────────────────────────┘
                                │ Content message
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│              Input Guardrails  (before_model_callback)          │
│  • Prompt injection detection                                   │
│  • PII tokenization                                             │
│  • Out-of-scope rejection                                       │
│  • Token-limit guard (> 20 000 estimated tokens → abort)       │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│          stock_orchestrator   (BaseAgent / GraphOrchestrator)   │
│                                                                 │
│  Step 1 ─ run intent_agent (LlmAgent)                          │
│           Gemini 2.5-flash → JSON intent + entities             │
│                                                                 │
│  Step 2 ─ _route(intent, entities) [pure Python]               │
│           Lookup _ROUTE_MAP[intent] → ordered agent list        │
│                                                                 │
│  Step 3 ─ Sequential pipeline execution                         │
│           Yield events from agent[0], then agent[1], …         │
└─────────┬────────────┬───────┬──────┬───────┬──────────────────┘
          │            │       │      │       │
     price_agent  prediction  alert  tenk  comparison  trading
     alert_agent  _agent    _agent  _agent   pipeline   _agent
     financial…   …         …       …        …          …
          │
          ▼
┌─────────────────────────────────────────────────────────────────┐
│             Output Guardrails  (after_model_callback)           │
│  • PII detokenization + re-masking                              │
│  • Investment-advice warning injection                          │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
                          Final response
```

---

## Route Map

The `_ROUTE_MAP` in `agent.py` is the single source of truth for all pipelines. It maps an intent string to an ordered list of agents to execute. The orchestrator also sets a `model_tier` in session state after routing — `"cheap"` (gemini-2.5-flash, thinking disabled) for simple single-tool intents, `"full"` (gemini-2.5-flash, thinking enabled) for everything requiring reasoning or RAG:

| Intent                | Model tier | Pipeline agents (in order)                                  |
|-----------------------|------------|-------------------------------------------------------------|
| `PRICE`               | cheap      | `price_agent`                                               |
| `ALERT`               | cheap      | `alert_agent`                                               |
| `VISUALIZATION`       | cheap      | `visualization_agent`                                       |
| `PDF_REPORT`          | cheap      | `pdf_agent`                                                 |
| `PREDICTION`          | full       | `prediction_agent`                                          |
| `FINANCIAL_REPORT`    | full       | `financial_report_agent`                                    |
| `ANNUAL_REPORT`       | full       | `tenk_agent`                                                |
| `STOCK_COMPARISON`    | full       | `comparison_trend_agent` → `comparison_insights_agent`      |
| `INVESTMENT_RESEARCH` | full       | `investment_research_agent`                                 |
| `TRADE_ANALYSIS`      | full       | `trading_agent`                                             |
| `PRICE_PREDICTION`    | full       | `price_agent` → `prediction_agent`                          |
| `PRICE_PREDICT_CHART` | full       | `price_agent` → `prediction_agent` → `visualization_agent`  |
| `ANNUAL_FINANCIAL`    | full       | `tenk_agent` → `financial_report_agent`                     |
| `UNKNOWN`             | —          | Clarification message (no agent run)                        |

`intent_agent` always uses `gemini-2.5-flash` regardless of tier — it runs before the tier is set.

---

## GraphOrchestrator Internals

`stock_orchestrator` extends `BaseAgent` rather than `LlmAgent`, giving full control over agent sequencing without an LLM deciding what runs next.

```
class GraphOrchestrator(BaseAgent):

    async def _run_async_impl(self, ctx):

        # 0. Smart pending-trade bypass (runs BEFORE intent_agent)
        #    When a trade is awaiting approval and the user replies with a
        #    short approval/cancellation phrase ("yes", "buy", "no", "cancel",
        #    etc., ≤30 chars, whole-word match), skip intent classification
        #    and hand off straight to trading_agent so it can call
        #    execute_pending_trade / cancel_pending_trade.
        #
        #    If the user instead pivots to an unrelated request (PDF report,
        #    chart, comparison, etc.), auto-cancel the stale pending trade
        #    and fall through to normal intent classification — otherwise
        #    that request would be silently hijacked by trading_agent
        #    (which has no PDF/chart/etc. capability).
        if has_pending_trade():
            looks_like_approval = (
                len(user_text.strip()) <= 30
                and any(kw == user_text.strip().lower()
                        or user_text.strip().lower().startswith(kw + " ")
                        or user_text.strip().lower().endswith(" " + kw)
                        for kw in _APPROVE | _CANCEL)
            )
            if looks_like_approval:
                if not is_allowed(ctx.session.state.get("user_role", "viewer"), "TRADE_ANALYSIS"):
                    cancel_pending_trade()
                    yield forbidden_event(ctx, "TRADE_ANALYSIS")
                    return
                async for event in trading_agent.run_async(ctx):
                    yield event
                return
            # Stale pending — clear it and continue to intent classification
            cancel_pending_trade()
            yield _progress_event(
                ctx, "Previous trade proposal cancelled — handling new request…"
            )

        # 1. Always run intent_agent first
        async for event in intent_agent.run_async(ctx):
            if event.is_final_response():
                intent_json = parse(event.content)

        # 2. Determine pipeline from intent
        pipeline = _ROUTE_MAP.get(intent_json["intent"], [])

        if not pipeline:
            yield clarification_event()
            return

        # 3. Run each agent; validate output before chaining to the next
        for step, agent in enumerate(pipeline, start=1):
            step_events = []
            async for event in agent.run_async(ctx):
                step_events.append(event)
                yield event          # stream events to user in real time

            # Validate between steps — never on the last step (nothing chains after it)
            if step < len(pipeline):
                ok, reason = _validate_step_output(agent.name, step_events)
                if not ok:
                    yield _abort_event(ctx, agent.name, reason)
                    return           # stop pipeline — do not run remaining agents
```

The `ctx` (InvocationContext) carries the full conversation history, so later agents in a pipeline see the output of earlier ones.

**Output validation gate** (`_validate_step_output`): called between every consecutive step pair. It runs three pure-Python checks — no LLM call:

1. **Has content** — at least one non-empty text part was emitted
2. **No error text markers** — response does not contain any phrase from `_ERROR_MARKERS`:
   ```
   "status: error" | "unable to fetch" | "no data available" | "not found"
   "could not retrieve" | "failed to" | "error fetching" | "no results" | "unavailable"
   ```

If either check fails, `_abort_event` is yielded with a user-friendly explanation naming the failed step and reason, and the pipeline terminates early. The failure is also recorded in session state (`pipeline_aborted_at`, `pipeline_abort_reason`) for audit inspection.

---

## Callback Architecture

Every agent registers five callbacks. All callbacks are defined in `audit.py` and `guardrails.py`:

```
Agent lifecycle:
  before_agent_callback  ──► emit audit log "agent_start"
                               call tracing.on_agent_start()
  after_agent_callback   ──► emit audit log "agent_end"
                               call tracing.on_agent_end()

Model lifecycle (per LLM call inside an agent):
  before_model_callback  ──► emit audit log "llm_request"
                               run input guardrails
                               (may return synthetic LlmResponse to abort)
  after_model_callback   ──► emit audit log "llm_response"
                               run output guardrails

Tool lifecycle (per tool call inside an agent):
  before_tool_callback   ──► emit audit log "tool_start"
                               call tracing.on_tool_start()
  after_tool_callback    ──► emit audit log "tool_end"
                               call tracing.on_tool_end()
```

---

## Compound Pipeline: End-to-End Message Flow

**Query**: "Show me MSFT's price then predict the next 2 weeks"

```
User ──► stock_orchestrator
          │
          ├─► intent_agent
          │      LLM call (Gemini 2.5-flash)
          │      Input: "Show me MSFT's price then predict the next 2 weeks"
          │      Output: {
          │        "intent": "PRICE_PREDICTION",
          │        "companies": ["MSFT"],
          │        "time_horizon": "2 weeks",
          │        "output_format": "text"
          │      }
          │      (JSON not shown to user)
          │
          ├─► _route("PRICE_PREDICTION") = [price_agent, prediction_agent]
          │
          ├─► price_agent  (step 1 of 2)
          │      Tool: resolve_ticker("MSFT") → "MSFT"
          │      Tool: get-ticker-info("MSFT")
          │              MCP call → finance_mcp_server subprocess
          │              Returns: {price: 425.30, change_pct: +1.2%, market_cap: 3.16T}
          │      LLM formats response
          │      ──► streams: "Microsoft (MSFT) is trading at $425.30..."
          │
          ├─► _validate_step_output("price_agent", step_events)
          │      ✓ has_content: response text is non-empty
          │      ✓ no error markers: "425.30" contains no failure phrases
          │      → (True, "") — proceed to prediction_agent
          │
          └─► prediction_agent  (step 2 of 2, sees price_agent output in history)
                 Tool: resolve_ticker("MSFT") → "MSFT"
                 Tool: fetch_and_forecast("MSFT")
                         yfinance.download("MSFT", period="3mo")
                         OLS regression on 63 days of closes
                         Returns: {forecast_table: [...], trend: "up", pct_change: 4.2}
                 LLM formats forecast table + trend description + disclaimer
                 ──► streams: "Based on the last 3 months, MSFT is trending upward..."
                 [last step — validation skipped]

Final response shown to user: price summary + 14-day forecast table

**Early abort example** (ticker not found):

```
price_agent  ──► "Error fetching data: not found for ticker 'XYZQ'"
                         │
                         ▼
          _validate_step_output("price_agent", ...)
               ✗ marker found: "not found"
               → (False, "response contains 'not found'")
                         │
                         ▼
          _abort_event yielded to user:
          "I couldn't continue because the previous step (price_agent)
           didn't return usable data: response contains 'not found'.
           Please try rephrasing your request or check that the ticker is valid."

prediction_agent  ← never runs
```
```

---

## Session and State Management

- **Session service**: `SqliteSessionService` (persists full event history in `sessions.db`; survives server restarts)
- **Session ID**: Created at conversation start; all pipeline agents share the same session
- **Context passing**: Each agent receives the same `InvocationContext`, which contains the full `session.events` list — later agents read earlier agents' output through conversation history, not via explicit variable passing
- **Invocation ID**: Unique per user turn (e.g., `e-d3f2918e-03c7`); used to correlate audit logs and tracing spans

**Pipeline state keys** written to `ctx.session.state` during orchestration:

| Key | Written when | Value |
|-----|--------------|-------|
| `pipeline` | Pipeline starts | Intent string (e.g. `"PRICE_PREDICTION"`) |
| `pipeline_total` | Pipeline starts | Total number of steps |
| `pipeline_step` | Before each step | Current step number (1-based) |
| `model_tier` | Pipeline starts | `"cheap"` or `"full"` — read by `before_model_token_guardrail` to swap model |
| `pipeline_aborted_at` | Validation fails | Name of the agent that failed |
| `pipeline_abort_reason` | Validation fails | Human-readable failure reason |

---

## Adding a New Pipeline

1. Implement the specialist agent (extend `LlmAgent`)
2. Add a new intent constant to `intent_agent.py`'s system prompt
3. Add a new entry to `_ROUTE_MAP` in `agent.py`
4. Add corresponding intent + E2E test cases in `eval/cases.py`
