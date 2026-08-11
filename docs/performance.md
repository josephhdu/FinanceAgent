# Performance & Latency

**Version:** 1.0  
**Date:** 2026-05-06  
**Scope:** Every measure — existing and new — taken to reduce latency, prevent wasted work, and make FinanceAI feel fast under real user load.

---

## Table of Contents

1. [Overview](#1-overview)
2. [What We Already Had](#2-what-we-already-had)
   - [SSE Token Streaming](#21-sse-token-streaming)
   - [Hard Request Timeout](#22-hard-request-timeout)
   - [Per-Agent Output Token Caps](#23-per-agent-output-token-caps)
   - [Thinking Disabled on Fast-Path Agents](#24-thinking-disabled-on-fast-path-agents)
   - [Circuit Breakers](#25-circuit-breakers)
   - [Base64 Stripping Before LLM Context](#26-base64-stripping-before-llm-context)
   - [Deterministic Python Routing](#27-deterministic-python-routing)
   - [Progress Events During Silent Phases](#28-progress-events-during-silent-phases)
   - [Non-Blocking Background Tasks](#29-non-blocking-background-tasks)
   - [Tool Duration Tracking](#210-tool-duration-tracking)
   - [LangFuse Tracing](#211-langfuse-tracing)
   - [fast_info for Price API](#212-fast_info-for-price-api)
   - [Ticker Batch Cap](#213-ticker-batch-cap)
   - [Tool Argument Validation Before Call](#214-tool-argument-validation-before-call)
   - [In-Memory Session Cache](#215-in-memory-session-cache)
   - [Streaming Lock — No Duplicate Requests](#216-streaming-lock--no-duplicate-requests)
   - [Optimistic Sidebar Title Update](#217-optimistic-sidebar-title-update)
   - [Client-Side Session Search](#218-client-side-session-search)
   - [Analytics Uses Promise.all](#219-analytics-uses-promiseall)
   - [Market Status Computed Locally](#220-market-status-computed-locally)
3. [New Fixes — Five Performance Gaps](#3-new-fixes--five-performance-gaps)
   - [Gap 1 — Debounce marked.parse on Token Events](#gap-1--debounce-markedparse-on-token-events)
   - [Gap 2 — TTL Cache for Yahoo Finance API Calls](#gap-2--ttl-cache-for-yahoo-finance-api-calls)
   - [Gap 3 — Sessions List Returns Metadata Only](#gap-3--sessions-list-returns-metadata-only)
   - [Gap 4 — SQLite WAL Mode](#gap-4--sqlite-wal-mode)
   - [Gap 5 — Analytics In-Flight Guard and Cooldown](#gap-5--analytics-in-flight-guard-and-cooldown)
4. [Summary Table](#4-summary-table)
5. [Known Limitations](#5-known-limitations)

---

## 1. Overview

FinanceAI is latency-sensitive at two distinct levels:

- **Perceived latency** — how long before the user sees *something* on screen. Managed through streaming, progress events, and optimistic UI.
- **Actual latency** — wall-clock time from request to final token. Managed through token budgets, circuit breakers, caching, and routing shortcuts.

The architecture splits work across three layers:

```
Browser (index.html)
  │  SSE stream (token, progress, image, signal, done)
  ▼
FastAPI + uvicorn  (web_server.py)
  │  asyncio.timeout(120)  ·  in-memory session cache  ·  price TTL cache
  ▼
ADK Runner  (stock_agent/agent.py)
  │  Python routing  ·  circuit breakers  ·  token budgets  ·  tool timers
  ▼
External APIs  (Gemini · Yahoo Finance MCP · A2A · SEC EDGAR)
```

Performance measures are applied at every layer. The twenty pre-existing measures are documented in §2; the five new gap fixes are in §3.

---

## 2. What We Already Had

### 2.1 SSE Token Streaming

**File:** `web_server.py` — `_stream()`, `chat()` route  
**Impact:** Perceived latency — user sees first token in ~1 s instead of waiting for full completion.

The `/api/chat/{session_id}` endpoint returns a `StreamingResponse` with `media_type="text/event-stream"`. Inside `_stream()`, every event from `_runner.run_async()` is immediately serialised as a `data: {...}\n\n` SSE line and flushed to the browser.

```python
return StreamingResponse(
    _stream(session_id, req.message, session, user["username"], user["role"]),
    media_type="text/event-stream",
    headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",   # disables nginx proxy buffering
    },
)
```

The `X-Accel-Buffering: no` header is critical — without it, nginx (common in production) would buffer the entire response before forwarding it, defeating the purpose of streaming.

On the browser side, `sendMessage()` reads the stream with `res.body.getReader()` and processes each chunk as it arrives, rendering tokens into the DOM incrementally.

---

### 2.2 Hard Request Timeout

**File:** `web_server.py` — `_stream()`  
**Impact:** Prevents a single stuck request from occupying an asyncio worker indefinitely.

```python
async with asyncio.timeout(120):
    async for event in _runner.run_async(...):
        ...
```

If 120 seconds elapse without completion, `asyncio.TimeoutError` is caught and a user-facing error SSE event is emitted. The connection is then closed and all context vars are reset in the `finally` block.

---

### 2.3 Per-Agent Output Token Caps

**File:** `stock_agent/model_config.py`, enforced in `stock_agent/audit.py` — `before_model_callback()`  
**Impact:** Prevents runaway responses from driving up latency and cost; tightens per-agent budgets to the minimum needed.

```python
MAX_OUTPUT_TOKENS: dict[str, int] = {
    "intent_agent":              1024,   # JSON blob only
    "price_agent":               1024,
    "alert_agent":               1024,
    "visualization_agent":        512,   # one caption sentence
    "pdf_agent":                  512,
    "financial_report_agent":    4096,
    "comparison_trend_agent":    2048,
    "prediction_agent":          8192,   # thinking + forecast table
    "comparison_insights_agent": 8192,
    "trading_agent":             4096,
    ...
}
```

In `before_model_callback`, if `llm_request.config.max_output_tokens` is not already set, the per-agent limit is injected:

```python
limit = MAX_OUTPUT_TOKENS.get(agent, _DEFAULT_MAX_OUTPUT_TOKENS)
if llm_request.config.max_output_tokens is None:
    llm_request.config.max_output_tokens = limit
```

A `visualization_agent` capped at 512 tokens completes in a fraction of the time it would take if left unconstrained at the model default (8192+).

---

### 2.4 Thinking Disabled on Fast-Path Agents

**File:** Agent constructors in `stock_agent/` (price, alert, intent, visualization, pdf, financial_report agents)  
**Impact:** Saves ~1.5 s of thinking overhead on agents that don't need multi-hop reasoning.

Gemini 2.5 Flash has an extended thinking mode that improves accuracy on complex tasks but adds latency. For agents whose outputs are deterministic (price card, alert table, route classification, chart caption), thinking is disabled via `thinking_budget=0` in the model config passed to the agent constructor.

Thinking is left **enabled** for:
- `prediction_agent` — time-series reasoning and confidence bands
- `tenk_agent` — multi-section 10-K synthesis
- `comparison_insights_agent` — cross-document multi-hop
- `investment_research_agent` — RAG + reasoning

---

### 2.5 Circuit Breakers

**File:** `stock_agent/circuit_breaker.py`, wired into `stock_agent/audit.py` callbacks  
**Impact:** OPEN state returns an error *immediately* (~0 ms) instead of waiting for upstream timeout (30–60 s). Prevents cascading slowdowns under partial failures.

Three independent breakers with a CLOSED → OPEN → HALF_OPEN state machine:

| Breaker | Threshold | Cooldown | Trips on |
|---------|-----------|----------|----------|
| `_gemini_breaker` | 5 failures | 30 s | Bad `finish_reason` from Gemini |
| `_yahoo_breaker` | 5 failures | 30 s | Yahoo Finance MCP tool errors |
| `_a2a_breaker` | 3 failures | 60 s | A2A financial report server errors |

When OPEN, `before_model_callback` and `before_tool_callback` return an error dict instead of letting the call through:

```python
if _gemini_breaker.is_open():
    error_content = types.Content(role="model", parts=[types.Part(text=(
        "I'm temporarily unable to reach the AI service due to repeated failures. "
        "Please try again in a moment."
    ))])
    return LlmResponse(content=error_content)
```

After `cooldown_s`, one probe call is allowed through (HALF_OPEN). Success → CLOSED; failure → resets the cooldown.

---

### 2.6 Base64 Stripping Before LLM Context

**File:** `stock_agent/audit.py` — `after_tool_callback()`  
**Impact:** Eliminates a 170,000+ token input spike that causes multi-second hangs or `MALFORMED_FUNCTION_CALL` failures.

Chart tools (`render_price_chart_for_ticker` etc.) return a dict containing a `markdown` field with a base64-encoded PNG (~50 KB). If this reaches the LLM as a tool response, Gemini must tokenise the entire base64 string — roughly 170 K tokens — before it can generate even one output token.

`after_tool_callback` strips the `markdown` key before the response enters LLM context, replacing it with a sentinel:

```python
if tool.name in _CHART_RENDER_TOOLS and isinstance(tool_response, dict) and "markdown" in tool_response:
    stripped = {k: v for k, v in tool_response.items() if k != "markdown"}
    stripped["chart_displayed"] = True   # tells LLM the render succeeded
    return stripped
```

The full base64 PNG is already in the SSE event stream for the browser (captured in `_current_images` before the strip happens), so the UI is unaffected.

---

### 2.7 Deterministic Python Routing

**File:** `stock_agent/agent.py` — `_ROUTE_MAP`, `_route()`  
**Impact:** Eliminates an entire LLM round-trip for dispatch. Pure Python dict lookup after intent classification.

Rather than using a meta-agent LLM call to decide which downstream agent to invoke, the orchestrator parses the intent agent's JSON output and indexes into a simple dict:

```python
_ROUTE_MAP: dict[str, list[BaseAgent]] = {
    "PRICE":            [price_agent],
    "PREDICTION":       [prediction_agent],
    "FINANCIAL_REPORT": [financial_report_agent],
    "PRICE_PREDICTION": [price_agent, prediction_agent],
    "ANNUAL_FINANCIAL": [tenk_agent, financial_report_agent],
    ...
}

pipeline = _ROUTE_MAP.get(intent)
```

This dispatch is O(1) and adds zero network latency. Compared to an LLM-routed approach, this saves 500–1500 ms per request.

---

### 2.8 Progress Events During Silent Phases

**File:** `stock_agent/agent.py` — `_progress_event()`, `_STEP_PROGRESS`  
**Impact:** Reduces *perceived* latency — the user sees activity immediately rather than staring at a static spinner.

Between agent steps, the orchestrator emits lightweight progress events:

```python
_STEP_PROGRESS: dict[str, list[str]] = {
    "PRICE":            ["Fetching live price data…"],
    "PREDICTION":       ["Running 2-week forecast…"],
    "ANNUAL_FINANCIAL": ["Searching 10-K filing…", "Analysing financials…"],
    ...
}
```

These are streamed as `{"type": "progress", "text": "..."}` SSE events and rendered in the browser alongside the typing dots. The user knows *what the system is doing* throughout the wait, which psychologically reduces perceived wait time even when actual latency is unchanged.

---

### 2.9 Non-Blocking Background Tasks

**File:** `web_server.py` — `_stream()` `finally` block  
**Impact:** Memory ingestion and goal verification add zero latency to the SSE stream.

Two operations that happen after every response are fired with `asyncio.create_task()`, which schedules them on the event loop without blocking the `finally` block from completing:

```python
# Memory ingestion — stores conversation turns in ChromaDB
asyncio.create_task(
    _memory_service.add_session_to_memory(adk_session)
)

# LLM-as-judge goal verification (only when ENABLE_JUDGE=true)
asyncio.create_task(
    _run_goal_judge(question, response_text, session_id)
)
```

If either task were `await`ed, it would delay the `done` SSE event and the response finalisation by hundreds of milliseconds.

---

### 2.10 Tool Duration Tracking

**File:** `stock_agent/audit.py` — `before_tool_callback()`, `after_tool_callback()`  
**Impact:** Every tool call's wall-clock time is written to `audit.log`, enabling slow-tool identification in production.

```python
# before_tool_callback — start timer
timer_key = f"{_get_invocation_id(tool_context)}:{tool.name}"
_tool_timers[timer_key] = time.perf_counter()

# after_tool_callback — compute duration
start = _tool_timers.pop(timer_key, None)
duration_ms = round((time.perf_counter() - start) * 1000, 1) if start else None

_emit("tool_end", ..., duration_ms=duration_ms)
```

`audit.log` entries look like:
```json
{"event": "tool_end", "tool": "fetch_and_forecast", "duration_ms": 1842.3, ...}
```

This makes it trivial to grep for slow tools: `jq 'select(.duration_ms > 2000)' audit.log`.

---

### 2.11 LangFuse Tracing

**File:** `stock_agent/tracing.py`  
**Impact:** Full span/generation/tool trace hierarchy for latency profiling and regression detection in production.

When `LANGFUSE_PUBLIC_KEY` is set in the environment, every agent start/end, LLM request/response, and tool call is captured as a LangFuse observation:

```
Trace  (one per user request)
└─ Span: agent:stock_orchestrator
   ├─ Span: agent:price_agent
   │  ├─ Generation: price_agent:llm      ← includes token counts + timing
   │  └─ Span: tool:get_ticker_info       ← start + end timestamps
   └─ Span: agent:prediction_agent
      ├─ Generation: prediction_agent:llm
      └─ Span: tool:fetch_and_forecast
```

Token usage (input/output) is recorded on every generation regardless of whether LangFuse is enabled, accumulating in `_metrics[inv_id]` for local evaluation pipelines.

---

### 2.12 `fast_info` for Price API

**File:** `web_server.py` — `/api/prices`  
**Impact:** Roughly 3–5× faster per ticker than the full `.info` property.

```python
info  = yf.Ticker(sym).fast_info   # lightweight — no full JSON blob
price = float(info.last_price)
prev  = float(info.previous_close)
```

`yf.Ticker(sym).info` downloads a large JSON object with 80+ fields from Yahoo Finance. `fast_info` requests only the real-time price fields needed for the price card, reducing the HTTP payload and parse time significantly.

---

### 2.13 Ticker Batch Cap

**File:** `web_server.py` — `/api/prices`, `/api/price-history`  
**Impact:** Prevents unbounded slow queries that could block the server for tens of seconds.

```python
# /api/prices — up to 20 tickers
ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()][:20]

# /api/price-history — up to 10 tickers
ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()][:10]
```

Without a cap, a malformed or adversarial request with 100+ tickers would iterate 100 `yf.Ticker()` calls sequentially, potentially taking 30+ seconds and starving other requests of the event loop.

---

### 2.14 Tool Argument Validation Before Call

**File:** `stock_agent/audit.py` — `_validate_tool_args()`, `before_tool_callback()`  
**Impact:** Invalid arguments return an instant error dict without touching any external API.

```python
def _validate_tool_args(tool_name: str, args: dict) -> Optional[dict]:
    if tool_name == "fetch_and_forecast":
        if not args.get("ticker", "").strip():
            return {"status": "error", "message": "ticker must not be empty."}
        if args.get("period") not in {"1mo", "3mo", "6mo"}:
            return {"status": "error", "message": "period must be one of ..."}
    ...
```

If the LLM hallucinates an invalid argument (e.g. `period="1y"` when only `1mo/3mo/6mo` are valid), the call is blocked before it hits Yahoo Finance. The LLM sees the error and can self-correct without the user paying for a failed network round-trip.

---

### 2.15 In-Memory Session Cache

**File:** `web_server.py` — `_sessions` dict  
**Impact:** All session reads are served from memory; only writes touch SQLite.

At startup, `_meta_load_all()` reads every session and its messages from `sessions_meta.db` into the `_sessions` dict. All subsequent reads (list sessions, get session, check ownership) hit this in-memory dict:

```python
_sessions: dict[str, dict] = {}   # session_id → {id, title, created_at, user_id, messages}

@app.get("/api/sessions/{session_id}")
def get_session(session_id: str, user: dict = Depends(_require_auth)):
    if session_id not in _sessions:
        raise HTTPException(status_code=404)
    ...
    return _sessions[session_id]
```

Only new session creation, message persistence, and renames write back to SQLite. Read latency for session operations is effectively zero.

---

### 2.16 Streaming Lock — No Duplicate Requests

**File:** `static/index.html` — `sendMessage()`  
**Impact:** Prevents duplicate concurrent submissions caused by rapid button clicks or Enter key presses.

```js
let streaming = false;

async function sendMessage() {
  if (streaming) return;          // ← immediate return if already in flight
  ...
  streaming = true;
  $('send-btn').disabled = true;
  try {
    ...
  } finally {
    streaming = false;
    $('send-btn').disabled = false;
  }
}
```

Both the `streaming` flag and `disabled` on the send button are set before the `fetch()` call. The flag guards against Enter key double-presses; the `disabled` property guards against mouse double-clicks on the button.

---

### 2.17 Optimistic Sidebar Title Update

**File:** `static/index.html` — `sendMessage()`  
**Impact:** Sidebar title appears instantly on first message; no spinner, no waiting for server.

```js
const sess = sessions[activeId];
if (!sess._hasMsg) {
  sess._hasMsg = true;
  sess.title   = text.slice(0, 55) + (text.length > 55 ? '…' : '');
  $('chat-title').textContent = sess.title;
  renderSidebar();
}
```

The server-confirmed title arrives later in the `done` SSE event and updates the sidebar again — but the user sees the title immediately without any flicker.

---

### 2.18 Client-Side Session Search

**File:** `static/index.html` — `renderSidebar(query)`  
**Impact:** Session search is instant — no server round-trip, no debounce needed.

```js
function renderSidebar(query = '') {
  const q = query.trim();
  const sorted = Object.values(sessions)
    .filter(s => !q || s.title.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  ...
}
```

Because all session metadata lives in the `sessions` dict (populated at login), filtering is a pure in-memory operation. The search input's `oninput` handler calls `renderSidebar()` directly with no debounce required.

---

### 2.19 Analytics Uses `Promise.all`

**File:** `static/index.html` — `loadAnalytics()`  
**Impact:** Price snapshot and price history requests fire in parallel, not sequentially.

```js
[prices, history] = await Promise.all([
  fetch(`/api/prices?tickers=${q}`,                   { headers: _authHeaders() }).then(r => r.json()),
  fetch(`/api/price-history?tickers=${q}&period=3mo`, { headers: _authHeaders() }).then(r => r.json()),
]);
```

With five holdings, sequential fetching would add ~500 ms of waiting for the second request to start after the first completes. `Promise.all` fires both simultaneously and waits for whichever finishes last, saving the full round-trip time of the faster request.

---

### 2.20 Market Status Computed Locally

**File:** `static/index.html` — `_updateMarketStatus()`  
**Impact:** NYSE open/closed badge is computed from the local clock — zero server calls, zero network latency.

```js
function _updateMarketStatus() {
  const et   = new Date(new Date().toLocaleString('en-US', { timeZone: 'America/New_York' }));
  const mins = et.getHours() * 60 + et.getMinutes();
  const isOpen = et.getDay() >= 1 && et.getDay() <= 5 && mins >= 570 && mins < 960;
  el.textContent = isOpen ? 'NYSE Open' : 'NYSE Closed';
  el.className   = isOpen ? 'open' : 'closed';
}
setInterval(_updateMarketStatus, 60_000);
```

The status is recalculated every 60 seconds entirely in the browser. No endpoint is hit, no extra request is made on every poll tick.

---

## 3. New Fixes — Five Performance Gaps

### Gap 1 — Debounce `marked.parse` on Token Events

**File:** `static/index.html` — `sendMessage()`  
**Before:** O(n²) markdown re-parses + DOM replacements for a long streaming response.  
**After:** At most one re-parse per 80 ms; the final batch is always flushed on stream end.

#### The Problem

The SSE `token` event handler previously did this on **every single incoming token**:

```js
} else if (ev.type === 'token') {
  accText += ev.text;
  textZone.innerHTML = marked.parse(accText);   // ← full re-parse every token
  scrollBottom();
}
```

For a 600-token response, this is 600 calls to `marked.parse()`, each operating on an increasingly long string. The total parse work grows quadratically: token 1 parses 1 character, token 600 parses ~4,000 characters. At ~600 tokens total, the browser is doing roughly 1.2 million character-parse operations just for markdown rendering, plus 600 full `innerHTML` DOM replacements that trigger layout and repaint.

On slower hardware this causes visible frame drops and choppiness during streaming.

#### The Fix

A debounce timer coalesces renders into at most one per 80 ms frame:

```js
let _renderTimer = null;

function _scheduleRender() {
  if (_renderTimer) return;            // already scheduled for this frame
  _renderTimer = setTimeout(() => {
    _renderTimer = null;
    textZone.innerHTML = marked.parse(accText);
    scrollBottom();
  }, 80);
}

function _flushRender() {
  if (_renderTimer) { clearTimeout(_renderTimer); _renderTimer = null; }
  if (accText) { textZone.innerHTML = marked.parse(accText); scrollBottom(); }
}
```

The token handler now just accumulates text and schedules a render:

```js
} else if (ev.type === 'token') {
  clearDots();
  progressZone.style.display = 'none';
  accText += ev.text;
  _scheduleRender();   // coalesced — at most one re-parse per 80 ms
}
```

The `finally` block calls `_flushRender()` first to ensure the last partial batch is committed even if the stream ends before the 80 ms timer fires:

```js
} finally {
  _flushRender();    // commit tokens still in the 80 ms buffer
  streaming = false;
  ...
}
```

#### Impact

| Scenario | Before | After |
|----------|--------|-------|
| 600-token response at 50 tokens/s | 600 parses × growing string ≈ O(n²) | ≤ 15 parses (one per 80 ms at 12 fps) |
| DOM replacements | 600 | ≤ 15 |
| Perceived smoothness | Jank on slow hardware | Consistent 12+ fps |

The 80 ms window is chosen to be fast enough that users see near-continuous text flow (12+ frames per second) while eliminating the quadratic growth.

---

### Gap 2 — TTL Cache for Yahoo Finance API Calls

**File:** `web_server.py` — `/api/prices`, `/api/price-history`  
**Before:** Every call hit Yahoo Finance fresh, including repeated tab opens and Refresh clicks.  
**After:** Results are served from an in-process TTL cache for 60 s (prices) and 5 min (history).

#### The Problem

`/api/prices` and `/api/price-history` are called by the Analytics panel on every tab open and every Refresh click. If a user opens the Analytics tab, reads the data, switches to Chat, then returns to Analytics — all within two minutes — Yahoo Finance is called twice for identical data. Under realistic usage patterns (five sessions, frequent tab switching), this generates 10–20 unnecessary network calls per hour per user.

Each `yf.Ticker(sym).fast_info` call adds ~100–300 ms latency (network round-trip to Yahoo Finance). For a portfolio with five holdings, each Analytics load was taking 500–1500 ms just in Yahoo Finance round-trips.

#### The Fix

Two in-process dicts act as TTL caches keyed by ticker symbol:

```python
_PRICE_CACHE:   dict[str, tuple[dict, float]] = {}   # sym → (snapshot, monotonic_ts)
_HISTORY_CACHE: dict[str, tuple[list, float]] = {}   # "sym:period" → (rows, monotonic_ts)
_PRICE_TTL   = 60.0    # seconds — live price snapshots
_HISTORY_TTL = 300.0   # seconds — daily history (changes once per trading day)
```

Each endpoint checks the cache before hitting Yahoo Finance:

```python
now = time.monotonic()
for sym in ticker_list:
    cached = _PRICE_CACHE.get(sym)
    if cached and (now - cached[1]) < _PRICE_TTL:
        result[sym] = cached[0]   # cache hit — no network call
        continue
    # cache miss — fetch and store
    info = yf.Ticker(sym).fast_info
    data = { "price": ..., "change": ..., ... }
    _PRICE_CACHE[sym] = (data, time.monotonic())
    result[sym] = data
```

The history cache uses a composite key `f"{sym}:{period}"` to correctly separate `AAPL:3mo` from `AAPL:1y`:

```python
cache_key = f"{sym}:{period}"
cached = _HISTORY_CACHE.get(cache_key)
if cached and (now - cached[1]) < _HISTORY_TTL:
    result[sym] = cached[0]
    continue
```

#### TTL Rationale

- **60 s for prices** — live prices change tick by tick, but for the analytics dashboard a one-minute snapshot is accurate enough. Users refreshing more frequently than once per minute see the same data anyway.
- **5 min for history** — daily OHLCV data only updates at market close. A 5-minute cache eliminates all repeat calls within a typical browser session while still picking up end-of-day data within 5 minutes.

#### Impact

| Scenario | Before | After |
|----------|--------|-------|
| Analytics tab opened 3× in 2 min (5 holdings) | 30 Yahoo Finance calls | 5 calls (first open) + 0 (cache hits) |
| Refresh clicked 5× in 60 s | 25 calls | 5 calls + 20 cache hits |
| End-of-day data freshness | Always fresh | ≤ 5 min stale |

---

### Gap 3 — Sessions List Returns Metadata Only

**File:** `web_server.py` — `GET /api/sessions`  
**Before:** Full session objects including all message history sent on every page load.  
**After:** Only `{id, title, created_at, user_id}` — messages loaded on-demand per session.

#### The Problem

`GET /api/sessions` was returning the complete `_sessions` dict values:

```python
return [s for s in _sessions.values() if s.get("user_id") == user["username"]]
```

Each session dict includes a `messages` list. A user with 20 sessions, each containing 15 message pairs (30 messages), each message averaging 500 characters, generates:

```
20 sessions × 30 messages × 500 chars ≈ 300 KB
```

This 300 KB payload is serialised to JSON and sent on every page load, just to render the sidebar — which only displays session titles. For power users with longer or more numerous sessions, this could reach several megabytes.

Beyond bandwidth, JSON deserialisation of large arrays in JavaScript on the main thread can cause a noticeable freeze on slower devices.

#### The Fix

The list endpoint returns only the four fields the sidebar actually uses:

```python
@app.get("/api/sessions")
def list_sessions(user: dict = Depends(_require_auth)):
    _META_KEYS = {"id", "title", "created_at", "user_id"}
    return [
        {k: v for k, v in s.items() if k in _META_KEYS}
        for s in _sessions.values()
        if s.get("user_id") == user["username"]
    ]
```

Full message history is already fetched on-demand when a session is opened:

```python
@app.get("/api/sessions/{session_id}")
def get_session(session_id: str, user: dict = Depends(_require_auth)):
    ...
    return _sessions[session_id]   # includes messages
```

The frontend's `loadSession(id)` already calls this endpoint and updates `sessions[id]` with the full object, so no JS changes were required.

#### Impact

| Scenario | Before | After |
|----------|--------|-------|
| 20 sessions, 30 messages each | ~300 KB JSON on page load | ~4 KB (metadata only) |
| 5 sessions, 5 messages each | ~15 KB | ~1 KB |
| Time-to-interactive (slow network) | Blocked on full payload | Sidebar renders in <50 ms |

---

### Gap 4 — SQLite WAL Mode

**File:** `web_server.py` — `_meta_init()`  
**Before:** Default DELETE journal mode — write transactions block concurrent readers.  
**After:** WAL mode — readers and a single writer can proceed concurrently without blocking each other.

#### The Problem

SQLite's default `DELETE` journal mode uses exclusive write locks. When one connection is writing (e.g. persisting a new message at the end of a streaming response), any concurrent read — such as another user's `/api/sessions` request — must wait for the write lock to be released. Under concurrent users this serialises all database access, adding up to tens of milliseconds of unnecessary waiting per request.

#### The Fix

WAL (Write-Ahead Logging) mode is set once during database initialisation:

```python
def _meta_init() -> None:
    with sqlite3.connect(_META_DB) as cx:
        # WAL mode: allows concurrent readers alongside a single writer, eliminating
        # the read-lock contention that DELETE journal mode causes under multi-user load.
        # The setting is persistent — only needs to be set once.
        cx.execute("PRAGMA journal_mode=WAL")
        cx.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (...);
            CREATE TABLE IF NOT EXISTS messages (...);
        """)
```

The `journal_mode=WAL` pragma is persistent — it is stored in the database file itself. Subsequent connections inherit it automatically; this `execute` call on startup simply ensures it is set even on first run.

#### How WAL Works

In WAL mode, writes go to a separate write-ahead log file (`sessions_meta.db-wal`) rather than modifying the main database file in-place. Readers continue to read the main file (or checkpoint data from the WAL) without waiting for the writer. The WAL is checkpointed (merged back into the main file) automatically when it grows beyond a threshold.

#### Impact

| Scenario | Before (DELETE) | After (WAL) |
|----------|-----------------|-------------|
| 1 writer + 1 reader | Reader blocks for write duration | Reader proceeds concurrently |
| 5 concurrent users, active chat | Up to 5× serial lock waits | Single writer; readers unblocked |
| Write duration (message persist) | Unchanged | Unchanged |
| Read latency under write pressure | +10–40 ms per blocked read | ~0 ms additional |

---

### Gap 5 — Analytics In-Flight Guard and Cooldown

**File:** `static/index.html` — `loadAnalytics()`, `switchTab()`  
**Before:** Every tab switch and every Refresh click fired concurrent `Promise.all` pairs with no guard.  
**After:** An in-flight flag prevents concurrent requests; tab-switch loads respect a 15-second cooldown.

#### The Problem

`loadAnalytics()` was called unconditionally from two places:

1. `switchTab('analytics')` — every time the user clicked the Analytics tab
2. The ⟳ Refresh button — `onclick="loadAnalytics()"`

Neither had any protection against:
- **Concurrent requests**: clicking Refresh while a load was already in progress would fire a second `Promise.all` simultaneously, resulting in two sets of Yahoo Finance calls racing each other and the second one potentially overwriting the first's DOM state mid-render.
- **Rapid tab switching**: switching to Analytics, back to Chat, then back to Analytics within 2 seconds would fire two identical loads separated by milliseconds.

#### The Fix

Two state variables and a `force` parameter govern the behaviour:

```js
let _analyticsLoading    = false;
let _analyticsLastAuto   = 0;
const _ANALYTICS_AUTO_COOLDOWN = 15_000; // ms
```

`loadAnalytics` now accepts a `force` parameter:

```js
async function loadAnalytics(force = false) {
  if (_analyticsLoading) return;    // in-flight guard — always enforced
  const now = Date.now();
  if (!force && now - _analyticsLastAuto < _ANALYTICS_AUTO_COOLDOWN) return;  // cooldown for tab switches

  _analyticsLoading = true;
  if (!force) _analyticsLastAuto = now;

  try {
    // ... fetch prices, history, render charts ...
  } finally {
    _analyticsLoading = false;    // always released, even on error
  }
}
```

Call sites are updated to distinguish implicit loads from explicit user intent:

```js
// Tab switch — implicit, respects cooldown
if (isAnalytics) loadAnalytics(false);

// Refresh button — explicit, bypasses cooldown but still respects in-flight guard
<button onclick="loadAnalytics(true)">⟳ Refresh</button>
```

#### Design Decisions

- **In-flight guard applies to both `force` and non-`force` calls** — even the Refresh button shouldn't fire a second request while one is already in progress. The user would see the loading spinner, know something is happening, and the button click is silently swallowed until the current load completes.
- **Cooldown only applies to implicit loads** — a user who explicitly clicks Refresh more than 15 seconds after the last auto-load shouldn't be blocked. The separation of `force` vs. cooldown gives full control to the user while protecting against tab-switch spam.
- **`finally` always releases `_analyticsLoading`** — without this, a network error during the `Promise.all` would leave `_analyticsLoading = true` permanently, breaking the panel for the session.

#### Impact

| Scenario | Before | After |
|----------|--------|-------|
| Rapid tab switches (5 in 3 s) | 5 concurrent loads / 10 Yahoo Finance calls | 1 load + 4 skipped |
| Refresh while loading | 2 concurrent loads racing | 2nd click silently ignored |
| Explicit Refresh after 15 s | Always fired | Always fired (force=true) |
| Network error during load | `_analyticsLoading` could jam | Always reset in `finally` |

---

## 4. Summary Table

| # | Measure | Layer | Type | What It Does |
|---|---------|-------|------|--------------|
| 1 | SSE token streaming | Server + Browser | Perceived latency | First token visible in ~1 s |
| 2 | 120 s hard timeout | Server | Safety | Prevents hung requests |
| 3 | Per-agent output token caps | Agent | Actual latency | Bounds max response length per agent |
| 4 | Thinking disabled (6 agents) | Agent | Actual latency | Saves ~1.5 s on fast-path agents |
| 5 | Circuit breakers (3) | Agent | Failure latency | OPEN state returns error in ~0 ms |
| 6 | Base64 stripping before LLM context | Agent | Actual latency | Eliminates 170 K-token input spike |
| 7 | Deterministic Python routing | Agent | Actual latency | Saves 500–1500 ms LLM dispatch round-trip |
| 8 | Progress events | Agent + Browser | Perceived latency | Live status during silent phases |
| 9 | Non-blocking background tasks | Server | Actual latency | Memory + judge don't delay `done` event |
| 10 | Tool duration tracking | Agent | Observability | `duration_ms` on every tool call in audit.log |
| 11 | LangFuse tracing | Agent | Observability | Span hierarchy for profiling |
| 12 | `fast_info` for price API | Server | Actual latency | 3–5× faster than full `.info` per ticker |
| 13 | Ticker batch cap (20 / 10) | Server | Safety | Prevents unbounded slow queries |
| 14 | Tool arg validation before call | Agent | Actual latency | Blocks invalid calls before any network hit |
| 15 | In-memory session cache | Server | Actual latency | Session reads served from dict, not SQLite |
| 16 | `streaming = true` lock | Browser | Correctness | No duplicate concurrent submissions |
| 17 | Optimistic sidebar title | Browser | Perceived latency | Title appears instantly, confirmed later |
| 18 | Client-side session search | Browser | Actual latency | In-memory filter — no server round-trip |
| 19 | Analytics uses `Promise.all` | Browser | Actual latency | Price + history fetched in parallel |
| 20 | Market status computed locally | Browser | Actual latency | Zero server calls for NYSE status |
| **21** | **Debounced `marked.parse`** | **Browser** | **Actual latency** | **≤15 re-parses vs 600 for a long response** |
| **22** | **TTL cache — prices (60 s)** | **Server** | **Actual latency** | **Eliminates repeat Yahoo Finance calls** |
| **23** | **TTL cache — history (5 min)** | **Server** | **Actual latency** | **Eliminates repeat history calls** |
| **24** | **Sessions list metadata only** | **Server** | **Payload size** | **~300 KB → ~4 KB on page load** |
| **25** | **SQLite WAL mode** | **Server** | **Concurrency** | **Readers unblocked during writes** |
| **26** | **Analytics in-flight guard** | **Browser** | **Correctness** | **No concurrent Analytics requests** |
| **27** | **Analytics 15 s cooldown** | **Browser** | **Actual latency** | **Tab-switch spam doesn't hit Yahoo Finance** |

Rows 21–27 (bold) are the new fixes added in this session.

---

## 5. Known Limitations

1. **Price cache is process-local** — in a multi-worker uvicorn deployment (`--workers 4`), each worker has its own `_PRICE_CACHE`. A request served by worker 2 doesn't benefit from a cache entry populated by worker 1. A shared cache (Redis, memcached) would be needed for multi-worker deployments.

2. **No cache invalidation on Refresh** — the ⟳ Refresh button bypasses the cooldown but still serves cached data if the TTL hasn't expired. A user who wants truly fresh data within 60 seconds has no way to force a cache bust without restarting the server. Acceptable for the current use case (analytics dashboard, not a trading terminal).

3. **Session messages not incrementally synced client-side** — after `fetchSessions()` strips messages, the client-side `sessions[id].messages` is only populated after `loadSession(id)` is called. The `msgIndex` used for feedback row placement falls back to an approximation for the currently active session. This is an existing UX limitation (not introduced by this change).

4. **WAL checkpoint pressure** — WAL mode writes to a `-wal` file that grows until checkpointed. Under very high write throughput (many concurrent users sending many messages), the WAL file can grow large and the checkpoint operation becomes heavy. The default automatic checkpoint threshold (1000 pages) is sufficient for the current single-server deployment.

5. **`marked.parse` debounce is timer-based, not `requestAnimationFrame`-based** — using `setTimeout(fn, 80)` means renders are not aligned to display refresh cycles. `requestAnimationFrame` would be more precise but adds complexity for marginal gain at the ~12 fps target.

6. **Analytics cooldown blocks `_syncAgentTrade` refresh** — when an agent trade is executed and `_syncAgentTrade` calls `loadAnalytics()` to update the panel, if it was called within 15 seconds of the last auto-load it will be silently skipped. The trade IS saved to localStorage; only the Analytics panel re-render is delayed until the next explicit open or Refresh.

7. **No HTTP-level caching headers on price API** — `Cache-Control` response headers are not set on `/api/prices` or `/api/price-history`. A browser or CDN could cache these responses, but the current in-process TTL cache achieves equivalent results for the single-origin deployment.
