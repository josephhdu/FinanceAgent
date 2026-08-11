# Web UI

## Overview

The web UI exposes the stock analysis agent as a browser-accessible chat application. It provides:

- A **dark-themed single-page chat interface** (`static/index.html`) with a session history sidebar
- A **FastAPI backend** (`web_server.py`) that wraps the ADK `Runner` and streams responses to the browser over Server-Sent Events (SSE)
- **Inline chart rendering** — base64 PNG charts produced by visualization tools are intercepted before the LLM strips them and delivered to the browser as SSE image events
- **Trade signal badge** — when `get_trade_signals` fires, the composite signal score and confidence percentage are captured and delivered as a `signal` SSE event, rendered as a structured badge (BUY/SELL/HOLD pill + confidence bar) above the LLM text
- **Prompt library** — a `☰` button opens a searchable modal of curated example prompts grouped into 12 categories; selecting a prompt fills the input and closes the modal
- **Response feedback** — a `👍 👎` row fades in below each assistant bubble after streaming; ratings are sent to `POST /api/feedback` and appended to `feedback.jsonl`

The web UI replaces ADK's generic development server (`adk web`) with a domain-specific interface that supports multi-session history, streaming text, chart display, trading signal visualisation, a browsable prompt library, JWT-based role-gated access control, a client-side trading ledger, and a live portfolio analytics dashboard.

---

## Architecture

```
Browser (static/index.html)
    │
    │  GET /                  → index.html (FileResponse)  [public]
    │  GET /health            → liveness probe             [public]
    │  GET /ready             → readiness probe            [public]
    │  POST /api/login        → issue JWT token            [public]
    │
    │  ── All routes below require Authorization: Bearer <jwt> ──
    │
    │  GET /api/sessions          → session list JSON
    │  POST /api/sessions         → create session
    │  DELETE /api/sessions/{id}  → delete session (ownership-checked)
    │  GET /api/sessions/{id}     → full session (messages + images)
    │  POST /api/chat/{id}        → SSE stream (text/event-stream)
    │  POST /api/feedback         → append rating to feedback.jsonl
    │  GET /api/prices            → current price snapshot (yfinance)
    │  GET /api/price-history     → daily closing prices for trend charts
    │  GET /api/downloads/{file}  → streams a generated PDF as a download
    │
    ▼
web_server.py  (FastAPI + uvicorn, port 8080)
    │
    ├─ _require_auth (FastAPI Depends)
    │    validates JWT → {username, role}; raises 401 on missing/expired
    │
    ├─ _sessions dict (in-memory session store)
    │    {id → {id, title, created_at, messages: [{role, content, images}]}}
    │
    ├─ _patch_for_image_capture()  (startup — patches all agents)
    │    wraps after_tool_callback on every agent in the tree
    │    chart markdown captured into _current_images ContextVar
    │    trade signal data captured into _current_signals ContextVar
    │    citations captured into _current_citations ContextVar
    │    all captured before audit.py can strip or transform them
    │
    └─ ADK Runner + SqliteSessionService  ("sessions.db")
         + ChromaMemoryService  ("memory_db/")
         (one shared runner — session context persisted per session_id)
         role injected via _current_role ContextVar per request
         │
         └─▶ stock_agent.root_agent (GraphOrchestrator)
                  ① search_memory(user_query) → _memory_context in session.state
                  ② reads role from _current_role → session.state["user_role"]
                  ③ RBAC check before every pipeline run
                  all existing pipelines, guardrails, MCP tools unchanged
         │
         └─▶ after stream: add_session_to_memory(adk_session)  → memory_db/
```

Two independent storage layers handle state for each session:

| Layer | Implementation | What it stores | Persisted? |
|---|---|---|---|
| `_sessions` dict | `sessions_meta.db` (SQLite, write-through) | Title, created_at, rendered messages (role + text + images) | ✅ survives restart |
| `SqliteSessionService` | `sessions.db` (ADK-managed SQLite) | Full ADK event history — tool calls, function responses, agent turns | ✅ survives restart |

Both are keyed by the same `session_id` (UUID hex string). When the browser loads a past session it reads from `_sessions` (populated from `sessions_meta.db` at startup); when the ADK runner continues a session it reads from `sessions.db`.

---

## API Routes

### `POST /api/login`

Issues a JWT token on successful credential verification.

**Request body:**
```json
{ "username": "alice", "password": "alice123" }
```

**Response:**
```json
{ "token": "eyJ...", "username": "alice", "role": "analyst" }
```

The token is HS256-signed with `JWT_SECRET` from `.env`, expiry 8 hours (configurable via `JWT_EXPIRY_HOURS`). The browser stores it in `localStorage` and attaches it as `Authorization: Bearer <token>` on every subsequent request.

**Seed accounts** (created at startup if the `users` table is empty):

| Username | Password | Role |
|----------|----------|------|
| admin | admin123 | admin |
| alice | alice123 | analyst |
| bob | bob123 | viewer |

---

### `GET /`

Serves `static/index.html` via `FileResponse`. No authentication.

---

### `GET /api/sessions`

Returns all sessions as a JSON array, newest-first sorting applied on the client.

**Response:**
```json
[
  {
    "id": "a3f9c1d2...",
    "title": "What is Microsoft's stock price?",
    "created_at": "2026-05-02T10:30:00+00:00",
    "messages": [...]
  }
]
```

---

### `POST /api/sessions`

Creates a new session. Registers it in `_sessions`, `sessions_meta.db`, and `SqliteSessionService`.

**Response:** The new session object (same schema as above, `messages: []`).

**Side effects:**
- `uuid.uuid4().hex` → `session_id`
- `_session_service.create_session(app_name, user_id, session_id)` registers ADK multi-turn context in `sessions.db`
- `_sessions[session_id]` populates the runtime cache
- `_meta_upsert_session(session)` persists title + created_at to `sessions_meta.db`

