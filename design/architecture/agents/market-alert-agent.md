# Market Alert Agent

## Overview

The market alert system gives every FinanceAI user a persistent, personalised market watch. It has two complementary layers that work together to cover both on-demand and proactive monitoring:

| Layer | Component | Model | Lifecycle | Trigger | Output |
|-------|-----------|-------|-----------|---------|--------|
| **Chat alert** | `alert_agent` (ADK `LlmAgent`) | `gemini-2.5-flash` | One-shot per user turn | User query: "which stocks dropped today?" | Formatted chat response |
| **Background monitor** | `alert_monitor.py` (asyncio task) + `monitor_analyst_agent` | `gemini-2.5-flash` (via ADK, no thinking) | Always running | 15-min poll of user-configured rules | Push notification + optional email |

The two layers share no code but form a coherent user experience: the chat agent handles ad-hoc queries; the background monitor handles persistent watchlists that fire even when the user is not in a session.

---

## Table of Contents

1. [Chat Alert Agent — `alert_agent`](#1-chat-alert-agent--alert_agent)
2. [Background Alert Monitor](#2-background-alert-monitor)
3. [Alert Types and Condition Logic](#3-alert-types-and-condition-logic)
4. [Alert Content Generation](#4-alert-content-generation)
5. [Notification Delivery](#5-notification-delivery)
6. [Data Model](#6-data-model)
7. [Integration Points](#7-integration-points)
8. [Message Flows](#8-message-flows)
9. [Design Decisions](#9-design-decisions)
10. [Configuration Reference](#10-configuration-reference)

---

## 1. Chat Alert Agent — `alert_agent`

### Purpose

Evaluates whether any monitored stock has dropped by more than a configurable percentage from its previous close. This is a one-shot conversational check — no scheduling, no persistence, no push. The user asks; the agent checks and responds.

### Configuration

| Field | Value |
|-------|-------|
| Name | `alert_agent` |
| Model | `gemini-2.5-flash` |
| Max output tokens | Inherited from `model_config.py` |
| Runs in pipeline | `ALERT` |
| Direct Python tools | `resolve_ticker`, `evaluate_drop_alerts` |
| MCP tools | `get-ticker-info` |
| System prompt | `skills/alert_agent/SKILL.md` |
| Disclaimer required | Yes — added to `_DISCLAIMER_REQUIRED_AGENTS` |
| Default watchlist | MSFT, NVDA, CRM (3 tickers — reduced from 10 to stay within context budget) |
| Default threshold | 5% |

### Tools

#### `resolve_ticker(name_or_ticker: str) -> str`

Normalises a company name or partial ticker to a canonical uppercase ticker symbol. Covers 40+ software-sector names (e.g. "Snowflake" → `SNOW`, "google" → `GOOGL`). Unknown names pass through as-is; yfinance will raise an error downstream if the symbol is invalid.

#### `get-ticker-info(ticker: str)` (MCP)

Fetches the full ticker info blob from Yahoo Finance via the Finance MCP server. The alert agent reads three fields:
- `currentPrice` — real-time last price
- `previousClose` — prior session's official close
- `regularMarketChangePercent` — intraday % change (used as a cross-check)

#### `evaluate_drop_alerts(stocks: list[dict], threshold_percent: float) -> dict`

Pure Python computation — no network calls. Accepts a list of `{ticker, current_price, previous_close}` dicts, computes `change_percent = (current_price - previous_close) / previous_close * 100` for each, and splits results into `alerts` (change < -threshold) and `safe` lists.

```
Input:
  stocks = [
    {"ticker": "SNOW", "current_price": 123.40, "previous_close": 137.80},
    {"ticker": "MSFT", "current_price": 425.30, "previous_close": 420.08},
    {"ticker": "NVDA", "current_price": 887.60, "previous_close": 862.00}
  ]
  threshold_percent = 5.0

Output:
  {
    "status": "success",
    "threshold_percent": 5.0,
    "alerts": [
      {"ticker": "SNOW", "company": "Snowflake Inc.",
       "current_price": 123.40, "previous_close": 137.80,
       "change_percent": -10.44}
    ],
    "safe": [
      {"ticker": "MSFT", "company": "Microsoft Corporation",
       "current_price": 425.30, "previous_close": 420.08,
       "change_percent": +1.24},
      {"ticker": "NVDA", "company": "NVIDIA Corporation",
       "current_price": 887.60, "previous_close": 862.00,
       "change_percent": +2.97}
    ]
  }
```

### Workflow

```
alert_agent
    │
    ├─ Step 1: Determine ticker list
    │     • Use tickers from intent JSON ("companies") if provided
    │     • Otherwise use default watchlist (MSFT, NVDA, CRM)
    │     • Orchestrator injects defaults if companies=[] in routing event
    │       (prevents empty-list context pollution that produces no output)
    │
    ├─ Step 2: For each ticker:
    │     resolve_ticker(name_or_ticker)   → canonical symbol
    │     get-ticker-info(ticker)          → currentPrice, previousClose
    │
    ├─ Step 3: evaluate_drop_alerts(stocks, threshold)
    │     Pure Python: classify each stock as alert / safe
    │
    └─ Step 4: LLM formats response
          • Header: threshold used, current date
          • Triggered alerts: company, ticker, price, % drop (sorted most severe first)
          • Safe summary: count or explicit list of safe stocks
          • If no alerts: explicit "all safe" confirmation — never empty response
```

### Output format (representative)

```
Drop Alert Check (threshold: 5%) — 2026-05-09

🚨 TRIGGERED (1 stock):
• Snowflake (SNOW): $123.40  ↓ -10.44%  (prev. close: $137.80)

✅ SAFE (2 stocks):
• Microsoft (MSFT): $425.30  ↑ +1.24%
• NVIDIA (NVDA):    $887.60  ↑ +2.97%

⚠️ This is factual market data, not financial advice.
```

---

## 2. Background Alert Monitor

### Purpose

A persistent asyncio background task (`alert_monitor.py`) started at server boot. It polls all enabled user-defined alert configurations every 15 minutes, evaluates conditions against live market data, and — when a condition is met — generates a structured alert report using Gemini Flash and delivers it in-browser via SSE and optionally via SMTP email.

### Configuration

| Field | Value |
|-------|-------|
| Module | `stock_agent/alert_monitor.py` |
| Persistence | `stock_agent/alert_store.py` → `stock_agent/alerts.db` (SQLite, WAL) |
| Poll interval | 900 seconds (15 minutes) — `POLL_INTERVAL_SECONDS` |
| Cooldown | 4 hours per (config_id, ticker) — `COOLDOWN_HOURS` |
| Content agent | `monitor_analyst_agent` (ADK `LlmAgent`, ephemeral `InMemorySessionService`) |
| Started by | `asyncio.create_task(alert_monitor.monitor_loop())` in `_on_startup()` |
| SSE queue registry | Module-level `_sse_queues: dict[str, set[asyncio.Queue]]` |
| Cooldown tracking | Module-level `_last_fired: dict[tuple, datetime]` (in-memory) |

### Key functions

| Function | Description |
|----------|-------------|
| `monitor_loop()` | Main coroutine. Infinite loop: sleep → poll → repeat. Updates `_monitor_status`. |
| `_process_config(config, loop)` | Per-config coroutine. Iterates over tickers, evaluates, fires if triggered. |
| `_fetch_price_data(ticker)` | Calls `yf.Ticker(ticker)` → returns price snapshot dict. |
| `_evaluate(config, price_data, portfolio)` | Pure Python condition checks. Returns `(triggered: bool, matched: dict)`. |
| `_run_alert_agent(config, ticker, price_data, matched, user_id)` | Creates an ephemeral ADK session, invokes `monitor_analyst_agent`, parses JSON response. Returns 4-field content dict. |
| `_push_sse(user_id, payload)` | Async. Puts payload to every queue in `_sse_queues[user_id]`. |
| `_send_email(user_id, notification)` | Threaded SMTP send. Non-blocking. Sets `email_sent=1` on success. |
| `subscribe_sse(user_id) -> asyncio.Queue` | Creates and registers a queue for an open browser connection. |
| `unsubscribe_sse(user_id, q)` | Removes queue on disconnect. |
| `get_monitor_status() -> dict` | Returns runtime stats for the `/api/alerts/monitor-status` endpoint. |

### Evaluation pipeline (per ticker per poll)

```
1. Fetch price snapshot          yf.Ticker(ticker).fast_info + .history(1d)
        │
        ▼
2. Cooldown check                _last_fired[(config_id, ticker)] < now - 4h?
        │ not on cooldown
        ▼
3. Portfolio lookup (if needed)  get_portfolio() for allocation checks
        │
        ▼
4. Condition evaluation          _evaluate(config, price_data, portfolio)
   Pure Python — no LLM          → triggered=True/False, matched={...}
        │ triggered=True
        ▼
5. Set cooldown                  _last_fired[(config_id, ticker)] = now
        │
        ▼
6. Generate content              _run_alert_agent()  → monitor_analyst_agent (ADK ephemeral session)
        │
        ▼
7. Persist notification          alert_store.create_notification()  → alerts.db
        │
        ▼
8. Push SSE                      _push_sse(user_id, payload)
        │
        ▼
9. Send email (if enabled)       _send_email()  [executor thread]
```

**Cost profile**: Steps 1–5 are cheap (one yfinance HTTP call + pure Python). Step 6 (Gemini Flash) is only reached when a condition fires — which is rare in normal market conditions. Across a calm trading day, the monitor may make dozens of yfinance calls but zero LLM calls.

---

## 3. Alert Types and Condition Logic

Three alert types are supported, each mapping to a distinct investment hypothesis.

### 3.1 `buy_opportunity` — Accumulation signal during pullbacks

**Logic**: ALL conditions must be true simultaneously.

| Condition | Parameter | Default | Data source |
|-----------|-----------|---------|-------------|
| Price has pulled back from its 52-week high | `price_drop_pct` | `8%` | `yf.Ticker.fast_info.fifty_two_week_high` |
| Revenue growth is positive (TTM) | `check_revenue_growth` | `true` | `yf.Ticker.info["revenueGrowth"]` |
| Debt is stable | `check_debt_stability` | `false` | `yf.Ticker.info["debtToEquity"]` < 200 |
| Position headroom (not already over-allocated) | `max_portfolio_pct` | `10%` | `get_portfolio()` aggregate from `trades.jsonl` |

```python
triggered = (
    price_ok              # price ≤ high × (1 - price_drop_pct/100)
    and rev_ok            # revenueGrowth > 0  (if check_revenue_growth)
    and debt_ok           # debtToEquity < 200  (if check_debt_stability)
    and alloc_ok          # position_pct < max_portfolio_pct
)
```

**Rationale**: Requires multiple confirming factors to avoid false positives on volatile stocks that pull back for fundamental reasons.

### 3.2 `sell_signal` — Capital protection trigger

**Logic**: ANY condition is sufficient to trigger.

| Condition | Parameter | Default | Data source |
|-----------|-----------|---------|-------------|
| Price has fallen below cost basis by stop-loss % | `stop_loss_pct` | `15%` | avg_cost from `trades.jsonl`; current price from yfinance |
| Position has grown beyond max allocation | `max_portfolio_pct` | `15%` | `get_portfolio()` aggregate |

```python
triggered = stop_loss_breach OR allocation_breach
```

**Rationale**: OR logic because either scenario (drawdown or concentration) independently warrants review.

### 3.3 `price_move` — Momentum / volatility alert

**Logic**: Absolute or directional intraday move.

| Condition | Parameter | Default |
|-----------|-----------|---------|
| % change vs previous close | `price_change_pct` | `5%` |
| Direction filter | `direction` | `either` |

```python
if direction == "either":   triggered = abs(change_pct) >= threshold
if direction == "up":       triggered = change_pct >= threshold
if direction == "down":     triggered = change_pct <= -threshold
```

**Rationale**: Directional control lets users create asymmetric alerts (e.g. "alert me only on upside breakouts").

### 3.4 Portfolio data access

For allocation checks, the monitor sets the `audit_user_id` context variable before calling `get_portfolio()`, which reads `trades.jsonl` scoped to that user. This reuses the same function as the trading agent — one source of truth for portfolio state.

```python
tok = audit_user_id.set(user_id)
try:
    portfolio = await loop.run_in_executor(None, get_portfolio)
finally:
    audit_user_id.reset(tok)
```

---

## 4. Alert Content Generation

When a condition fires, `_run_alert_agent()` invokes `monitor_analyst_agent` — a dedicated ADK `LlmAgent` whose sole purpose is enriching a pre-detected condition snapshot with investment context and returning a structured JSON analysis.

### Why a dedicated `monitor_analyst_agent`, not `alert_agent`?

The existing `alert_agent` has a system prompt that instructs it to produce **human-readable formatted text** (drop alert summaries for the chat window). When the monitor sent it a JSON-output request, the system prompt won — the agent returned prose, JSON parsing failed, and the fallback fired on every trigger.

`monitor_analyst_agent` has a **JSON-only system prompt** (`prompts/monitor_analyst_v1.md`) that mirrors the schema exactly. It never outputs anything other than a valid JSON object. The two agents are intentionally separate:

| Agent | Used by | System prompt goal | Output |
|---|---|---|---|
| `alert_agent` | Chat pipeline (ALERT intent) | Check if a drop occurred; format summary for the user | Human-readable text |
| `monitor_analyst_agent` | Background monitor only | Enrich a pre-detected condition with context | JSON only |

### Why LLM here, not earlier?

Condition evaluation is deterministic arithmetic — no LLM needed. The LLM is invoked only at the point of content generation, ensuring:
- **Cost**: LLM calls scale with trigger frequency, not poll frequency
- **Accuracy**: The LLM receives confirmed factual data (not raw price streams) as its context
- **Quality**: Gemini interprets and contextualises the conditions for the user rather than outputting raw numbers

### Agent configuration

| Field | Value |
|-------|-------|
| File | `stock_agent/monitor_analyst_agent.py` |
| System prompt | `prompts/monitor_analyst_v1.md` (version-pinned via `load_prompt`) |
| Tools | `get-ticker-info` only (supplementary data beyond the pre-fetched snapshot) |
| Thinking | Disabled (`thinking_budget=0`) — deterministic JSON output, no reasoning needed |
| Sessions | Ephemeral `InMemorySessionService` — created and deleted within `_run_alert_agent()` |
| Guardrails | Full stack: `before_agent_callback`, `after_agent_callback`, `before_tool_callback`, `after_tool_callback`, `before_model_context_trim_guardrail_with_audit`, `after_model_output_guardrail_with_audit` |

### Invocation flow

```python
# Ephemeral session scoped to this trigger
session_id = f"monitor-{config_id[:8]}-{ticker}-{uuid4().hex[:8]}"
await _alert_session_service.create_session(app_name=_MONITOR_APP, user_id=user_id, session_id=session_id)

prompt = _build_monitor_prompt(config, ticker, price_data, matched)
# prompt contains: alert_type, alert_name, ticker, company, full price snapshot,
# triggered_conditions JSON — monitor_analyst_agent does NOT re-verify conditions

async for event in _alert_runner.run_async(user_id, session_id, new_message=prompt):
    if event.is_final_response():
        response_text += part.text   # collect JSON output

result = _parse_agent_response(response_text, alert_type, ticker,
                                price_data=price_data, matched=matched)
# → normalises next_steps list → "\n"-joined string if needed
# → falls back to _fallback_content() on parse failure

# session auto-cleaned by InMemorySessionService
```

### Prompt structure (sent to `monitor_analyst_agent`)

```
Alert name:   {config_name}
Alert type:   {alert_type}
Ticker:       {ticker} ({company})

Price snapshot (pre-fetched):
  Current price:    ${current_price}
  52-week high:     ${high_52w}
  Drop from high:   {drop_pct}%
  Previous close:   ${prev_close}
  Revenue growth:   {revenue_growth}
  Debt/equity:      {debt_to_equity}
  Trailing P/E:     {trailing_pe}

Triggered conditions:
{matched_conditions_json}

Respond with ONLY a valid JSON object — no markdown fences, no extra text.
```

### Output schema

```json
{
  "what_happened":  "<1-2 sentences: factual, uses concrete numbers>",
  "why_it_matters": "<2-3 sentences: investment significance and context>",
  "confidence":     "HIGH" | "MEDIUM" | "LOW",
  "next_steps":     "<2-3 bullet points starting with •; no trade directives>"
}
```

### Confidence calibration

| Level | When to use |
|-------|-------------|
| `HIGH` | All conditions met clearly; multiple confirming data points; data is fresh |
| `MEDIUM` | Conditions met but some values are marginal or borderline |
| `LOW` | Early or weak signal; single condition barely met; data may be stale |

### `next_steps` normalisation

The LLM occasionally returns `next_steps` as a JSON array (`["• point 1", "• point 2"]`) instead of a newline-separated string. `_parse_agent_response` normalises this after successful JSON parse:

```python
if isinstance(result["next_steps"], list):
    result["next_steps"] = "\n".join(result["next_steps"])
```

This is idempotent — if `next_steps` is already a string, no transformation occurs.

### Fallback (agent call fails or returns unparseable output)

`_fallback_content(alert_type, ticker, price_data=None, matched=None)` produces a factual notification from the pre-fetched snapshot rather than a generic placeholder:

```python
# Example output with price_data and matched available:
{
    "what_happened":  "SAP buy opportunity triggered — price $173.70; 12.3% below 52-week high; conditions met: price drop, revenue growth.",
    "why_it_matters": "Key metrics: revenue growth +8.5%, trailing P/E 28.4. Alert conditions confirmed by the background monitor.",
    "confidence":     "MEDIUM",
    "next_steps":     "• Review SAP recent news and earnings\n• Check your portfolio allocation\n• Consult your investment plan before acting",
}
```

Both call sites in `_run_alert_agent` pass `price_data=price_data, matched=matched` through so even the worst-case path produces an informative notification. The raw agent response is logged at WARNING level (up to 300 chars) for diagnosis before falling back.

### No-auto-trade guarantee

The `monitor_analyst_v1.md` system prompt explicitly forbids trade directives in `next_steps`. Additionally:
- `alert_monitor.py` imports no trade execution functions
- The notification detail modal displays: *"No trades have been or will be executed automatically without your explicit approval."*
- Email templates carry the same disclaimer footer

---

## 5. Notification Delivery

### 5.1 In-app SSE

```
monitor_loop fires condition
        │
        ▼
create_notification() → INSERT INTO alert_notifications (alerts.db)
        │
        ▼
_push_sse(user_id, {
    "type": "alert_notification",
    "notification": {notification dict},
    "unread_count": N
})
        │
        for each asyncio.Queue in _sse_queues[user_id]:
            q.put_nowait(payload)
        │
        ▼
Browser EventSource receives "alert_notification" event
        ├─ updateBadge(unread_count)          → red badge on bell + tab dot
        ├─ showAlertToast(ticker, summary)    → 8-second overlay toast
        ├─ renderAlertNotifications()         → updates notification side panel
        └─ if Alerts tab is open:
               loadAlertsTab()               → refreshes dashboard
```

**SSE connection management:**

```
GET /api/alerts/stream?token=<jwt>
        │
subscribe_sse(user_id)      → creates asyncio.Queue, inserts into _sse_queues[user_id]
        │
yields {"type": "connected"}
        │
loop:
    q.get() [awaits message]
    yield f"data: {json.dumps(msg)}\n\n"
    │
    heartbeat every 30s: {"type": "heartbeat"}
    │
finally:
    unsubscribe_sse(user_id, q)  → removes queue from set on disconnect
```

**Auth note**: The browser `EventSource` API cannot set `Authorization` headers. The endpoint accepts the JWT as a `?token=` query parameter, validated identically to a Bearer token by `_require_auth`.

Browser auto-reconnects via `EventSource.onerror` → `setTimeout(reconnect, 30000)` on network drop.

### 5.2 Email

Optional. Enabled per-user via `PUT /api/alerts/settings`. SMTP credentials live exclusively in server environment variables — never stored in the database or exposed to the browser.

**Send flow:**

```python
if user_settings["email_alerts_enabled"]:
    loop.run_in_executor(None, _send_email_sync, user_id, notification)
    # non-blocking: does not delay SSE push
    # on success: UPDATE alert_notifications SET email_sent = 1
```

**Email content:**
- Subject: `FinanceAI Alert: {alert_type} — {ticker}`
- Body: HTML table with what_happened, why_it_matters, confidence badge, next_steps bullet list
- Footer: *"This is an informational alert only. No trades have been or will be executed automatically without your explicit approval."*
- Failure: logged to audit; SSE notification already delivered independently

### 5.3 Delivery independence

SSE and email are independent paths. A failure in email delivery (SMTP timeout, bad credentials) does not affect in-app notification. A user with no browser tab open still receives the email. A user with no email configured still receives the in-app notification at next login (notifications are persisted in SQLite with `is_read = 0`).

### 5.4 Chat Follow-Up

Any notification can be escalated into a full chat conversation via the **Continue in Chat →** button (available on toast, notification cards, and the detail modal). This bridges the `alerts.db` notification world and the `sessions.db` chat world.

**Flow:**
1. User clicks **Continue in Chat →** on any notification surface
2. `_continueAlertInChat(notif)` runs in the browser:
   - Calls `switchTab('chat')` + `newSession()` — fresh session, no contamination of existing conversations
   - Pre-fills `#user-input` with a framed draft message
3. Draft message structure:
   ```
   My market alert monitor has already confirmed a {alert_type} signal for {ticker} (triggered {ts}).

   Alert details:
   • Confidence: {conf}
   • What happened: {what_happened}
   • Why it matters: {why_it_matters}
   • Suggested next steps: {next_steps}

   Please give me a deeper analysis of {ticker} and help me decide what to do next.
   ```
4. User edits the draft (adds a specific question) and presses Send
5. Orchestrator routes based on the full message — typical routes:
   - "deeper analysis" → `investment_research_agent`
   - "show me the chart" → `visualization_agent`
   - "what does the 10-K say" → `tenk_agent`
   - "I want to buy" → `trading_agent` (two-turn approval — unchanged)

**Why the draft is pre-framed (not raw alert fields):**
The phrase "already confirmed a signal" tells the intent agent not to re-verify conditions. Without this, the agent would check the current price, find it hasn't moved 5% *today*, and report no alert — because it doesn't know the alert was based on a 52-week-high comparison, not a daily change.

**Safety guarantee:** The draft is never sent automatically. The user must press Send, preserving the trading agent's two-turn approval requirement.

---

## 6. Data Model

Three SQLite tables in `stock_agent/alerts.db` (WAL journal mode).

### `alert_configs` — User-defined monitoring rules

```sql
CREATE TABLE alert_configs (
    id          TEXT PRIMARY KEY,       -- uuid4
    user_id     TEXT NOT NULL,          -- JWT "sub" (username)
    name        TEXT NOT NULL,          -- user-defined label, e.g. "MSFT buy dip"
    enabled     INTEGER NOT NULL DEFAULT 1,  -- 0 = paused by user
    tickers     TEXT NOT NULL,          -- JSON array: ["MSFT", "NVDA"]
    alert_type  TEXT NOT NULL,          -- "buy_opportunity" | "sell_signal" | "price_move"
    conditions  TEXT NOT NULL,          -- JSON dict of typed condition parameters
    created_at  TEXT NOT NULL,          -- ISO-8601 UTC
    updated_at  TEXT NOT NULL
);
CREATE INDEX idx_cfg_user ON alert_configs(user_id);
```

Example row:
```json
{
  "id": "a3f1...",
  "user_id": "analyst1",
  "name": "MSFT buy-on-dip",
  "enabled": true,
  "tickers": ["MSFT"],
  "alert_type": "buy_opportunity",
  "conditions": {
    "price_drop_pct": 8,
    "check_revenue_growth": true,
    "check_debt_stability": false,
    "max_portfolio_pct": 10
  }
}
```

### `alert_notifications` — Triggered alert records

```sql
CREATE TABLE alert_notifications (
    id              TEXT PRIMARY KEY,       -- uuid4
    user_id         TEXT NOT NULL,
    config_id       TEXT,                   -- FK to alert_configs.id (nullable)
    config_name     TEXT,                   -- snapshot at trigger time
    triggered_at    TEXT NOT NULL,          -- ISO-8601 UTC
    ticker          TEXT NOT NULL,
    alert_type      TEXT NOT NULL,
    what_happened   TEXT NOT NULL,          -- Gemini-generated (or fallback)
    why_it_matters  TEXT NOT NULL,
    confidence      TEXT NOT NULL,          -- "HIGH" | "MEDIUM" | "LOW"
    next_steps      TEXT NOT NULL,
    raw_data        TEXT,                   -- JSON: price snapshot + matched_conditions
    is_read         INTEGER NOT NULL DEFAULT 0,
    email_sent      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_notif_user ON alert_notifications(user_id);
```

### `user_alert_settings` — Email preferences

```sql
CREATE TABLE user_alert_settings (
    user_id                 TEXT PRIMARY KEY,
    notification_email      TEXT,               -- where to send alerts
    email_alerts_enabled    INTEGER NOT NULL DEFAULT 0,
    updated_at              TEXT NOT NULL
);
```

---

## 7. Integration Points

### 7.1 Orchestrator (`stock_agent/agent.py`)

**ALERT intent routing with default injection:**

The intent agent may return `companies: []` for a sector-wide alert query ("Are any stocks down today?"). If left as-is, the routing event stores an empty list in session state, and the `alert_agent` LLM sees `companies: []` and produces no tool calls.

Fix: the orchestrator injects the agent's default watchlist into the routing event when `intent=ALERT` and `companies=[]`:

```python
if intent == "ALERT" and not companies:
    companies = ["MSFT", "NVDA", "CRM"]  # inject default watchlist
```

**`_ROUTE_MAP` entry:**

```python
"ALERT": [alert_agent]
```

### 7.2 Intent Agent (`prompts/intent_agent_v1.md`)

The `ALERT` intent is classified when the user asks for:
- Drop/fall monitoring ("which stocks dropped today", "alert me if anything fell 5%")
- Sector health checks ("how is the software sector doing")
- Threshold queries ("is SNOW down more than 10%")

Entity extraction: `alert_threshold_percent` (float, defaults to 5.0 if not mentioned), `companies` (list of tickers/names, may be empty).

### 7.3 Guardrails (`stock_agent/guardrails.py`)

`alert_agent` uses `before_model_context_trim_guardrail_with_audit` as its `before_model_callback`. This:

1. **Trims context**: strips accumulated session history to only the current invocation — prevents token bloat when the chat session is long
2. **Checks PII**: tokenises any personal data before the LLM sees it
3. **Checks token limit**: blocks if estimated tokens > 120 000
4. **Injects memory context**: adds relevant past conversation context as `<PAST_CONVERSATIONS>` system instruction
5. **Audits**: logs the request to `audit.log`

`after_model_output_guardrail` fires on every response, detokenising PII and checking for inappropriate financial advice patterns.

`alert_agent` is listed in `_DISCLAIMER_REQUIRED_AGENTS` — if no disclaimer phrase is found in a response, `disclaimer_missing` is logged and a warning is emitted.

### 7.4 Alert Monitor (`stock_agent/alert_monitor.py`)

The background monitor starts independently of the chat `alert_agent` — they share no code and no runtime state. The connection between them is conceptual (both serve the "alert" use case) and via `alert_store.py` (the monitor writes notifications; the chat agent does not).

The monitor's REST API and SSE stream are exposed by `web_server.py` alongside the chat API, creating a unified surface for the user.

### 7.5 Alert Store (`stock_agent/alert_store.py`)

The chat `alert_agent` does **not** use `alert_store`. Its results are transient chat responses. The background monitor uses `alert_store` exclusively for persistence.

### 7.6 Web Server (`web_server.py`)

**Alert monitor startup:**
```python
@app.on_event("startup")
async def _on_startup():
    ...
    asyncio.create_task(alert_monitor.monitor_loop())
```

**REST API endpoints** (all require JWT authentication):

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/alerts/configs` | List user's configs |
| `POST` | `/api/alerts/configs` | Create config |
| `PATCH` | `/api/alerts/configs/{id}` | Update/toggle config |
| `DELETE` | `/api/alerts/configs/{id}` | Delete config |
| `GET` | `/api/alerts/notifications` | List notifications (`?unread_only=true`) |
| `GET` | `/api/alerts/notifications/count` | Unread count |
| `POST` | `/api/alerts/notifications/{id}/read` | Mark one read |
| `POST` | `/api/alerts/notifications/read-all` | Mark all read |
| `GET` | `/api/alerts/stream` | SSE stream (JWT via `?token=`) |
| `GET` | `/api/alerts/settings` | Get email settings |
| `PUT` | `/api/alerts/settings` | Update email settings |
| `GET` | `/api/alerts/monitor-status` | Live monitor stats + recent notifications |

**Monitor status response shape:**
```json
{
  "monitor": {
    "running": true,
    "last_poll_at": "2026-05-09T10:15:00Z",
    "next_check_at": "2026-05-09T10:30:00Z",
    "poll_interval_seconds": 900
  },
  "summary": {
    "configs_total": 3,
    "configs_enabled": 2,
    "notifications_total": 17,
    "notifications_unread": 2,
    "triggers_today": 3
  },
  "configs": [
    {
      "id": "...",
      "name": "MSFT buy-on-dip",
      "enabled": true,
      "tickers": ["MSFT"],
      "last_triggered": "2026-05-08T14:22:00Z",
      "on_cooldown_tickers": []
    }
  ],
  "recent_notifications": [...]
}
```

`triggers_today` = count of notifications with `triggered_at` within the last 24 hours, computed in the endpoint (no extra DB query — derived from the fetched notifications list).

### 7.7 UI — Alerts Tab (`static/index.html`)

**Alerts tab** (visible to all roles):

- **Stats bar**: Monitor status (● Running), **Triggers Today** (notifications fired in last 24 h, sourced from `summary.triggers_today`), Total configured, Unread count, Next check countdown
- **Agent cards grid**: One card per config — name, alert type, ticker badges, condition summary bullets, cooldown indicator, last triggered, pause/resume toggle, delete button
- **Notification log table**: 10 most recent — ticker, config name, type, summary preview, confidence badge, relative time, click to open detail modal

**Alert side panel** (accessible from bell icon in header, visible from any tab):

- Bell icon with animated red badge (shows unread count)
- Notification cards (unread: blue left border; newest first)
- Active monitors list with on/off toggles
- Detail modal: what happened, why it matters, confidence (colour-coded: green=HIGH, amber=MEDIUM, grey=LOW), next steps bullets, no-auto-trade disclaimer; **💬 Continue in Chat →** button at bottom

**Toast notifications**: 8-second overlay (bottom-right) when SSE pushes a new alert. Shows ticker, alert type, confidence, and truncated `what_happened`. Two buttons: **View →** (opens alert side panel) and **Continue in Chat →** (creates a new chat session pre-seeded with alert context).

**Alert detail modal**: Opens on notification card click. Shows full what_happened, why_it_matters, confidence, next_steps, no-auto-trade disclaimer, and a **💬 Continue in Chat →** button.

**Alert setup modal** (triggered by "New Alert" button):

| Field | Type | Description |
|-------|------|-------------|
| Alert name | text | Free-form label |
| Alert type | select | buy_opportunity / sell_signal / price_move |
| Tickers | searchable inline picker | Search by symbol or company name; click to add as chip; custom tickers supported; selected shown with ✓ |
| Conditions | dynamic form | Parameters vary by alert type (see §3) |

---

## 8. Message Flows

### 8.1 Chat alert — user asks about drops

```
User: "Are any software stocks down more than 8% today? Check MSFT, SNOW, NVDA"

stock_orchestrator
    │
    ├─► intent_agent
    │     Output: {
    │       "intent": "ALERT",
    │       "companies": ["MSFT", "SNOW", "NVDA"],
    │       "alert_threshold_percent": 8.0
    │     }
    │
    └─► alert_agent
          │
          ├─► resolve_ticker("MSFT")  → "MSFT"
          ├─► get-ticker-info("MSFT") → {currentPrice: 425.30, previousClose: 420.08}
          │
          ├─► resolve_ticker("SNOW")  → "SNOW"
          ├─► get-ticker-info("SNOW") → {currentPrice: 123.40, previousClose: 137.80}
          │
          ├─► resolve_ticker("NVDA")  → "NVDA"
          ├─► get-ticker-info("NVDA") → {currentPrice: 887.60, previousClose: 862.00}
          │
          ├─► evaluate_drop_alerts(
          │     stocks=[
          │       {ticker:"MSFT", current_price:425.30, previous_close:420.08},
          │       {ticker:"SNOW", current_price:123.40, previous_close:137.80},
          │       {ticker:"NVDA", current_price:887.60, previous_close:862.00}
          │     ],
          │     threshold_percent=8.0
          │   )
          │   → alerts: [{SNOW, -10.44%}]
          │   → safe:   [{MSFT, +1.24%}, {NVDA, +2.97%}]
          │
          └─► LLM formats response:
                "Drop Alert Check (threshold: 8%) — 2026-05-09
                 🚨 TRIGGERED: Snowflake (SNOW) $123.40 ↓ -10.44%
                 ✅ SAFE: Microsoft (MSFT) +1.24% · NVIDIA (NVDA) +2.97%"
```

### 8.2 Background monitor — condition fires

```
FastAPI boot
    └─► asyncio.create_task(alert_monitor.monitor_loop())

[15 minutes later]

monitor_loop wakes
    └─► get_all_enabled_configs()         → [{config: "MSFT buy-on-dip", ...}]
         └─► for ticker "MSFT":
               _fetch_price_data("MSFT")  → {price:380.00, high52w:450.00, rev:0.12, ...}
               cooldown check             → not on cooldown ✓
               get_portfolio()            → {MSFT: {shares:10, avg_cost:395.00}}
               _evaluate(config, data)    → triggered=True
                                            matched={price_drop_pct:"15.6% from high",
                                                     revenue_growth:"positive (12%)",
                                                     allocation:"2.3% < 10% limit"}
               _last_fired[("cfg-id","MSFT")] = now  (start 4h cooldown)
               _run_alert_agent()        → monitor_analyst_agent (ADK ephemeral session)
                 → {what_happened: "MSFT has fallen 15.6% from its 52-week high...",
                    why_it_matters: "The pullback brings valuation closer to...",
                    confidence: "HIGH",
                    next_steps: "• Review analyst consensus\n• Check recent earnings..."}
               create_notification()     → INSERT INTO alert_notifications
               _push_sse("analyst1",...)  → q.put_nowait() to open browser tab
               _send_email(...)          → SMTP thread (if email enabled)
```

### 8.3 User creates a new alert config

```
Browser          web_server.py        alert_store.py       monitor_loop
   │                  │                    │                    │
   │  POST /api/alerts/configs             │                    │
   │  {name, type, tickers, conditions}    │                    │
   │─────────────────▶│                    │                    │
   │                  │  create_alert_config()                  │
   │                  │──────────────────▶ │                    │
   │                  │  INSERT alert_configs                   │
   │                  │◀──────────────────-│                    │
   │  201 {config}    │                    │                    │
   │◀─────────────────│                    │                    │
   │                  │                    │                    │
   │  (≤ 15 minutes later)                │                    │
   │                  │                    │  get_all_enabled_  │
   │                  │                    │  configs() reads   │
   │                  │                    │  new config ──────▶│
   │  SSE alert if    │  _push_sse() ──────────────────────────▶│
   │  triggered ◀─────│                    │                    │
```

### 8.4 SSE reconnect after network drop

```
Browser                    web_server.py                monitor_loop
   │                            │                            │
   │  GET /api/alerts/stream    │                            │
   │  ?token=<jwt>              │                            │
   │───────────────────────────▶│                            │
   │                            │  subscribe_sse(user_id)    │
   │                            │  → Queue q added to set    │
   │  {"type":"connected"}      │                            │
   │◀───────────────────────────│                            │
   │                            │                            │
   │   ... heartbeats (30s) ... │                            │
   │                            │                            │
   │  [network drop]            │                            │
   │  onerror fired             │                            │
   │  setTimeout(reconnect, 30s)│                            │
   │                            │  connection generator ends │
   │                            │  unsubscribe_sse(user_id, q)
   │                            │  q removed from set        │
   │                            │                            │
   │  [30s later]               │                            │
   │  GET /api/alerts/stream    │                            │
   │───────────────────────────▶│                            │
   │                            │  subscribe_sse()           │
   │                            │  → new Queue q2 added      │
   │  {"type":"connected"}      │                            │
   │◀───────────────────────────│                            │
   │                            │                            │
   │                            │  if monitor fired while    │
   │                            │  disconnected: notification│
   │                            │  is in alerts.db with      │
   │                            │  is_read=0 — user sees it  │
   │                            │  on next GET /api/alerts/  │
   │                            │  notifications             │
```

---

## 9. Design Decisions

### Chat alert agent vs background monitor — why two separate components?

The chat `alert_agent` is a pure ADK `LlmAgent`: stateless, one-shot, driven by user intent. It fits naturally into the intent→agent pipeline. It cannot schedule itself, cannot push notifications, and has no awareness of sessions it isn't currently in.

Building background monitoring inside an ADK agent would require retrofitting scheduling, SSE push, and cross-session state into the callback model — fighting the framework. A plain asyncio coroutine is the natural fit for a poll loop, and shares the FastAPI process without any IPC overhead.

The two components are kept separate by design so each is easy to test, maintain, and reason about independently.

### Why the 3-ticker default watchlist?

The `alert_agent` calls `get-ticker-info` for every ticker in the list. Each call returns ~2 KB of JSON. At 10 tickers that is ~20 KB of tool responses in the LLM context, which with Gemini's char/4 heuristic is ~5 000 tokens — before the system prompt or user message is counted. Three tickers keeps the context comfortably small while still covering the three most commonly requested names in the eval suite (MSFT, NVDA, CRM).

### Why `evaluate_drop_alerts` is a separate pure-Python tool?

The alternative is to ask the LLM to compute percentage changes in its response. This introduces rounding errors and occasional arithmetic hallucinations. Moving the computation into a typed Python function makes the result deterministic and testable. The LLM's role is formatting and contextualising — not arithmetic.

### Why inject default companies in the orchestrator, not in the agent prompt?

The orchestrator emits a `__routing__` event with `{"pipeline": "ALERT", "companies": []}` that is appended to ADK session history. The `alert_agent` LLM sees this as a prior model message containing `companies: []` — and produces no tool calls because there are no tickers. Fixing this at the routing event level (inject defaults when `companies=[]`) is cleaner than adding fallback logic to the agent's prompt, which would be more fragile.

### Why `monitor_analyst_agent`, not `alert_agent`, for monitor content generation?

The monitor needs **JSON output** so it can persist structured fields (`what_happened`, `why_it_matters`, `confidence`, `next_steps`) to SQLite and render them in the UI. `alert_agent` has a system prompt that instructs it to produce human-readable formatted text for the chat window. When the monitor sent it a JSON request, the system prompt won — the agent returned prose, JSON parsing failed, and the fallback fired on every trigger.

Creating a dedicated `monitor_analyst_agent` with a JSON-only system prompt (`prompts/monitor_analyst_v1.md`) solved this cleanly. The two agents have non-overlapping roles:
- `alert_agent`: chat-facing, one-shot, returns formatted drop summary
- `monitor_analyst_agent`: monitor-facing, JSON-only, enriches a pre-detected condition

This is preferable to modifying `alert_agent` because the chat use-case genuinely needs prose output — a shared agent cannot satisfy both contracts simultaneously.

### Why not use the Finance MCP server for all alert_agent calls?

`resolve_ticker` is a direct Python call (no MCP) because it only needs a local lookup dict — no network round-trip. `evaluate_drop_alerts` is also direct Python because it is pure computation. Only `get-ticker-info` goes through MCP because that is where the Yahoo Finance network call lives. This keeps MCP calls minimal and avoids unnecessary subprocess overhead.

### No-auto-trade guarantee

Three independent enforcement layers:
1. **Prompt**: `next_steps` explicitly excludes buy/sell directives ("do not recommend a specific trade action")
2. **Code**: `alert_monitor.py` imports nothing from `trade_tools.py`; `alert_agent.py` has no trade tools in its tool list
3. **UI**: Detail modal and email both display the disclaimer: *"No trades have been or will be executed automatically without your explicit approval."*

---

## 10. Configuration Reference

### Monitor constants (`alert_monitor.py`)

| Constant | Default | Description |
|----------|---------|-------------|
| `POLL_INTERVAL_SECONDS` | `900` | Seconds between poll cycles (15 minutes) |
| `COOLDOWN_HOURS` | `4` | Minimum hours between re-fires for the same (config_id, ticker) pair |

### Environment variables (email delivery)

| Variable | Required | Description |
|----------|----------|-------------|
| `ALERT_SMTP_HOST` | No | SMTP server hostname (e.g. `smtp.gmail.com`) |
| `ALERT_SMTP_PORT` | No | SMTP port (default: `587`, STARTTLS) |
| `ALERT_SMTP_USER` | No | SMTP authentication username |
| `ALERT_SMTP_PASS` | No | SMTP password or app-specific password |
| `ALERT_SMTP_FROM` | No | Sender address (defaults to `ALERT_SMTP_USER`) |

Email delivery is silently skipped if SMTP variables are absent. All in-app SSE notification functionality works without email configured.

### Alert condition parameters

#### `buy_opportunity`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `price_drop_pct` | float | `8` | Required % drop from 52-week high |
| `check_revenue_growth` | bool | `true` | Revenue growth (TTM) must be > 0 |
| `check_debt_stability` | bool | `false` | Debt-to-equity must be < 200 |
| `max_portfolio_pct` | float | `10` | Existing position must be below this % of total portfolio value |

#### `sell_signal`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `stop_loss_pct` | float | `15` | Triggers when price < avg_cost × (1 − stop_loss_pct/100) |
| `max_portfolio_pct` | float | `15` | Triggers when position value > this % of total portfolio |

#### `price_move`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `price_change_pct` | float | `5` | Intraday % change threshold (absolute) |
| `direction` | string | `either` | `up` (upward only), `down` (downward only), `either` (both) |

### Files

| File | Description |
|------|-------------|
| `stock_agent/alert_agent.py` | ADK LlmAgent definition — ALERT intent pipeline |
| `stock_agent/alert_monitor.py` | Asyncio background monitor — poll loop, condition evaluation, content generation, SSE push, email |
| `stock_agent/alert_store.py` | SQLite persistence layer — CRUD for configs, notifications, settings |
| `stock_agent/alerts.db` | SQLite database (WAL mode) — created on first server start |
| `skills/alert_agent/SKILL.md` | System prompt for the chat alert agent |
| `stock_agent/monitor_analyst_agent.py` | ADK LlmAgent definition — background monitor analyst (JSON-only output) |
| `prompts/monitor_analyst_v1.md` | System prompt for `monitor_analyst_agent` — JSON schema, confidence guide, no-trade-directive rules |
| `arch/agents/market-alert-monitor.md` | System architecture document — component diagram, sequence diagrams, data model |
