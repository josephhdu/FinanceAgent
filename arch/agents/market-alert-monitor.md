# Market Alert Monitor — Design Document

## Table of Contents

1. [Purpose and Scope](#1-purpose-and-scope)
2. [System Architecture](#2-system-architecture)
3. [Component Descriptions](#3-component-descriptions)
   - 3.1 [Alert Store (`alert_store.py`)](#31-alert-store-alert_storepy)
   - 3.2 [Alert Monitor (`alert_monitor.py`)](#32-alert-monitor-alert_monitorpy)
   - 3.3 [API Layer (`web_server.py`)](#33-api-layer-web_serverpy)
   - 3.4 [Alerts Tab UI](#34-alerts-tab-ui)
   - 3.5 [Alert Side Panel and Notifications](#35-alert-side-panel-and-notifications)
4. [Alert Types and Condition Logic](#4-alert-types-and-condition-logic)
5. [Alert Content Generation](#5-alert-content-generation)
6. [Notification Delivery](#6-notification-delivery)
7. [Data Model](#7-data-model)
8. [Sequence Diagrams](#8-sequence-diagrams)
9. [Design Decisions](#9-design-decisions)
10. [Configuration Reference](#10-configuration-reference)

---

## 1. Purpose and Scope

The **Market Alert Monitor** is a long-running background service that continuously evaluates user-configured market conditions against live data. When a condition is met it delegates analysis to `monitor_analyst_agent` (a dedicated ADK `LlmAgent`), which enriches the pre-detected condition with investment context and returns a structured JSON result, which is then delivered to the user via in-app notification and optionally email — without executing any trade.

**Two-layer separation:**
- **Monitor (watchman)**: cheap pure-Python + yfinance condition checks run on every poll cycle. No LLM.
- **`monitor_analyst_agent` (analyst)**: invoked in an ephemeral ADK session only when a condition fires. Uses `get-ticker-info` for supplementary data; returns structured JSON only.

### Three alert-related components

There are three alert-related components in the system. They serve distinct purposes:

| Component | Trigger | Lifecycle | Output |
|---|---|---|---|
| `alert_agent` (chat) | User asks "alert me if X dropped" | One shot, per message | Human-readable chat response |
| `monitor_analyst_agent` (background analyst) | Called by monitor when condition fires | Ephemeral ADK session | JSON: `what_happened`, `why_it_matters`, `confidence`, `next_steps` |
| `alert_monitor.py` (background watchman) | 15-min asyncio poll | Always running | Orchestrates condition checks, analyst invocation, SSE push, email |

`alert_agent` and `monitor_analyst_agent` are intentionally separate agents with different system prompts. Sharing one agent would require the same system prompt to produce both human prose (for chat) and strict JSON (for the monitor) — which is not reliably achievable.

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  FastAPI Web Server (web_server.py)                                  │
│                                                                      │
│  ┌─────────────────────────┐   ┌──────────────────────────────────┐ │
│  │  Alert REST API          │   │  SSE Notification Stream         │ │
│  │  /api/alerts/*           │   │  GET /api/alerts/stream          │ │
│  │  CRUD for configs        │   │  Long-lived EventSource          │ │
│  │  Read notifications      │   │  Pushes alert_notification events│ │
│  │  User settings           │   └─────────────┬────────────────────┘ │
│  └──────────┬──────────────┘                 │                      │
│             │                                │                      │
│  ┌──────────▼──────────────────────────────▼──────────────────────┐ │
│  │  asyncio background task: monitor_loop()                        │ │
│  │                                                                 │ │
│  │  every 15 min ──► get_all_enabled_configs()                    │ │
│  │                   for each config:                             │ │
│  │                     for each ticker:                           │ │
│  │                       _fetch_price_data()   [yfinance]         │ │
│  │                       _evaluate()           [pure Python]      │ │
│  │                       if triggered:                            │ │
│  │                         _run_alert_agent() [monitor_analyst_agent] │ │
│  │                         create_notification()     [SQLite]     │ │
│  │                         _push_sse()               [asyncio.Queue]│ │
│  │                         _send_email()             [SMTP]       │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
              ┌────────────────┴───────────────────┐
              │  alert_store.py  (alerts.db)        │
              │                                     │
              │  alert_configs         ← user rules │
              │  alert_notifications   ← history    │
              │  user_alert_settings   ← email prefs│
              └─────────────────────────────────────┘
```

---

## 3. Component Descriptions

### 3.1 Alert Store (`alert_store.py`)

Pure persistence layer. No business logic. SQLite database at `stock_agent/alerts.db`.

**Why SQLite**: Consistent with the rest of the system (`sessions.db`, `session_archive.db`, `pii_tokens.db`). Zero operational overhead, survives server restart, readable with standard tools.

```python
# Key functions
create_alert_config(user_id, name, alert_type, tickers, conditions) → dict
get_all_enabled_configs()       → list[dict]   # used by monitor loop
create_notification(...)        → dict
get_notifications(user_id, ...)→ list[dict]
get_unread_count(user_id)       → int
mark_notification_read(id, user_id)
get_user_settings(user_id)      → dict
update_user_settings(user_id, **kwargs)
```

### 3.2 Alert Monitor (`alert_monitor.py`)

The background service. Started as an asyncio task in `_on_startup()`. Runs indefinitely in the same process as the web server.

**Key responsibilities**:
- Poll on a configurable interval (default 15 min)
- Fetch live market data per ticker (yfinance)
- Evaluate conditions (pure Python, no LLM)
- Delegate to `alert_agent` when a condition fires (ephemeral ADK session)
- Persist notifications to SQLite
- Push to SSE queues
- Send email (optional)
- Track monitor status for the UI dashboard

**Monitor analyst runner**: A dedicated `Runner` and `InMemorySessionService` are created at module level for the monitor's exclusive use. Sessions are ephemeral — created, used, and deleted within a single `_run_alert_agent()` call. No state leaks into `sessions.db` or the user's chat history.

```python
_MONITOR_APP           = "alert_monitor"
_alert_session_service = InMemorySessionService()
_alert_runner          = Runner(
    agent           = monitor_analyst_agent,   # dedicated JSON-only analyst
    app_name        = _MONITOR_APP,
    session_service = _alert_session_service,
)
```

**SSE subscriber registry**: A module-level dict maps `user_id → set[asyncio.Queue]`. Each open browser connection holds one queue. The monitor calls `q.put_nowait(payload)` to deliver in real time.

**Cooldown**: The same `(config_id, ticker)` pair won't re-fire within `COOLDOWN_HOURS` (default 4 h) to prevent spam across poll cycles. Tracked in-memory — resets on server restart.

### 3.3 API Layer (`web_server.py`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/alerts/configs` | List user's alert configurations |
| `POST` | `/api/alerts/configs` | Create new alert config |
| `PATCH` | `/api/alerts/configs/{id}` | Update (enable/disable, rename, edit conditions) |
| `DELETE` | `/api/alerts/configs/{id}` | Delete config |
| `GET` | `/api/alerts/notifications` | List triggered alerts (paginated) |
| `GET` | `/api/alerts/notifications/count` | Unread count |
| `POST` | `/api/alerts/notifications/{id}/read` | Mark one as read |
| `POST` | `/api/alerts/notifications/read-all` | Mark all as read |
| `GET` | `/api/alerts/stream` | SSE stream (long-lived, token via `?token=`) |
| `GET` | `/api/alerts/settings` | Get user's email settings |
| `PUT` | `/api/alerts/settings` | Update email / enable email alerts |
| `GET` | `/api/alerts/monitor-status` | Runtime dashboard data |

**Authentication note**: All endpoints use the standard `_require_auth` dependency. The SSE endpoint (`/api/alerts/stream`) accepts the JWT as a `?token=` query parameter because the browser's native `EventSource` API cannot set `Authorization` headers. The server validates this token identically to a Bearer header.

### 3.4 Alerts Tab UI

A dedicated main tab (5th tab, visible to all roles) providing a real-time dashboard:

**Stats bar** (5 cards):

| Card | Source |
|------|--------|
| Monitor status (● Running / ○ Stopped) | `monitor_status.running` |
| Running agents | `summary.configs_enabled` |
| Total configured | `summary.configs_total` |
| Unread alerts | `summary.notifications_unread` |
| Next check | countdown from `monitor_status.next_check_at` |

**Agent cards grid**: One card per configured alert, showing name, type, tickers, condition bullets, cooldown status, last triggered timestamp, pause/resume and delete controls.

**Alert history table**: The 10 most recent notifications with ticker, agent name, alert type, summary preview, confidence, and relative timestamp. Clicking opens the detail modal.

### 3.5 Alert Side Panel and Notifications

A slide-in panel (accessible from the bell icon in the header, from any tab):

- **Bell icon** with animated red badge (unread count)
- **Notifications list** (newest first, unread cards have a blue left border)
- **Active monitors** section (all configs with on/off toggles)
- **Detail modal**: what happened, why it matters, confidence level (colour coded), next steps, and a no-auto-trade disclaimer
- **Toast notifications**: 8-second overlay when a new alert arrives via SSE

---

## 4. Alert Types and Condition Logic

### 4.1 Buy Opportunity (ALL conditions must be met)

Designed for accumulation signals during pullbacks in fundamentally sound companies.

| Condition | Parameter | Default | Source |
|-----------|-----------|---------|--------|
| Price drop from 52-week high | `price_drop_pct` | 8% | yfinance `fiftyTwoWeekHigh` |
| Revenue growth positive | `check_revenue_growth` | true | yfinance `revenueGrowth` (TTM) |
| Debt stability | `check_debt_stability` | false | yfinance `debtToEquity` < 200 |
| Portfolio allocation headroom | `max_portfolio_pct` | 10% | `get_portfolio()` aggregated from trades.jsonl |

```python
triggered = price_ok AND rev_ok AND debt_ok AND alloc_ok
```

Example configuration corresponding to the user's stated criteria:
```json
{
  "alert_type": "buy_opportunity",
  "conditions": {
    "price_drop_pct": 8,
    "check_revenue_growth": true,
    "check_debt_stability": true,
    "max_portfolio_pct": 10
  }
}
```

### 4.2 Sell / Risk Alert (ANY condition triggers)

Designed for capital protection: stop-loss enforcement and position sizing discipline.

| Condition | Parameter | Default | Source |
|-----------|-----------|---------|--------|
| Stop-loss below cost basis | `stop_loss_pct` | 15% | avg cost from trades.jsonl |
| Allocation breach after run-up | `max_portfolio_pct` | 15% | portfolio % calculation |

```python
triggered = stop_loss_breach OR allocation_breach
```

Example configuration corresponding to the user's stated criteria:
```json
{
  "alert_type": "sell_signal",
  "conditions": {
    "stop_loss_pct": 15,
    "max_portfolio_pct": 15
  }
}
```

### 4.3 Price Move

Simple momentum signal — any significant intraday move.

| Condition | Parameter | Default |
|-----------|-----------|---------|
| % change vs previous close | `price_change_pct` | 5% |
| Direction | `direction` | `either` |

```python
triggered = abs(change_pct) >= threshold   # direction="either"
triggered = change_pct >= threshold         # direction="up"
triggered = change_pct <= -threshold        # direction="down"
```

### 4.4 Portfolio Data Access

The monitor needs per-user portfolio data for allocation checks. It sets the `audit_user_id` context variable before calling `get_portfolio()`, which reads from `trades.jsonl` filtered to that user:

```python
tok = audit_user_id.set(user_id)
portfolio = await loop.run_in_executor(None, get_portfolio)
audit_user_id.reset(tok)
```

This reuses the same portfolio function that the trading agent uses — no duplication, consistent source of truth.

---

## 5. Alert Content Generation

When a condition fires, the monitor delegates to `monitor_analyst_agent` — a dedicated ADK `LlmAgent` with a JSON-only system prompt — via an ephemeral ADK session. This separates the cheap condition-check step (pure Python + yfinance) from the LLM content-generation step, ensuring LLM cost is only incurred when something actually happened.

### Why `monitor_analyst_agent`, not `alert_agent`?

`alert_agent` has a system prompt that produces human-readable formatted text for the chat window. When the monitor sent it a JSON output request, the system prompt won — the agent returned prose, JSON parsing failed, and the fallback fired on every trigger.

`monitor_analyst_agent` (`stock_agent/monitor_analyst_agent.py`) has a **JSON-only system prompt** (`prompts/monitor_analyst_v1.md`) that matches the required output schema exactly. It is the only agent invoked by the monitor. The two agents are intentionally separate:

| Agent | Used by | System prompt | Output |
|---|---|---|---|
| `alert_agent` | Chat pipeline (ALERT intent) | `skills/alert_agent/SKILL.md` — prose drop summary | Human-readable text |
| `monitor_analyst_agent` | Background monitor only | `prompts/monitor_analyst_v1.md` — JSON schema | `{what_happened, why_it_matters, confidence, next_steps}` |

### Why use an ADK agent rather than a raw Gemini call?

Using `monitor_analyst_agent` via the ADK runner brings three benefits:
1. **Guardrails**: PII tokenisation, token limit check, and audit logging fire automatically at every LLM boundary
2. **Tool access**: the agent can call `get-ticker-info` to fetch supplementary data (P/E, analyst target, sector) beyond the monitor's pre-fetched snapshot
3. **Prompt versioning**: the system prompt lives in `prompts/monitor_analyst_v1.md` under the same `load_prompt(name, version)` registry as all other prompts

### Agent invocation flow

```python
session_id = f"monitor-{config_id[:8]}-{ticker}-{uuid4().hex[:8]}"
await _alert_session_service.create_session(
    app_name=_MONITOR_APP, user_id=user_id, session_id=session_id
)

prompt = _build_monitor_prompt(config, ticker, price_data, matched)
# Prompt states conditions are already confirmed — agent does NOT re-verify

async for event in _alert_runner.run_async(user_id, session_id, new_message=prompt):
    if event.is_final_response():
        response_text += part.text

result = _parse_agent_response(
    response_text, config["alert_type"], ticker,
    price_data=price_data, matched=matched,
)
# session auto-cleaned by InMemorySessionService
```

### Prompt design

```
Alert name:   {config_name}
Alert type:   {alert_type}
Ticker:       {ticker} ({company})

Price snapshot (pre-fetched):
  Current price, 52-week high, drop%, prev close, revenue growth, D/E, trailing P/E

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

| Level | Meaning |
|-------|---------|
| `HIGH` | All conditions met with clear data; multiple confirming factors |
| `MEDIUM` | Conditions met but some data is uncertain or marginal |
| `LOW` | Early or weak signal; worth watching but not acting on |

### `next_steps` normalisation

`monitor_analyst_agent` occasionally returns `next_steps` as a JSON array instead of a string. `_parse_agent_response` normalises this:

```python
if isinstance(result["next_steps"], list):
    result["next_steps"] = "\n".join(result["next_steps"])
```

### Fallback (agent call fails or returns unparseable output)

`_fallback_content(alert_type, ticker, price_data=None, matched=None)` produces a factual notification from the pre-fetched snapshot:

- Builds `what_happened` from `current_price`, `drop_from_52w_high_pct`, and matched condition labels — never a generic placeholder
- `_parse_agent_response` logs the raw response (up to 300 chars) at WARNING level before falling back
- Both call sites pass `price_data=price_data, matched=matched` so even the worst-case path is informative

The notification is always created and delivered — agent failure never silently swallows an alert.

---

## 6. Notification Delivery

### 6.1 In-app (SSE)

```
monitor_loop detects condition
    │
    ▼
create_notification()   →   alerts.db
    │
    ▼
_push_sse(user_id, payload)
    │
    ├─ for each Queue in _sse_queues[user_id]:
    │      q.put_nowait({"type": "alert_notification", "notification": {...}})
    │
    ▼
Browser EventSource receives event
    ├─ updateBadge()           → red badge on bell icon + tab dot
    ├─ renderAlertNotifications()   → side panel list
    ├─ showAlertToast(notif)   → 8-second overlay toast (View → / Continue in Chat →)
    └─ loadAlertsTab()         → refresh dashboard if tab is open
```

SSE connections are maintained with a 30-second heartbeat (`{"type":"heartbeat"}`) so the browser knows the connection is alive. On disconnect, the browser auto-reconnects after 30 seconds via the `onerror` handler.

### 6.2 Email

Email delivery uses globally configured SMTP environment variables:

| Env var | Description |
|---------|-------------|
| `ALERT_SMTP_HOST` | SMTP server hostname (e.g. `smtp.gmail.com`) |
| `ALERT_SMTP_PORT` | Port (default 587 / STARTTLS) |
| `ALERT_SMTP_USER` | SMTP login username |
| `ALERT_SMTP_PASS` | SMTP password / app password |
| `ALERT_SMTP_FROM` | From address (defaults to `ALERT_SMTP_USER`) |

The user configures only their **notification email address** in the UI. SMTP credentials live in server environment variables and are never exposed to the browser.

Email is sent in an executor thread (non-blocking). Failure is logged but does not affect the in-app notification path. On success, `alert_notifications.email_sent` is set to `1`.

**No automatic trades**: The email template explicitly states: *"This is an informational alert only. No trades have been or will be executed automatically without your explicit approval."*

---

## 7. Data Model

### `alert_configs`

```sql
CREATE TABLE alert_configs (
    id          TEXT PRIMARY KEY,       -- uuid4
    user_id     TEXT NOT NULL,          -- username (JWT sub)
    name        TEXT NOT NULL,          -- user-defined label
    enabled     INTEGER NOT NULL DEFAULT 1,  -- 0 = paused
    tickers     TEXT NOT NULL,          -- JSON array of uppercase ticker strings
    alert_type  TEXT NOT NULL,          -- buy_opportunity | sell_signal | price_move
    conditions  TEXT NOT NULL,          -- JSON dict of typed parameters
    created_at  TEXT NOT NULL,          -- ISO-8601 UTC
    updated_at  TEXT NOT NULL
);
```

### `alert_notifications`

```sql
CREATE TABLE alert_notifications (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    config_id       TEXT,               -- FK to alert_configs.id (nullable: manual)
    config_name     TEXT,               -- snapshot of name at trigger time
    triggered_at    TEXT NOT NULL,      -- ISO-8601 UTC
    ticker          TEXT NOT NULL,
    alert_type      TEXT NOT NULL,
    what_happened   TEXT NOT NULL,      -- Gemini-generated
    why_it_matters  TEXT NOT NULL,      -- Gemini-generated
    confidence      TEXT NOT NULL,      -- HIGH | MEDIUM | LOW
    next_steps      TEXT NOT NULL,      -- Gemini-generated bullet points
    raw_data        TEXT,               -- JSON: price snapshot + matched_conditions
    is_read         INTEGER NOT NULL DEFAULT 0,
    email_sent      INTEGER NOT NULL DEFAULT 0
);
```

### `user_alert_settings`

```sql
CREATE TABLE user_alert_settings (
    user_id                 TEXT PRIMARY KEY,
    notification_email      TEXT,               -- where to send emails
    email_alerts_enabled    INTEGER NOT NULL DEFAULT 0,
    updated_at              TEXT NOT NULL
);
```

---

## 8. Sequence Diagrams

### 8.1 Monitor Loop — Condition Triggered

```
                        monitor_loop (every 15 min)
                               │
                    get_all_enabled_configs()
                               │
                    for each config:
                       for each ticker:
                               │
                    ┌──────────▼──────────────────────────────┐
                    │ _fetch_price_data(ticker)  [yfinance]   │
                    │  → current_price, high_52w, rev_growth  │
                    │    debt_to_equity, prev_close           │
                    └──────────┬──────────────────────────────┘
                               │
                    ┌──────────▼──────────────────────────────┐
                    │ _is_on_cooldown(config_id, ticker)?     │
                    │  YES → skip (4h cooldown active)        │
                    │  NO  → continue                         │
                    └──────────┬──────────────────────────────┘
                               │
                    ┌──────────▼──────────────────────────────┐
                    │ get_portfolio() [trades.jsonl]           │
                    │  → positions, total_invested            │
                    └──────────┬──────────────────────────────┘
                               │
                    ┌──────────▼──────────────────────────────┐
                    │ _evaluate(config, price_data, portfolio) │
                    │  → triggered=True/False, matched={}     │
                    └──────────┬──────────────────────────────┘
                               │ triggered=True
                    ┌──────────▼──────────────────────────────┐
                    │ _mark_fired(config_id, ticker)          │
                    │  start 4h cooldown                      │
                    └──────────┬──────────────────────────────┘
                               │
                    ┌──────────▼──────────────────────────────┐
                    │ _run_alert_agent()                              │
                    │  create ephemeral InMemory session              │
                    │  _alert_runner.run_async(prompt)                │
                    │   → monitor_analyst_agent calls get-ticker-info │
                    │   → LLM returns JSON (no prose, no re-verify)   │
                    │   → _parse_agent_response() normalises result   │
                    │  session auto-cleaned by InMemorySessionService │
                    │  → what_happened, why_it_matters,       │
                    │     confidence, next_steps              │
                    └──────────┬──────────────────────────────┘
                               │
                    ┌──────────▼──────────────────────────────┐
                    │ alert_store.create_notification()       │
                    │  → INSERT INTO alert_notifications      │
                    └──────────┬──────────────────────────────┘
                               │
                    ┌──────────▼──────────────────────────────┐
                    │ _push_sse(user_id, payload)             │
                    │  → q.put_nowait() for each open tab    │
                    └──────────┬──────────────────────────────┘
                               │
                    ┌──────────▼──────────────────────────────┐
                    │ email_alerts_enabled?                   │
                    │  YES → _send_email()  [SMTP thread]     │
                    │  NO  → done                             │
                    └─────────────────────────────────────────┘
```

### 8.2 User Creates an Alert Config

```
Browser                           FastAPI                    alerts.db
   │                                 │                          │
   │  POST /api/alerts/configs       │                          │
   │  { name, alert_type,            │                          │
   │    tickers, conditions }        │                          │
   │────────────────────────────────►│                          │
   │                                 │  create_alert_config()   │
   │                                 │─────────────────────────►│
   │                                 │  INSERT alert_configs    │
   │                                 │◄─────────────────────────│
   │  201 { id, name, enabled... }   │                          │
   │◄────────────────────────────────│                          │
   │                                 │                          │
   │  (next monitor poll, ≤ 15 min)  │                          │
   │  SSE alert_notification event   │  monitor_loop picks      │
   │◄────────────────────────────────│  up new config and       │
   │  updateBadge()                  │  evaluates it            │
   │  showAlertToast()               │                          │
```

### 8.3 SSE Reconnect Flow

```
Browser               FastAPI (SSE endpoint)         monitor_loop
   │                          │                            │
   │  GET /api/alerts/stream  │                            │
   │  ?token=<jwt>            │                            │
   │─────────────────────────►│                            │
   │                          │  subscribe_sse(user_id)    │
   │                          │  → new asyncio.Queue q     │
   │  data: {"type":"connected"}                           │
   │◄─────────────────────────│                            │
   │                          │                            │
   │  ... (30s heartbeats) ...│                            │
   │                          │                            │
   │  [network drop]          │                            │
   │  onerror callback        │                            │
   │  setTimeout(reconnect,   │                            │
   │             30000)       │                            │
   │                          │  unsubscribe_sse()         │
   │                          │  q removed from set        │
   │                          │                            │
   │  [30s later]             │                            │
   │  GET /api/alerts/stream  │                            │
   │─────────────────────────►│                            │
   │                          │  subscribe_sse()           │
   │                          │  → new Queue q2            │
   │  data: {"type":"connected"}                           │
   │◄─────────────────────────│                            │
```

---

## 9. Design Decisions

### Why asyncio background task, not a separate process?

Running the monitor in the same process as the web server (as an `asyncio.create_task`) avoids IPC complexity, shares the same SQLite file handles cleanly, and allows direct queue injection to SSE connections without a message broker. The downside is that a server crash stops monitoring — acceptable for a v1 system where the user can simply restart. A future upgrade path is `celery` + Redis for true process isolation.

### Why `monitor_analyst_agent`, not `alert_agent`, for monitor content generation?

`alert_agent` has a system prompt that produces human-readable formatted text for the chat window. When the monitor sent it a JSON output request, the system prompt won — the agent returned prose, JSON parsing failed, and the fallback fired on every trigger.

`monitor_analyst_agent` has a JSON-only system prompt (`prompts/monitor_analyst_v1.md`) specifically designed for the monitor's structured output contract. Using a dedicated agent instead of modifying `alert_agent` keeps the two contracts separate — chat needs prose, the monitor needs JSON, and one agent cannot reliably satisfy both simultaneously.

Using an ADK agent (rather than a raw `google.generativeai.GenerativeModel` call) brings three additional benefits: (1) the analysis goes through the full guardrail stack automatically; (2) the agent can call `get-ticker-info` for supplementary data; (3) the system prompt lives in the versioned prompt registry.

### Why yfinance for market data?

Consistent with the rest of the system: `fetch_price_trends`, `fetch_and_forecast`, and MCP `get-ticker-info` all use yfinance. Using the same library avoids adding a dependency and keeps data source behaviour predictable. The `fiftyTwoWeekHigh`, `revenueGrowth`, and `debtToEquity` fields cover the key buy-opportunity conditions without additional API calls.

### Why not use the existing `alert_agent`?

The existing `alert_agent` is a conversational agent — it responds to a user query, runs a single check, and returns. It has no persistence, no scheduling, and no push capability. Building on top of it would require retrofitting scheduling and SSE delivery into the ADK callback model, which is significantly more complex than a dedicated async service. The two agents are complementary: the chat alert agent handles ad-hoc queries; the market alert monitor handles persistent background watching.

### Why per-user SSE queues instead of WebSockets?

SSE is already used for the chat stream (`POST /api/chat/{id}`). Keeping the same transport for notifications avoids adding a WebSocket server, while SSE's unidirectional model is a perfect fit for push-only alert delivery. The browser's native `EventSource` auto-reconnects without any client-side code.

### No-auto-trade guarantee

The system never calls `execute_pending_trade()` or any write-to-portfolio function. The `next_steps` field in every alert explicitly forbids automatic trade recommendations. The UI disclaimer reads: *"No trades have been or will be executed automatically without your explicit approval."* This is enforced at the generation prompt level and at the UI level.

---

## 10. Configuration Reference

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ALERT_SMTP_HOST` | No | SMTP hostname for email delivery |
| `ALERT_SMTP_PORT` | No | SMTP port (default: `587`) |
| `ALERT_SMTP_USER` | No | SMTP authentication username |
| `ALERT_SMTP_PASS` | No | SMTP password or app password |
| `ALERT_SMTP_FROM` | No | From address (defaults to `ALERT_SMTP_USER`) |

Email is silently skipped if SMTP vars are absent. All other functionality works without email configured.

### Monitor Constants (`alert_monitor.py`)

| Constant | Default | Description |
|----------|---------|-------------|
| `POLL_INTERVAL_SECONDS` | `900` | How often the monitor polls (15 minutes) |
| `COOLDOWN_HOURS` | `4` | Minimum time between re-fires for the same (config, ticker) |

### Alert Type Condition Parameters

#### `buy_opportunity`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `price_drop_pct` | float | `8` | % drop from 52-week high required to trigger |
| `check_revenue_growth` | bool | `true` | Revenue growth (TTM) must be positive |
| `check_debt_stability` | bool | `false` | Debt-to-equity must be < 200% |
| `max_portfolio_pct` | float | `10` | Current position must be below this % of portfolio |

#### `sell_signal`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `stop_loss_pct` | float | `15` | Triggers when price < avg_cost × (1 − stop_loss_pct/100) |
| `max_portfolio_pct` | float | `15` | Triggers when position > this % of portfolio |

#### `price_move`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `price_change_pct` | float | `5` | Intraday % change threshold |
| `direction` | string | `either` | `up`, `down`, or `either` |