---

### `GET /api/sessions/{session_id}`

Returns the full session object including all messages and per-message image lists.

**Message schema:**
```json
{
  "role": "user" | "assistant",
  "content": "string — plain text (user) or markdown (assistant)",
  "images": ["![Chart Title](data:image/png;base64,...)"]
}
```

Images are stored as a list on the assistant message so the browser can render them in order when loading a historical session.

---

### `GET /health`

Liveness probe. Returns `{"status": "ok"}` with HTTP 200 unconditionally. Confirms the process is running and FastAPI is responding. Zero overhead — no dependency checks.

---

### `GET /ready`

Readiness probe. Runs four dependency checks before the server is considered ready to serve traffic:

| Check | What it tests |
|---|---|
| `gemini_api_key` | `GOOGLE_API_KEY` env var is set |
| `chromadb` | `PersistentClient.heartbeat()` succeeds |
| `lightrag_storage` | `lightrag_storage/` directory exists |
| `audit_log` | Audit log parent directory is writable |

Returns `200 {"status":"ready","checks":{...}}` if all pass. Returns `503 {"status":"degraded","checks":{...}}` if any fail — with per-check detail so operators know exactly what's wrong.

---

### `POST /api/feedback`

Submits a thumbs up or down rating for an assistant message.

**Request body:**
```json
{
  "session_id": "a3f9c1d2...",
  "msg_index":  2,
  "rating":     "up",
  "preview":    "MSFT is currently trading at $414..."
}
```

**Validation:** `rating` must be `"up"` or `"down"` — returns HTTP 400 otherwise.

**Side effects:** appends one JSON line to `feedback.jsonl`; writes an INFO log entry.

**Response:** `{"ok": true}`

---

### `DELETE /api/sessions/{session_id}`

Deletes a session. Verifies ownership before deletion.

**Ownership check:** returns HTTP 403 if the authenticated user does not own the session.

**Side effects (in order):**
1. Removes `session_id` from the in-memory `_sessions` dict.
2. Deletes `messages` and `sessions` rows from `sessions_meta.db` (SQLite).
3. Calls `_session_service.delete_session()` to remove the ADK event history from `sessions.db`.

**Response:** HTTP 204 No Content.

---

### `GET /api/prices`

Returns a current price snapshot for a comma-separated list of tickers.

**Query parameters:** `tickers` (required) — e.g. `?tickers=AAPL,MSFT,NVDA`

**Response:**
```json
{
  "AAPL": { "price": 172.30, "prev_close": 170.10, "change": 2.20, "change_pct": 1.29 },
  "MSFT": { "price": 415.20, "prev_close": 417.80, "change": -2.60, "change_pct": -0.62 }
}
```

If yfinance fails for a ticker, that entry contains `{"price": null, "change": null, "change_pct": null, "error": "..."}`.

**Implementation:** calls `yf.Ticker(sym).fast_info` for each ticker. Max 20 tickers per request.

---

### `GET /api/price-history`

Returns daily closing prices for up to 10 tickers over a configurable lookback period.

**Query parameters:**
- `tickers` (required) — comma-separated
- `period` (optional, default `3mo`) — one of `1mo`, `3mo`, `6mo`, `1y`

**Response:**
```json
{
  "AAPL": [
    { "date": "2026-02-03", "close": 168.40 },
    { "date": "2026-02-04", "close": 170.10 }
  ],
  "MSFT": [...]
}
```

**Implementation:** calls `yf.Ticker(sym).history(period=period)` for each ticker. Invalid `period` values silently default to `3mo`.

---

### `GET /api/downloads/{filename}`

Streams a generated report file (typically a PDF in `output/`) to the browser as an attachment so the file lands in the user's Downloads folder.

**Path-traversal guards (rejected with HTTP 400):**
- Any slash or backslash in the filename — `filename != Path(filename).name`
- Dotfiles — `filename.startswith(".")`
- Resolved path outside `_OUTPUT_DIR` — caught by `candidate.resolve().relative_to(_OUTPUT_DIR)`

**Response:**
- `Content-Type: application/pdf` (for `.pdf` files; default otherwise)
- `Content-Disposition: attachment; filename="<name>"` — forces download, never inline rendering
- HTTP 401 if no JWT, 400 on invalid filename, 404 if missing

**Why a custom endpoint instead of the static mount:** `static/` is public, but `output/` may contain user-specific reports — every request must check the JWT. The endpoint also adds the `Content-Disposition: attachment` header, which the static mount does not.

#### Authenticated download flow (browser side)

Markdown links can't add an `Authorization` header to a plain `<a href>`, so a delegated click handler in `static/index.html` intercepts any click on `/api/downloads/…`:

```js
document.addEventListener('click', async (ev) => {
  const a = ev.target.closest('a[href^="/api/downloads/"]');
  if (!a) return;
  ev.preventDefault();
  const res    = await fetch(a.href, { headers: _authHeaders() });
  const blob   = await res.blob();
  const objUrl = URL.createObjectURL(blob);
  const tmp    = document.createElement('a');
  tmp.href = objUrl; tmp.download = filename;
  tmp.click(); URL.revokeObjectURL(objUrl);
});
```

The link text briefly flips to `⏳ Downloading…` → `✅ Downloaded` for visual feedback, then restores. On failure: `⚠️ Download failed`.

**Why a Blob URL instead of `?token=…`:** putting the JWT in the URL would leak it into server access logs, browser history, the referrer header, and any sharing the user might do. The Blob-URL flow keeps the JWT in memory only.

---

### `POST /api/chat/{session_id}`

Sends a user message and streams the agent's response as SSE.

**Request body:**
```json
{ "message": "What is Apple's stock price?" }
```

**Response:** `Content-Type: text/event-stream`

The server:
1. Appends the user message to `_sessions[id].messages`
2. Sets the session title from the first message (truncated to 55 chars)
3. Returns a `StreamingResponse` wrapping the `_stream()` async generator
4. After the generator completes, appends the assistant message (text + captured images) to `_sessions[id].messages`

---

## Authentication & RBAC

### JWT auth flow

```
Browser                    web_server.py              sessions_meta.db
   │                              │                        │
   │  POST /api/login             │                        │
   │  {username, password} ──────▶│  verify_user()         │
   │                              │  bcrypt.verify() ──────▶│ (users table)
   │◀── {token, role} ────────────│  create_token()        │
   │  (stored in localStorage)    │                        │
   │                              │                        │
   │  POST /api/chat/{id}         │                        │
   │  Authorization: Bearer <tok> │                        │
   │─────────────────────────────▶│  _require_auth()       │
   │                              │  decode_token() → {sub,role}
   │                              │  _current_role.set(role)
   │                              │                        │
   │                              ├──── GraphOrchestrator  │
   │                              │     session.state["user_role"] = role
   │                              │     is_allowed(role, intent)?
   │                              │       NO  → forbidden_event → SSE
   │                              │       YES → run pipeline
   │◀── SSE stream ───────────────│                        │
```

### Role permissions

Defined in `stock_agent/roles.yaml` — edit and restart to change:

| Role | Allowed intents |
|------|----------------|
| `viewer` | PRICE, VISUALIZATION, ANNUAL_REPORT |
| `analyst` | All viewer intents + PREDICTION, FINANCIAL_REPORT, STOCK_COMPARISON, INVESTMENT_RESEARCH, PRICE_PREDICTION, PRICE_PREDICT_CHART, ANNUAL_FINANCIAL |
| `admin` | All intents (`*`) |

### Tab Visibility by Role

The **Trading History** and **Analytics** tabs are hidden for `viewer` role accounts. Only `analyst` and `admin` roles can see and access these tabs. The visibility is enforced client-side in `_showApp()` (called after login) by setting `style.display = 'none'` on `#tab-trades` and `#tab-analytics`. If a viewer navigates directly to those tabs (e.g. via browser history), `switchTab('chat')` is called automatically to redirect them to the Chat view.

This complements the server-side RBAC enforcement in `stock_orchestrator`, which blocks `TRADE_ANALYSIS` intents for the `viewer` role.

### Enforcement layers

| Layer | Where | What it does |
|-------|-------|-------------|
| HTTP | `_require_auth` FastAPI `Depends` | Rejects any request without a valid JWT with HTTP 401 |
| Agent | `GraphOrchestrator._run_async_impl` | After intent is classified, checks `is_allowed(role, intent)`; yields `forbidden_event` and returns if denied |
| Config | `stock_agent/roles.yaml` | Declarative — no code change needed to adjust permissions |

### Storage

Users are stored in `sessions_meta.db` (same file as session metadata, separate `users` table):

```sql
CREATE TABLE users (
    username  TEXT PRIMARY KEY,
    hashed_pw TEXT NOT NULL,   -- bcrypt
    role      TEXT NOT NULL    -- viewer / analyst / admin
);
```

`init_users_table()` creates the table and inserts seed accounts at startup (skips if rows already exist).

---

## SSE Event Protocol

All events are JSON objects encoded as `data: {...}\n\n` lines. The browser's SSE client parses them line by line.

### Event types

| Type | Fields | Description |
|---|---|---|
| `progress` | `text: str` | Orchestrator status update emitted during silent phases (intent classification, pipeline step start). Displayed as italic text alongside the typing dots, then as a status line above the response. Hidden when the first `token` arrives. |
| `signal` | `ticker`, `recommendation`, `signal_score`, `confidence_pct` | Trade signal data from `get_trade_signals`. Emitted before images and text so the badge renders first. `recommendation` is `BUY`, `SELL`, or `HOLD`. `signal_score` is -1.0 to 1.0; `confidence_pct` is 0–100. |
| `token` | `text: str` | A chunk of the assistant's text response. Accumulate and re-render as markdown on each arrival. |
| `image` | `markdown: str` | A base64-embedded PNG in markdown image syntax: `![Title](data:image/png;base64,...)`. Emitted before the text tokens that caption the chart. |
| `error` | `text: str` | A user-friendly error message from the agent run. Raw exception text is never sent — exceptions are classified into safe messages by `_friendly_error()`. Displayed in red. |
| `citations` | `sources: [{label, detail}]` | Source chips emitted after `done`. Each entry has a `label` (e.g. "Yahoo Finance", "SEC 10-K · MSFT") and a `detail` (e.g. "AAPL · live price"). Displayed as a collapsible "📎 Sources" row below the response. |
| `done` | `title: str` | Signals end of stream. Carries the (possibly updated) session title so the sidebar can refresh. |

### Event ordering

For a chart response (e.g. "Show me AAPL price chart"):

```
data: {"type":"image","markdown":"![AAPL Price History](data:image/png;...)"}

data: {"type":"token","text":"This chart shows the 3-month price history"}
data: {"type":"token","text":" for Apple (AAPL)."}

data: {"type":"done","title":"Show me AAPL price chart"}
```

For a trade analysis response (e.g. "Should I buy MSFT?"):

```
data: {"type":"signal","ticker":"MSFT","recommendation":"BUY","signal_score":0.605,"confidence_pct":60.5}

data: {"type":"token","text":"📊 Trade Recommendation: BUY MSFT\n━━━━━━━━..."}
data: {"type":"token","text":"...Reply **yes** to execute, or **no** to cancel."}

data: {"type":"done","title":"should I buy MSFT?"}
```

The ordering guarantee: `signal` → `image` → `token`. Both `_current_signals` and `_current_images` are flushed in the `_stream()` generator before processing each ADK event's text parts.

### SSE wire format

```
data: {"type":"token","text":"Microsoft (MSFT) is currently"}\n\n
data: {"type":"token","text":" trading at $425.30"}\n\n
data: {"type":"done","title":"What is Microsoft's stock price?"}\n\n
```

Standard SSE: each event is a `data:` line followed by a blank line. The browser's `ReadableStream` + `TextDecoder` parses this without `EventSource` (which doesn't support POST bodies).

---

## Capture System (Images and Trade Signals)

Two types of tool output need to be intercepted by the web server and delivered to the browser as structured SSE events, before the LLM or audit layer can transform them:

| Data | Tool | Why intercept | SSE event |
|------|------|--------------|-----------|
| Chart PNG (base64, ~50KB) | `render_price_chart_for_ticker` + 3 others | `audit.py` strips it before LLM context — prevents ~170K-token hang | `{"type":"image","markdown":"..."}` |
| Trade signal (`confidence_pct`, `recommendation`, `signal_score`, `ticker`) | `get_trade_signals` | Data is available in the tool response dict; surfacing it as a structured UI element (badge + bar) requires delivery before the LLM embeds it in prose | `{"type":"signal",...}` |

Both are captured using the same `_patch_for_image_capture()` callback wrapping mechanism.

### Mechanism: `_patch_for_image_capture()`

Called once at startup, before the runner processes any requests.

```python
_CHART_RENDER_TOOLS = frozenset({
    "render_price_chart_for_ticker",
    "render_prediction_chart_for_ticker",
    "render_comparison_chart_for_tickers",
    "render_financial_chart_for_ticker",
})

def _patch_for_image_capture(agent) -> None:
    orig = getattr(agent, "after_tool_callback", None)
    if orig is not None:
        def _wrapped(tool, args, tool_context, tool_response, _orig=orig):
            # Chart capture
            if tool.name in _CHART_RENDER_TOOLS and isinstance(tool_response, dict):
                markdown = tool_response.get("markdown")
                if markdown:
                    imgs = _current_images.get()
                    if imgs is not None:
                        imgs.append(markdown)

            # Trade signal capture
            if (tool.name == "get_trade_signals"
                    and isinstance(tool_response, dict)
                    and tool_response.get("status") == "success"):
                sigs = _current_signals.get()
                if sigs is not None:
                    sigs.append({
                        "ticker":         tool_response.get("ticker", ""),
                        "recommendation": tool_response.get("recommendation", ""),
                        "signal_score":   tool_response.get("signal_score", 0),
                        "confidence_pct": tool_response.get("confidence_pct", 0),
                    })

            return _orig(tool, args, tool_context, tool_response)
        agent.after_tool_callback = _wrapped
    for sub in getattr(agent, "sub_agents", []) or []:
        _patch_for_image_capture(sub)
```

The wrapper fires before `audit.py`'s callback. It captures what it needs, then delegates to the original.

### Mechanism: ContextVars

Each SSE request gets its own private lists via `ContextVar`:

```python
_current_images:  contextvars.ContextVar[list | None] = ContextVar("_current_images",  default=None)
_current_signals: contextvars.ContextVar[list | None] = ContextVar("_current_signals", default=None)

async def _stream(session_id, question, session):
    images:  list[str]  = []
    signals: list[dict] = []
    ctx_token = _current_images.set(images)
    sig_token = _current_signals.set(signals)
    try:
        async for event in _runner.run_async(...):
            while signals:
                yield _sse({"type": "signal", **signals.pop(0)})
            while images:
                yield _sse({"type": "image", "markdown": images.pop(0)})
            # ... yield text tokens ...
    finally:
        _current_images.reset(ctx_token)
        _current_signals.reset(sig_token)
```

`ContextVar` is the correct primitive here because:
- Python's `asyncio` propagates the current `contextvars.Context` to child tasks and `run_in_executor` calls (as of Python 3.7)
- ADK callbacks fire synchronously within `runner.run_async`, in the same asyncio task as the SSE generator
- Each SSE request coroutine has its own context copy — concurrent sessions never share lists

### Full delivery path (trade signal)

```
get_trade_signals("MSFT")
  └─ returns {
       "status": "success",
       "ticker": "MSFT",
       "recommendation": "BUY",
       "signal_score": 0.605,
       "confidence_pct": 60.5,
       ... (price, analyst data, etc.)
     }
         │
         ├──▶ _patch_for_image_capture wrapper fires first
         │      _current_signals.get().append({ticker, recommendation,
         │                                     signal_score, confidence_pct})
         │
         └──▶ audit.py after_tool_callback fires normally
                logs tool response, applies guardrails

_stream() generator (before next token):
  while signals: yield {"type":"signal","ticker":"MSFT","recommendation":"BUY",...}
  → browser receives signal event, renders badge above text  ✓

LLM writes: "📊 Trade Recommendation: BUY MSFT ..."
  → yield {"type":"token","text":"📊 Trade Recommendation..."}
  → badge already visible; text arrives below it  ✓
```

### Full delivery path (chart image)

```
render_price_chart_for_ticker("AAPL")
  └─ returns {
       "status": "success",
       "title":  "AAPL Price History",
       "markdown": "![AAPL Price History](data:image/png;base64,...50KB)"
     }
         │
         ├──▶ _patch_for_image_capture wrapper fires first
         │      _current_images.get().append("![...](...)")
         │
         └──▶ audit.py after_tool_callback fires
                strips "markdown" key
                LLM context receives {status, title} — ~20 tokens, no hang  ✓

_stream() generator:
  while images: yield {"type":"image","markdown":"![...](...)"}
  → browser renders <img> via marked.js  ✓

LLM writes caption text → appended below chart  ✓
```

---

## Frontend Design

**File:** `static/index.html` — fully self-contained single-page application. No build step. One external CDN dependency: `marked.js` for markdown rendering.

### Layout

```
┌──────────────────────────────────────────────────────────────────┐
│  sidebar (250px)      │  main                                    │
│                       │  ┌────────────────────────────────────┐  │
│  [Stock Agent]  [+New]│  │  chat-header: session title        │  │
│                       │  └────────────────────────────────────┘  │
│  ┌─────────────────┐  │  ┌────────────────────────────────────┐  │
│  │ Session title   │  │  │  messages                          │  │
│  │ May 2, 10:30    │  │  │                                    │  │
│  └─────────────────┘  │  │  [user bubble — right/blue]        │  │
│  ┌─────────────────┐  │  │                                    │  │
│  │ Another session │  │  │  [assistant bubble — left/dark]    │  │
│  │ May 2, 09:15    │  │  │    img (chart, if any)             │  │
│  └─────────────────┘  │  │    markdown text                   │  │
│  ...                  │  │                                    │  │
│                       │  └────────────────────────────────────┘  │
│                       │  ┌────────────────────────────────────┐  │
│                       │  │  [☰] [textarea input]    [Send]    │  │
│                       │  └────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### Markdown rendering

All assistant text is rendered via `marked.parse(accText)` and set as `innerHTML`. This handles:

| Content type | How rendered |
|---|---|
| Plain text | Paragraph |
| Tables | `<table>` with CSS borders |
| Code blocks | `<pre><code>` with monospace font |
| Inline code | `<code>` with background highlight |
| `![title](data:image/png;base64,...)` | Native `<img>` — no image server needed |
| Bold, italic, blockquote, horizontal rule | Standard HTML elements |

`marked.setOptions({ breaks: true, gfm: true })` enables GitHub-flavoured markdown and newline-as-`<br>`.

### SSE client

The browser does not use the `EventSource` API because `EventSource` only supports GET requests with no body. Instead, the client uses `fetch()` + `ReadableStream`:

```javascript
const res = await fetch(`/api/chat/${activeId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: text }),
});
const reader = res.body.getReader();
const decoder = new TextDecoder();
let buf = '';

while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buf += decoder.decode(value, { stream: true });
    const lines = buf.split('\n');
    buf = lines.pop() ?? '';

    for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const ev = JSON.parse(line.slice(6));
        // dispatch on ev.type ...
    }
}
```

The `buf` accumulator handles the case where a chunk boundary falls in the middle of a `data:` line.

### Streaming display

The assistant bubble is built incrementally as events arrive:

```
bubble
  ├─ signalZone div  (signal badge inserted here on "signal" event)
  ├─ imgZone    div  (images inserted here as they arrive)
  └─ textZone   div  (marked.parse(accText) re-rendered on each token)
```

While waiting for the first event, the bubble shows a three-dot typing animation. On the first `signal`, `token`, or `image` event, the animation is removed and the three zones are inserted.

### Signal badge

When a `signal` event arrives, a `.signal-badge` element is injected into `signalZone`:

```
┌─────────────────────────────────────┐
│  [BUY]  MSFT                score 0.61 │   ← pill + ticker + score
│  Confidence  ████████░░░░  61%      │   ← confidence bar
└─────────────────────────────────────┘
```

- **Pill colour**: green (`#4ade80`) for BUY, red (`#f87171`) for SELL, grey (`#94a3b8`) for HOLD
- **Bar fill**: same colour family, width = `confidence_pct%`
- **Score**: raw `signal_score` (-1.0 to 1.0) shown as a secondary label

The badge is a pure CSS component — no JavaScript library, no external assets.

### Response feedback

A `👍 👎` row fades in below every assistant bubble after the stream ends. It is not shown while streaming — the animation (`fadeIn 0.3s delay 0.2s`) ensures it only appears on a completed response.

**Interaction states:**

| Action | Result |
|--------|--------|
| Click 👍 | Highlights green, sends `POST /api/feedback {rating:"up"}` |
| Click 👎 | Highlights red, sends `POST /api/feedback {rating:"down"}` |
| Click selected thumb again | Deselects — no API call |
| Click opposite thumb | Switches highlight, sends new POST |

**API call:**
```
POST /api/feedback
{
  "session_id": "a3f9c1d2...",
  "msg_index":  2,              // index in session["messages"]
  "rating":     "up",
  "preview":    "MSFT is currently trading at $414..."  // first 120 chars
}
→ {"ok": true}
```

**Persistence:** appended to `feedback.jsonl` (project root), one JSON record per line. Append-only — no deletes or updates. Latest entry per `(session_id, msg_index)` pair wins at read time.

```
{"ts":"2026-05-03T10:30Z","session_id":"a3f9...","msg_index":2,"rating":"up","preview":"MSFT is currently..."}
{"ts":"2026-05-03T10:35Z","session_id":"a3f9...","msg_index":4,"rating":"down","preview":"The 2-week forecast..."}
```

Feedback rows also appear on historical messages when a past session is loaded (`renderSession()` attaches a row to every assistant bubble at `msg_index = i`). Failures are silent — a network error on the feedback POST does not surface to the user.

**Why JSONL, not a database:** single-user, low write volume — matches the `trades.jsonl` pattern already in the codebase. Natural upgrade path is SQLite when multi-user authentication is added.

---

### Prompt library

A `☰` button sits left of the textarea. Clicking it opens a full-screen-overlay modal (`#prompt-modal-overlay`) containing a search bar and 12 categorised prompt sections.

**Categories:**

| Category | Example prompts |
|----------|----------------|
| 📈 Price | "What is the current price of MSFT?" |
| 🔮 Forecast | "What is the 2-week price forecast for AAPL?" |
| 📊 Price + Forecast | "Show me the current price and 2-week prediction for AAPL" |
| 🖼️ Charts | "Show me a price history chart for MSFT", comparison charts |
| 🔭 Price + Forecast Chart | "Visualise the 2-week prediction for AAPL" |
| 💰 Financial Reports | Revenue, EPS, margins, cash flow, balance sheet |
| 📋 Annual Reports (10-K) | Risk factors, MD&A, competition, executive compensation |
| ⚖️ Stock Comparison | "Compare MSFT vs GOOGL vs AAPL across all time horizons" |
| 🔬 Investment Research | Cross-section 10-Q/10-K multimodal analysis |
| 📄 PDF Export | "Generate a PDF report for MSFT" |
| 🔔 Drop Alerts | "Alert me if AAPL drops more than 5%" |
| 🤝 Trading (Mock) | Buy/sell signals, portfolio view, trade history |

**Interaction model:**
- Search input filters all chips live; categories with no matches hide entirely
- Clicking a chip copies the prompt text into the textarea and closes the modal
- Close via ✕ button, clicking the backdrop, or `Escape`
- Prompt data is defined as a static `PROMPT_LIBRARY` array in `static/index.html` — no server round-trip

**Data flow:**
```
User clicks ☰
  → openPromptLib() → modal visible, search focused
  → types query → filterPrompts() hides non-matching chips + empty categories
  → clicks chip → selectPrompt(text) → fills textarea, closes modal
  → presses Enter → sendMessage() runs normally
```

### Session management

| Action | Browser behaviour | Server call |
|---|---|---|
| Page load | `GET /api/sessions` → load most recent session or create new | — |
| New session | Creates session, clears chat area, focuses input | `POST /api/sessions` |
| Click session in sidebar | Fetches full session, renders all messages | `GET /api/sessions/{id}` |
| Send message | Shows user bubble, opens SSE stream | `POST /api/chat/{id}` |
| `done` event | Updates sidebar title, re-renders sidebar | — |
| Delete session (✕ hover) | Styled confirm dialog → `DELETE`, removes from sidebar | `DELETE /api/sessions/{id}` |

---

### Analytics tab

The Analytics tab is the third main-area tab alongside Chat and Trading History. It is a purely client-side dashboard powered by two new read-only API endpoints and the same localStorage trade ledger used by Trading History.

#### Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│  [Total Portfolio]  [Cash]  [Open Positions]  [Unrealised P&L]       │  ← summary cards
├───────────────────────────┬──────────────────────────────────────────┤
│  Asset Allocation         │  Holdings Table                          │
│  [Doughnut — Chart.js]    │  Symbol · Shares · Avg · Price ·         │
│                           │  Mkt Value · Gain/Loss · %               │
├───────────────────────────┴──────────────────────────────────────────┤
│  Current Prices  [AAPL ▲]  [MSFT ▲]  [NVDA ▲]  …                   │  ← price cards
├──────────────────────────────────────────────────────────────────────┤
│  Portfolio Value — 3-Month Trend  [Area line — Chart.js]             │
├──────────────────────────────────────────────────────────────────────┤
│  Individual Stock Prices — 3-Month Trend  [Multi-line — Chart.js]    │
└──────────────────────────────────────────────────────────────────────┘
```

#### Data flow

```
switchTab('analytics')
  │
  └─▶ loadAnalytics()
        │
        ├─ loadTrades()         ← localStorage["trades_{user}"]
        │
        ├─ _computePositions()  ← net shares per ticker (replays trade history)
        │
        ├─ _computeCash()       ← $100,000 starting cash ± BUY/SELL amounts
        │
        ├─ GET /api/prices?tickers=AAPL,MSFT,...
        │     └─ yfinance fast_info → {price, change, change_pct}
        │
        ├─ GET /api/price-history?tickers=AAPL,MSFT,...&period=3mo
        │     └─ yfinance .history() → [{date, close}, ...]
        │
        └─ render:
             _renderSummaryCards()      → 4 KPI cards
             _renderAllocationChart()   → Chart.js doughnut (destroy+recreate)
             _renderHoldingsTable()     → table rows with gain/loss colouring
             _renderPriceCards()        → one card per held ticker
             _renderPortfolioTrend()    → Chart.js area line (trade replay × history)
             _renderStockTrends()       → Chart.js multi-line
```

#### Portfolio value trend computation

For each calendar date in the 3-month price history:
1. Replay every trade whose `date ≤ current_date` (sorted ascending) to compute net shares per ticker and cash balance at that point in time.
2. For each held position, look up the closing price on `current_date` from the history map.
3. `portfolio_value = cash + Σ(shares × close)`. If a stock has no closing price entry for a date (e.g. newly acquired ticker), the position's cost basis is used as a fallback.

This runs entirely in the browser — no server-side portfolio state is stored.

#### Chart.js usage

| Chart | Type | ID |
|---|---|---|
| Asset allocation | `doughnut` | `allocation-chart` |
| Portfolio trend | `line` (filled) | `portfolio-trend-chart` |
| Individual stocks | `line` (multi-dataset) | `stock-trends-chart` |

Chart instances are stored in module-level variables (`_allocChart`, `_trendChart`, `_stocksChart`). On every refresh, existing instances are `destroy()`ed before new ones are created to prevent canvas reuse errors.

Chart.js is loaded via CDN: `https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js`.

Session titles are derived from the first user message (truncated to 55 chars). The server sets the title in `_sessions` and returns it in the `done` event so the sidebar can update without a separate fetch.

---

## Sequence Diagrams

### Starting a new session and sending the first message

```
Browser              web_server.py        InMemorySessionService
   │                       │                        │
   │  POST /api/sessions   │                        │
   │──────────────────────▶│                        │
   │                       │  uuid.uuid4().hex       │
   │                       │  create_session() ─────▶│
   │                       │                        │
   │◀── {id, title, ...} ──│                        │
   │  (activeId = id)      │                        │
   │                       │                        │
   │  POST /api/chat/id    │                        │
   │  {"message":"MSFT?"}  │                        │
   │──────────────────────▶│                        │
   │                       │  session["title"] = "MSFT?"
   │                       │  session["messages"].append(user)
   │                       │                        │
   │◀── 200 text/event-stream ─────────────────────│
   │                       │                        │
   │  data: {"type":"token","text":"Microsoft..."}  │
   │◀──────────────────────│                        │
   │  [appended + re-rendered via marked.parse]     │
   │                       │                        │
   │  data: {"type":"done","title":"MSFT?"}         │
   │◀──────────────────────│                        │
   │  [sidebar title updated]                       │
```

---

### Chart response (image arrives before caption)

```
Browser              web_server.py       _wrapped callback     audit.py callback
   │                       │                    │                      │
   │  POST /api/chat/id    │                    │                      │
   │  {"message":"chart"}  │                    │                      │
   │──────────────────────▶│                    │                      │
   │◀── 200 SSE ───────────│                    │                      │
   │                       │                    │                      │
   │     [runner runs: render_price_chart_for_ticker fires]            │
   │                       │                    │                      │
   │                       │  tool returns {status, title, markdown}   │
   │                       │                    │                      │
   │                       │    _wrapped fires first ─────────────────│
   │                       │    _current_images.append(markdown)       │
   │                       │                    │                      │
   │                       │                    │  audit.py fires next │
   │                       │                    │  strips "markdown"   │
   │                       │                    │  LLM gets {status,title}
   │                       │                    │                      │
   │                       │  flush images:     │                      │
   │  data: {"type":"image","markdown":"![...](...base64...)"}         │
   │◀──────────────────────│                    │                      │
   │  [<img> rendered inline via marked.parse]  │                      │
   │                       │                    │                      │
   │                       │  LLM writes caption text                  │
   │  data: {"type":"token","text":"This chart shows..."}              │
   │◀──────────────────────│                    │                      │
   │  [caption appended below chart]            │                      │
   │                       │                    │                      │
   │  data: {"type":"done","title":"..."}       │                      │
   │◀──────────────────────│                    │                      │
```

---

### Trade signal response (badge appears before text)

```
Browser              web_server.py       _wrapped callback     trading_agent
   │                       │                    │                    │
   │  POST /api/chat/id    │                    │                    │
   │  {"message":"buy?"}   │                    │                    │
   │──────────────────────▶│                    │                    │
   │◀── 200 SSE ───────────│                    │                    │
   │                       │                    │                    │
   │     [runner routes to trading_agent; agent calls get_trade_signals]
   │                       │                    │                    │
   │                       │  tool returns {status:"success",        │
   │                       │    ticker, recommendation, signal_score,│
   │                       │    confidence_pct, ...}                 │
   │                       │                    │                    │
   │                       │    _wrapped fires first ────────────────│
   │                       │    _current_signals.append({            │
   │                       │      ticker, recommendation,            │
   │                       │      signal_score, confidence_pct})     │
   │                       │                    │                    │
   │                       │  flush signals:                         │
   │  data: {"type":"signal","ticker":"MSFT","recommendation":"BUY", │
   │          "signal_score":0.605,"confidence_pct":60.5}            │
   │◀──────────────────────│                    │                    │
   │  [badge rendered: green BUY pill + 61% bar]│                    │
   │                       │                    │                    │
   │                       │  LLM writes recommendation text         │
   │  data: {"type":"token","text":"📊 Trade Recommendation..."}     │
   │◀──────────────────────│                    │                    │
   │  [text rendered below badge]               │                    │
   │                       │                    │                    │
   │  data: {"type":"done","title":"..."}        │                    │
   │◀──────────────────────│                    │                    │
```

---

### Loading a historical session

```
Browser              web_server.py
   │                       │
   │  (user clicks session │
   │   in sidebar)         │
   │  GET /api/sessions/id │
   │──────────────────────▶│
   │                       │
   │◀── {id, title, messages: [
   │      {role:"user",    content:"MSFT?",   images:[]},
   │      {role:"assistant",content:"MSFT...",images:["![...](base64)"]},
   │      ...
   │    ]} ────────────────│
   │                       │
   │  renderSession():     │
   │  for each message:    │
   │    appendMsg(role,    │
   │     content, images)  │
   │  (images rendered via │
   │   marked.parse before │
   │   text)               │
```

---

## Error Handling

### SSE stream errors (`_friendly_error`)
Exceptions that occur during `_stream()` are classified into user-facing categories instead of surfacing raw Python exception text (which may contain internal paths, service names, or stack traces).

| Exception signal | User message |
|---|---|
| `ConnectionError`, `network`, `refused` | "Unable to reach a data service. Please try again shortly." |
| `rate limit`, `quota`, `429`, `resource exhausted` | "API quota reached. Please wait a moment and try again." |
| `MALFORMED_FUNCTION_CALL`, `JSONDecodeError` | "The agent returned an unexpected response. Please rephrase your query." |
| `prompt not found`, `FileNotFoundError` | "Agent configuration error. Please contact support." |
| `timeout`, `deadline exceeded` | "The request took too long. Please try a simpler query." |
| Anything else | "Something went wrong. Please try again or rephrase your query." |

The full exception and traceback are always written to the server log via `_logger.exception()`. Only the classified string is sent in the SSE `error` event.

### Unhandled route exceptions (global handler)
`@app.exception_handler(Exception)` catches any exception that escapes a route handler before a response starts. Returns:
```json
{"detail": "An unexpected error occurred. Please try again."}
```
as a clean HTTP 500. The traceback is logged server-side. Raw exception detail is never included in the response body.

---

## Design Decisions

### FastAPI over ADK Web

ADK Web (`adk web`) is a generic development tool: it streams all ADK events (tool calls, routing events, partial model outputs) in a raw format, has no session history, no custom chat layout, and no chart-rendering logic. Building a domain-specific frontend requires owning the server layer.

FastAPI was chosen over Flask or raw ASGI because:
- Async-native: `async def` route handlers + async generators for SSE work without threading
- Pydantic request validation with no boilerplate
- `StreamingResponse` wraps an async generator directly

---

### SSE over WebSocket

| Factor | SSE | WebSocket |
|---|---|---|
| Direction | Server → client (unidirectional) | Bidirectional |
| Protocol | HTTP/1.1 (standard) | Upgrade to ws:// |
| Browser auto-reconnect | Yes (EventSource) | Manual |
| POST body support | Not with EventSource (use fetch + ReadableStream) | N/A |
| Simplicity | One `StreamingResponse` on the server | Connection manager + message routing |

Chat streaming is strictly server → client. SSE is the correct, simpler protocol. The only nuance: because the message is a POST body, the browser uses `fetch()` + `ReadableStream` instead of the `EventSource` API, which is GET-only.

---

### ContextVar for request-scoped capture (images and signals)

The callback patching (`_patch_for_image_capture`) happens once at startup — the wrapped callback is shared across all requests. Each concurrent SSE request needs its own image and signal lists. Options considered:

| Option | Problem |
|---|---|
| Global dict keyed by `session_id` | Two concurrent requests on the same session would race |
| Thread-local | Not meaningful in async code |
| Pass image list as a closure per request | Would require re-patching callbacks on every request |
| **`ContextVar`** | Each asyncio coroutine gets its own context copy; no shared mutable state |

Python 3.7+ propagates `contextvars.Context` into child tasks and `run_in_executor` threads, so the ContextVar value set in the SSE generator is visible in the callback even if ADK uses task switching internally.

---

### Session persistence

Sessions survive server restarts via two SQLite files:

**`sessions.db`** — owned by ADK's `SqliteSessionService`. Stores the full event history for every session (LLM turns, tool calls, function responses). The ADK runner reads this to reconstruct multi-turn conversational context. No application code writes to this file directly.

**`sessions_meta.db`** — owned by the web server. Two tables:

```sql
sessions (id TEXT PRIMARY KEY, title TEXT, created_at TEXT)
messages (session_id TEXT, idx INTEGER, role TEXT, content TEXT, images TEXT)
```

Write-through on every mutation:

| Mutation | SQLite write |
|----------|-------------|
| `POST /api/sessions` | `_meta_upsert_session` → sessions row |
| First user message (title derived) | `_meta_upsert_session` → updates title |
| User message appended | `_meta_save_message` → messages row |
| Assistant message appended (stream finally) | `_meta_save_message` → messages row |

**Startup sequence:**

```
1. _meta_init()              — create tables if not exist
2. _meta_load_all()          — populate _sessions dict from sessions_meta.db
3. app starts (FastAPI)
4. _on_startup() fires:
     _rehydrate_adk_sessions()
       — list_sessions() from sessions.db
       — for any session in _sessions not in sessions.db:
           create_session() to register it
```

Step 4 handles the case where `sessions_meta.db` has sessions that `sessions.db` doesn't (e.g. after `sessions.db` is deleted). Both stores are always brought into sync before the first request is served.

**Why two files instead of one?**

ADK owns `sessions.db` schema — the web server must not write to it directly. `sessions_meta.db` stores only what the browser needs (rendered text, titles, image markdown). Keeping them separate means either can be deleted and rebuilt independently without corrupting the other.

---

### marked.js for client-side markdown

`marked.js` renders GitHub-flavoured markdown including `![...](data:image/png;base64,...)` tags as native `<img>` elements. The browser handles base64 image display natively — no image proxy, no separate static file server, no API endpoint for image data. The base64 string stays entirely within the SSE event payload and the DOM.

---

## Known Limitations

| Limitation | Impact | Mitigation |
|---|---|---|
| Sessions are in-memory | ~~Lost on server restart~~ **Fixed** — both `sessions.db` and `sessions_meta.db` persist across restarts | — |
| ~~Single `_USER_ID` for all sessions~~ | **Fixed** — `username` from JWT is passed as `user_id` throughout the session lifecycle | — |
| No streaming abort | User cannot cancel a slow agent turn mid-stream | `reader.cancel()` on the browser side; `asyncio.CancelledError` handling in `_stream()` |
| Session title truncated to 55 chars | Long questions produce cut-off titles | Truncation is intentional for sidebar space; consider a title-generation LLM call for polish |
| One message at a time per session | Sending a second message while streaming is blocked by the client-side `streaming` flag | Queue or cancel-and-replace semantics for concurrent turns |
| Feedback stored in flat file | `feedback.jsonl` has no deduplication — latest entry per `(session_id, msg_index)` must be resolved at read time | Migrate to SQLite with an `UPSERT` on `(session_id, msg_index)` when multi-user support is added |
| Analytics prices are point-in-time snapshots | `GET /api/prices` calls yfinance at request time; values do not auto-update | Add a polling interval or WebSocket feed to the analytics panel |
| Analytics trade ledger is browser-local | `localStorage` data is not synced across devices or users | Migrate to a server-side `POST/GET /api/trades` endpoint |
| Portfolio trend uses cost basis as price fallback | If a ticker has no historical price for a given date, the position's cost basis is substituted | Use previous-day close as fallback instead |
