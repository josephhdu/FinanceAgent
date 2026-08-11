# Technology Stack

**Version:** 1.0  
**Date:** 2026-05-07  
**Scope:** Every library and protocol used in FinanceAI — what it is, why it was chosen, and which product features it directly enables.

---

## Table of Contents

1. [Stack Overview](#1-stack-overview)
2. [Technology → Feature Mapping](#2-technology--feature-mapping)
   - [AI & Agent Layer](#21-ai--agent-layer)
   - [Data & Finance Layer](#22-data--finance-layer)
   - [RAG & Memory Layer](#23-rag--memory-layer)
   - [Web Server & API Layer](#24-web-server--api-layer)
   - [Auth & Security Layer](#25-auth--security-layer)
   - [Visualisation & Export Layer](#26-visualisation--export-layer)
   - [Observability & Evaluation Layer](#27-observability--evaluation-layer)
   - [Frontend Layer](#28-frontend-layer)
3. [Feature → Technology Mapping](#3-feature--technology-mapping)
4. [Dependency Graph](#4-dependency-graph)

---

## 1. Stack Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│  Browser  (index.html)                                              │
│  marked.js · Chart.js · SSE reader · localStorage · vanilla JS     │
└────────────────────────────┬────────────────────────────────────────┘
                             │  HTTP / SSE
┌────────────────────────────▼────────────────────────────────────────┐
│  Web Server  (FastAPI + uvicorn)                                    │
│  JWT auth · RBAC · TTL cache · SQLite WAL · SSE streaming          │
└────────────────────────────┬────────────────────────────────────────┘
                             │  Python calls
┌────────────────────────────▼────────────────────────────────────────┐
│  Agent Orchestrator  (Google ADK)                                   │
│  Gemini 2.5 Flash · Python routing · Circuit breakers · LangFuse   │
└──┬──────────────┬──────────────┬──────────────┬─────────────────────┘
   │ MCP          │ A2A          │ Direct       │ Direct
   ▼              ▼              ▼              ▼
Yahoo Finance  Financial     ChromaDB      LightRAG
FastMCP server Report A2A    (10-K RAG     (Knowledge
               server        + memory)     graph)
```

---

## 2. Technology → Feature Mapping

### 2.1 AI & Agent Layer

---

#### Google Gemini 2.5 Flash
**Package:** `google-genai >= 1.74.0`  
**What it is:** Anthropic-class multimodal LLM with extended thinking mode, available via Google's GenAI API.  
**Why chosen:** Best-in-class price/performance for financial reasoning tasks; supports thinking budget control (set to 0 on fast-path agents to save latency); single model across all agents avoids versioning complexity.

| Feature | How Gemini enables it |
|---------|----------------------|
| Natural language stock queries | Understands free-form questions like "Is Apple a good trade?" |
| Intent classification | `intent_agent` parses user query into structured JSON (intent, tickers, confidence) |
| Financial report analysis | `financial_report_agent` synthesises P&L, balance sheet, cash flow into plain English |
| 10-K annual report Q&A | `tenk_agent` reasons over retrieved SEC passages and cites them |
| 2-week price forecast | `prediction_agent` interprets OLS regression output and writes the forecast narrative |
| Trading signal reasoning | `trading_agent` synthesises analyst consensus + OLS signal into a BUY/SELL/HOLD verdict |
| Stock comparison insights | `comparison_insights_agent` cross-references multiple tickers across time horizons |
| Investment research | `investment_research_agent` reasons over LightRAG knowledge graph results |
| Chart captions | `visualization_agent` writes a one-sentence caption for every rendered chart |
| PDF narrative | `pdf_agent` writes the prose sections of the downloadable report |
| Context drift detection | Orchestrator prompts Gemini to flag when company context shifts mid-conversation |
| Jargon glossary | Per-agent prompts instruct Gemini to define financial terms on first use |

---

#### Google ADK (Agent Development Kit)
**Package:** `google-adk >= 1.32.0`  
**What it is:** Google's open-source SDK for building multi-agent systems on top of Gemini. Provides `BaseAgent`, `Runner`, `InvocationContext`, session services, callbacks, and tool calling.  
**Why chosen:** Native integration with Gemini; provides `SqliteSessionService` for conversation persistence; callback system (`before_model_callback`, `after_tool_callback`, etc.) enables clean cross-cutting concerns without modifying agent logic.

| Feature | How ADK enables it |
|---------|-------------------|
| Multi-agent pipeline | `Runner.run_async()` executes sequential agent pipelines; `_ROUTE_MAP` dispatches deterministically |
| Conversation memory (per session) | `SqliteSessionService` persists all message turns to `sessions.db` |
| Tool calling | Native function-calling loop; agents call `get_trade_signals`, `search_10k`, etc. |
| Streaming responses | `async for event in runner.run_async()` yields token-by-token events |
| Callbacks (audit, RBAC, tracing) | `before_model_callback`, `after_tool_callback`, `before_agent_callback` hooks |
| Session state | `ctx.session.state` stores pipeline name, anchor companies, pending trades |
| Cross-session memory | `ChromaMemoryService` (implements ADK's `BaseMemoryService`) injected into `Runner` |
| Agent-to-agent (A2A) | `to_a2a()` wraps `financial_report_agent` as an independent HTTP service |

---

#### A2A SDK (Agent-to-Agent)
**Package:** `a2a-sdk >= 0.3.0`  
**What it is:** Google's A2A protocol implementation — a standard for one agent to call another agent over HTTP.  
**Why chosen:** Allows `financial_report_agent` to run as a completely independent process, keeping PDF compilation concerns isolated from the main orchestrator.

| Feature | How A2A enables it |
|---------|-------------------|
| PDF report generation | `pdf_agent` calls `financial_report_agent` via A2A (`http://localhost:8001`) to get the financial summary, then compiles it into a PDF |
| Service isolation | Financial report server can be deployed, scaled, or restarted independently |
| Agent card discovery | `/.well-known/agent-card.json` lets clients discover the agent's capabilities |

---

#### MCP (Model Context Protocol)
**Package:** `mcp >= 1.27.0`  
**What it is:** Anthropic's open protocol for connecting LLMs to external tools via a standardised JSON-RPC interface.  
**Why chosen:** Decouples tool implementation from agent logic; tools can be tested or replaced independently; ADK has native MCP support.

| Feature | How MCP enables it |
|---------|-------------------|
| Live stock prices | `get-ticker-info` tool on Yahoo Finance MCP server |
| Price history charts | `get-price-history` tool returns OHLCV data |
| Earnings data | `ticker-earning` tool returns EPS, PE, upcoming dates |
| 10-K passage search | `rag_mcp_server.py` exposes `search_10k` over MCP |
| Tool isolation | Each MCP server runs as a subprocess; failures don't crash the main process |

---

#### FastMCP
**Package:** `fastmcp >= 3.2.0`  
**What it is:** A Python framework for building MCP servers, analogous to FastAPI for HTTP APIs.  
**Why chosen:** Minimal boilerplate for defining MCP tools; used internally by ADK; consistent with the rest of the stack.

| Feature | How FastMCP enables it |
|---------|----------------------|
| Yahoo Finance MCP server | `finance_mcp_server.py` exposes 3 tools via `FastMCP("finance-mcp-server")` |
| RAG MCP server | `rag_mcp_server.py` exposes `search_10k` with semantic search |

---

### 2.2 Data & Finance Layer

---

#### yfinance
**Package:** `yfinance >= 1.3.0`  
**What it is:** Unofficial Python wrapper for Yahoo Finance — downloads prices, financials, earnings, company info.  
**Why chosen:** Free, no API key required, covers all software/tech stocks in scope; `fast_info` property provides low-latency live prices.

| Feature | How yfinance enables it |
|---------|------------------------|
| Live price card | `fast_info.last_price`, `fast_info.previous_close` |
| 2-week OLS forecast | `Ticker.history(period="3mo")` provides closing prices for regression |
| Price history charts | `Ticker.history(period=...)` returns OHLCV DataFrame |
| Financial report | `Ticker.financials`, `Ticker.balance_sheet`, `Ticker.cashflow` |
| Earnings analysis | `Ticker.earnings_dates`, `Ticker.info["trailingEps"]` |
| Drop alerts | `Ticker.history(period="5d")` compared against threshold |
| PDF report | `Ticker.fast_info` + `Ticker.info` combined into report sections |
| Trading signals | `Ticker.history()` feeds OLS signal computation; `Ticker.info` provides analyst data |
| Portfolio Analytics | `/api/prices` and `/api/price-history` both use yfinance under the hood |

---

#### pandas
**Package:** `pandas >= 2.3.0`  
**What it is:** DataFrame library for tabular data manipulation.  
**Why chosen:** yfinance returns DataFrames; all time-series operations (resampling, merging, forward-fill) use pandas.

| Feature | How pandas enables it |
|---------|----------------------|
| Price history processing | DataFrame indexing, `resample`, `ffill` for OHLCV data |
| Earnings table formatting | `to_dict()` serialisation for LLM context |
| Financial statement parsing | Row extraction from `Ticker.financials` DataFrame |
| MCP server data shaping | `pd.to_datetime`, `.index` operations in `finance_mcp_server.py` |

---

#### numpy
**Package:** `numpy >= 2.4.0`  
**What it is:** Numerical computing library for Python.

| Feature | How numpy enables it |
|---------|---------------------|
| OLS regression | Array operations for slope/intercept computation in `tools.py` |
| Chart data preparation | Array math for chart datasets in `visualization_tools.py` |
| Signal score normalisation | `np.clip`, `np.nan_to_num` in `trade_tools.py` |

---

#### scipy
**Package:** `scipy >= 1.17.0`  
**What it is:** Scientific computing library built on numpy.

| Feature | How scipy enables it |
|---------|---------------------|
| Forecast confidence bands | `scipy.stats.t.ppf` for t-distribution confidence intervals on OLS residuals |
| R² significance testing | Statistical tests for forecast reliability score |

---

### 2.3 RAG & Memory Layer

---

#### ChromaDB
**Package:** `chromadb >= 1.5.0`  
**What it is:** Open-source vector database with persistent local storage. Used in two separate instances for two distinct purposes.  
**Why chosen:** Runs fully in-process with no external server; `PersistentClient` stores embeddings on disk; supports custom embedding functions.

**Instance 1 — 10-K SEC Filing RAG** (`data/10k_chroma/`)

| Feature | How ChromaDB enables it |
|---------|------------------------|
| 10-K annual report Q&A | `search_10k` queries `sec_10k` collection by semantic similarity |
| Passage citation | Retrieved passages carry `form`, `ticker`, `section` metadata |
| Cross-section analysis | Multiple passages retrieved and ranked before LLM synthesis |

**Instance 2 — Cross-session Conversation Memory** (`memory_db/`)

| Feature | How ChromaDB enables it |
|---------|------------------------|
| Cross-session recall | Stores past Q&A turn embeddings in `agent_memory` collection |
| Context injection | Top-4 semantically similar past turns injected before each pipeline run |
| Personalisation | User-specific memory enables contextually relevant follow-up responses |

---

#### sentence-transformers (all-MiniLM-L6-v2)
**Package:** `sentence-transformers >= 5.4.0`  
**What it is:** Lightweight BERT-based sentence embedding model running locally.  
**Why chosen:** No API cost; fast inference for 10-K chunk queries; 384-dimension embeddings sufficient for document similarity.

| Feature | How sentence-transformers enables it |
|---------|-------------------------------------|
| 10-K semantic search | Embeds both stored chunks and user query for cosine similarity ranking |
| Passage retrieval for `tenk_agent` | Ranks SEC filing passages by relevance to the question |

---

#### Gemini Embedding (gemini-embedding-001)
**Package:** `google-genai` (same SDK as Gemini LLM)  
**What it is:** Google's 768-dimension text embedding model via the GenAI API.  
**Why chosen:** Higher semantic quality than MiniLM for conversational turns; used where accuracy matters more than cost (memory has low call frequency).

| Feature | How Gemini Embedding enables it |
|---------|--------------------------------|
| Cross-session memory recall | Embeds conversation turns stored in `memory_db/` ChromaDB |
| Semantic user query matching | Embeds incoming query to find similar past conversations |

---

#### LightRAG + RAG-Anything
**Package:** `lightrag-hku >= 1.4.0`, `raganything >= 1.2.0`  
**What it is:** LightRAG is a knowledge graph + vector hybrid RAG framework. RAG-Anything extends it with multimodal document ingestion (tables, charts, prose).  
**Why chosen:** Unlike pure vector search (ChromaDB), LightRAG builds a knowledge graph of entities and relationships, enabling cross-document and cross-section queries that vector similarity alone cannot answer.

| Feature | How LightRAG enables it |
|---------|------------------------|
| Investment research — cross-filing trend analysis | Queries knowledge graph for how a concept (e.g. "AI strategy") evolved across multiple 10-K/10-Q filings |
| Cross-section analysis | Finds contradictions or alignments between MD&A narrative and financial tables |
| Entity tracing | Traces a specific term (e.g. "operating leverage") across all ingested documents |
| Multimodal document understanding | RAG-Anything parses tables and charts from PDFs alongside prose |
| Hybrid retrieval modes | `local`, `global`, `hybrid`, `naive`, `mix` modes selectable per query type |

---

#### beautifulsoup4 + lxml
**Package:** `beautifulsoup4 >= 4.14.0`, `lxml >= 6.1.0`  
**What it is:** HTML/XML parsing libraries.

| Feature | How bs4/lxml enables it |
|---------|------------------------|
| SEC filing ingestion | Parses EDGAR HTML filings to extract text before chunking into ChromaDB |
| Table extraction | `lxml` parses financial tables from annual report HTML for RAG-Anything ingestion |

---

### 2.4 Web Server & API Layer

---

#### FastAPI
**Package:** `fastapi >= 0.136.0`  
**What it is:** Modern async Python web framework with automatic OpenAPI docs, Pydantic validation, and dependency injection.  
**Why chosen:** First-class `StreamingResponse` for SSE; async route handlers integrate naturally with ADK's async runner; Pydantic models for all request validation; `Depends()` for clean auth injection.

| Feature | How FastAPI enables it |
|---------|----------------------|
| SSE token streaming | `StreamingResponse` with `media_type="text/event-stream"` |
| REST API for sessions, chat, auth | `@app.get/post/patch/delete` route decorators |
| JWT auth injection | `Depends(_require_auth)` on every protected route |
| Request validation | Pydantic models (`ChatRequest`, `LoginRequest`, `FeedbackRequest`, `RenameRequest`) |
| Global error handling | `@app.exception_handler(Exception)` returns clean 500 JSON |
| Health / readiness probes | `/health` and `/ready` endpoints for deployment monitoring |
| File download | `FileResponse` with path-traversal guard for PDF downloads |

---

#### uvicorn
**Package:** `uvicorn >= 0.46.0`  
**What it is:** ASGI server — the production process that runs the FastAPI app.

| Feature | How uvicorn enables it |
|---------|----------------------|
| Async request handling | ASGI protocol handles many concurrent SSE connections without threads |
| Hot reload in dev | `--reload` flag for development |
| Production serving | `--workers N` for multi-process deployment |

---

#### Pydantic
**Package:** `pydantic >= 2.13.0`  
**What it is:** Data validation and serialisation library used by FastAPI.

| Feature | How Pydantic enables it |
|---------|------------------------|
| Chat request validation | `ChatRequest(message: str)` — rejects empty/malformed bodies with 422 |
| Login validation | `LoginRequest(username, password)` |
| Session rename | `RenameRequest(title: str)` with 80-char truncation |
| Feedback recording | `FeedbackRequest(session_id, message_index, vote, comment)` |

---

#### SQLite (stdlib `sqlite3`)
**Package:** Python stdlib  
**What it is:** Embedded relational database. Used for three tables: `sessions`, `messages`, and `users`.  
**Why chosen:** Zero external dependencies; sufficient for single-server deployment; WAL mode handles read concurrency.

| Feature | How SQLite enables it |
|---------|----------------------|
| Session persistence | `sessions` table stores `{id, title, created_at, user_id}` |
| Message history | `messages` table stores all chat turns with role, content, images, citations |
| User accounts | `users` table stores `{username, hashed_pw, role}` |
| Chat history replay | On page load, `_meta_load_all()` restores all sessions into memory |
| Concurrent read access | WAL journal mode allows readers during writes |
| Session rename | `PATCH /api/sessions/{id}` persists new title via `_meta_upsert_session()` |

---

#### httpx
**Package:** `httpx >= 0.28.0`  
**What it is:** Async-capable HTTP client used by ADK internally for A2A calls.

| Feature | How httpx enables it |
|---------|---------------------|
| A2A agent calls | ADK uses httpx to call the `financial_report_agent` A2A server at `localhost:8001` |

---

#### python-dotenv
**Package:** `python-dotenv >= 1.2.0`  
**What it is:** Loads `.env` files into environment variables at startup.

| Feature | How python-dotenv enables it |
|---------|------------------------------|
| API key management | `GOOGLE_API_KEY`, `JWT_SECRET`, `LANGFUSE_PUBLIC_KEY` loaded from `.env` |
| Dev/prod config separation | Different `.env` files per environment without code changes |

---

#### PyYAML
**Package:** stdlib-adjacent (`yaml`)  
**What it is:** YAML parser.

| Feature | How YAML enables it |
|---------|-------------------|
| RBAC configuration | `roles.yaml` declares which intents each role (`admin`, `analyst`, `viewer`) can access |
| Human-readable permissions | Ops team can edit role permissions without touching Python code |

---

### 2.5 Auth & Security Layer

---

#### PyJWT / python-jose
**Package:** `PyJWT >= 2.12.0`, `python-jose >= 3.5.0`  
**What it is:** JWT (JSON Web Token) libraries for creating and verifying signed tokens.  
**Why chosen:** Stateless auth — server doesn't need to store sessions; tokens expire automatically (`JWT_EXPIRY_HOURS=8`); HS256 signing with a configurable secret.

| Feature | How JWT enables it |
|---------|-------------------|
| User login | `create_token(username, role)` → HS256-signed JWT returned to browser |
| API authentication | Every protected endpoint validates Bearer token via `_require_auth` dependency |
| Role propagation | `role` claim in token payload used to enforce RBAC per request |
| Session expiry | `exp` claim causes automatic logout after 8 hours |

---

#### bcrypt
**Package:** `bcrypt` (via `passlib`)  
**What it is:** Adaptive password hashing algorithm designed to be computationally expensive.

| Feature | How bcrypt enables it |
|---------|----------------------|
| Secure password storage | User passwords stored as bcrypt hashes in `users` table, never plaintext |
| Login verification | `bcrypt.checkpw()` used in `verify_user()` |

---

#### RBAC (roles.yaml + `rbac.py`)
**Technology:** Custom Python + YAML  
**What it is:** In-house role-based access control with three roles: `admin`, `analyst`, `viewer`.

| Feature | How RBAC enables it |
|---------|-------------------|
| Feature gating | `viewer` cannot access Trading, Analytics, or PDF export |
| Intent-level control | Each role declares a whitelist of allowed intents in `roles.yaml` |
| UI enforcement | Trading History and Analytics tabs hidden for viewer role |
| API enforcement | `is_allowed(role, intent)` checked in orchestrator before routing |
| Session ownership | Every session/message API endpoint checks `user_id == username` |

---

### 2.6 Visualisation & Export Layer

---

#### matplotlib
**Package:** `matplotlib >= 3.10.0`  
**What it is:** Python plotting library. Runs in headless mode (`matplotlib.use("Agg")`) — renders to PNG in memory, no display required.

| Feature | How matplotlib enables it |
|---------|--------------------------|
| Price history chart | `render_price_chart_for_ticker` — candlestick-style line chart with volume bars |
| Forecast chart | `render_prediction_chart_for_ticker` — actual + projected line + confidence band |
| Comparison chart | `render_comparison_chart_for_tickers` — normalised multi-ticker overlay |
| Financial metrics chart | `render_financial_chart_for_ticker` — bar chart for revenue, EBITDA, margins |
| PDF embedded charts | `pdf_tools.py` uses matplotlib to generate charts embedded inline in the PDF |

---

#### ReportLab
**Package:** `reportlab >= 4.5.0`  
**What it is:** Python library for programmatic PDF generation.

| Feature | How ReportLab enables it |
|---------|-------------------------|
| PDF report download | `pdf_tools.py` compiles a multi-section A4 PDF with cover page, charts, financial tables, and narrative |
| Styled typography | `ParagraphStyle` for section headers, body text, data tables |
| Chart embedding | matplotlib PNGs injected as `Image` flowables |
| Authenticated download | Output saved to `output/` then served via FastAPI `FileResponse` |

---

### 2.7 Observability & Evaluation Layer

---

#### LangFuse
**Package:** `langfuse >= 4.5.0`  
**What it is:** Open-source LLM observability platform. Captures traces, spans, generations, and evaluation scores.

| Feature | How LangFuse enables it |
|---------|------------------------|
| Per-request latency profiling | Trace hierarchy: request → agent span → LLM generation → tool span |
| Token usage tracking | Input/output token counts on every `Generation` |
| Slow tool identification | Tool spans include start/end timestamps |
| LLM-as-judge evaluation | Goal verification scores written as evaluation events |
| Cost monitoring | Token counts + model ID → cost estimate per trace |
| Regression detection | Compare p95 latency before/after a code change in the LangFuse UI |

---

#### RAGAS
**Package:** `ragas >= 0.4.3`  
**What it is:** RAG evaluation framework. Measures faithfulness, answer relevance, context precision, and context recall.

| Feature | How RAGAS enables it |
|---------|---------------------|
| 10-K RAG quality measurement | Evaluates whether `tenk_agent` answers are grounded in retrieved passages |
| Investment research evaluation | Measures context recall for LightRAG queries |
| Regression testing | `eval/` directory runs RAGAS scores against a golden test set |

---

#### langchain-google-genai
**Package:** `langchain-google-genai >= 4.2.0`  
**What it is:** LangChain adapter for Gemini, used exclusively as an evaluation harness.

| Feature | How it enables it |
|---------|-----------------|
| RAGAS evaluation | RAGAS uses LangChain LLM interfaces internally; this adapter bridges to Gemini |

---

#### Audit logging (`audit.py`)
**Technology:** Python `logging.handlers.TimedRotatingFileHandler` + JSONL  
**What it is:** Custom structured logging to `audit.log` with daily rotation, 90-day retention, and gzip compression.

| Feature | How audit logging enables it |
|---------|------------------------------|
| Compliance trail | Every agent start/end, tool call, LLM request/response written as JSON line |
| Tool latency tracking | `duration_ms` on every `tool_end` event |
| Disclaimer enforcement | `disclaimer` field records whether each financial response included required disclosure |
| Security monitoring | `tool_injection_attempt` events flagged when tool responses contain injection patterns |
| Cost accounting | `cost.jsonl` records per-agent token counts and USD cost estimates |
| Spend alerts | `spend_alert.py` reads `cost.jsonl` and warns if monthly spend exceeds threshold |

---

### 2.8 Frontend Layer

---

#### marked.js
**CDN:** `cdn.jsdelivr.net/npm/marked@12/marked.min.js`  
**What it is:** Fast Markdown-to-HTML parser for the browser.

| Feature | How marked.js enables it |
|---------|--------------------------|
| Formatted agent responses | LLM output (tables, bold text, code blocks, lists) rendered as HTML |
| Chart embedding | Base64 PNG image tags in markdown rendered as `<img>` elements |
| Citation snippets | Markdown bold and inline code in citation chips |
| Debounced token render | `marked.parse(accText)` called at most once per 80 ms frame (Gap 1 fix) |

---

#### Chart.js
**CDN:** `cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js`  
**What it is:** Canvas-based charting library for the browser.

| Feature | How Chart.js enables it |
|---------|------------------------|
| Portfolio allocation donut chart | Analytics tab — doughnut chart of holdings vs. cash |
| Portfolio value trend line | 3-month portfolio value over time (line chart) |
| Individual stock trends | Multi-ticker line chart in Analytics tab |

---

#### localStorage
**Technology:** Browser Web Storage API  
**What it is:** Client-side key-value persistence. Used for trade history and UI preferences.

| Feature | How localStorage enables it |
|---------|----------------------------|
| Trade history persistence | All mock trades stored as JSON under `trades_{username}` key |
| Portfolio analytics | Trade data read from localStorage to compute positions, P&L |
| Sidebar width preference | Persisted across page reloads |
| Sidebar collapse state | Persisted across page reloads |
| JWT token | Auth token stored and read on every API call |

---

#### SSE (Server-Sent Events)
**Technology:** Browser `EventSource` / `fetch + ReadableStream` + FastAPI `StreamingResponse`  
**What it is:** A unidirectional HTTP streaming protocol. The server pushes events; the client reads them incrementally.

| Feature | How SSE enables it |
|---------|------------------|
| Token-by-token streaming | `token` events render text progressively as Gemini generates it |
| Progress indicators | `progress` events update the status line during silent processing |
| Chart injection | `image` events deliver base64 PNGs before the text response |
| Trade signal badges | `signal` events render the BUY/SELL/HOLD badge before the narrative |
| Trade sync | `trade_executed` events synchronise agent trades into localStorage |
| Follow-up chips | `done` event carries `follow_ups` array rendered as clickable suggestions |

---

#### Vanilla JavaScript (ES2022)
**Technology:** No framework  
**Why chosen:** Zero build step; no bundler required; the app is a single `index.html`; modern browser APIs (`fetch`, `ReadableStream`, `navigator.clipboard`, `requestAnimationFrame`, `localStorage`) cover all needs.

| Feature | How JS enables it |
|---------|-----------------|
| Session management | `fetchSessions`, `newSession`, `loadSession`, `deleteSession` |
| Real-time streaming UI | SSE reader loop, incremental DOM updates |
| Markdown debounce | `_scheduleRender` / `_flushRender` (80 ms coalesce) |
| Prompt library | Modal with category chips, search filter, ticker substitution |
| Analytics dashboard | Position computation, P&L calculation, chart rendering |
| Session rename | Inline `<input>` with optimistic update + `PATCH` API call |
| Keyboard shortcuts | Global `keydown` listener (`Ctrl+K`, `Escape`, `Ctrl+N`) |
| Mobile sidebar | CSS `translateX` toggle + overlay tap-to-close |
| Copy to clipboard | `navigator.clipboard.writeText` on raw markdown |
| Scroll-to-bottom button | Scroll event listener with 180 px threshold |
| Analytics rate-limit | In-flight guard + 15 s cooldown on tab-switch loads |

---

## 3. Feature → Technology Mapping

| Feature | Technologies |
|---------|-------------|
| **Natural language query understanding** | Gemini 2.5 Flash, Google ADK |
| **Live stock price** | yfinance (`fast_info`), FastMCP, Gemini |
| **2-week price forecast** | yfinance (history), numpy/scipy (OLS + R²), Gemini, ADK |
| **Price history chart** | yfinance, matplotlib, SSE (`image` event), marked.js |
| **Forecast chart** | yfinance, numpy, matplotlib, SSE |
| **Financial report (P&L, balance sheet, cash flow)** | yfinance, pandas, Gemini, ADK |
| **10-K annual report Q&A** | SEC EDGAR (via ingestion), ChromaDB, sentence-transformers, FastMCP, Gemini |
| **Investment research (cross-filing)** | LightRAG, RAG-Anything, lxml, bs4, Gemini |
| **Stock comparison** | yfinance, pandas, matplotlib, Gemini |
| **Drop alerts** | yfinance, Gemini |
| **Trading signals (BUY/SELL/HOLD)** | yfinance, numpy, Gemini |
| **Mock paper trading** | In-memory trade store, Gemini, ADK session state |
| **Portfolio analytics dashboard** | yfinance (`/api/prices`, `/api/price-history`), Chart.js, localStorage |
| **PDF report export** | yfinance, matplotlib, ReportLab, A2A SDK, FastAPI `FileResponse` |
| **Chart captions** | Gemini, matplotlib |
| **User login / logout** | bcrypt, python-jose, FastAPI, SQLite |
| **Role-based access control** | RBAC (`roles.yaml`), JWT, FastAPI `Depends` |
| **Session persistence** | SQLite (WAL), ADK `SqliteSessionService` |
| **Cross-session memory** | ChromaDB (`memory_db`), gemini-embedding-001, ADK `BaseMemoryService` |
| **Streaming responses** | FastAPI `StreamingResponse`, uvicorn, SSE, Google ADK |
| **Token streaming in browser** | SSE reader, marked.js (debounced), vanilla JS |
| **Progress indicators** | ADK custom events (`__progress__` author), SSE |
| **Follow-up suggestions** | ADK session state (`pipeline` key), SSE `done` event, vanilla JS chips |
| **Session rename** | FastAPI `PATCH`, SQLite, vanilla JS inline input |
| **Prompt library** | vanilla JS, localStorage (sidebar width), zero backend |
| **Session search** | vanilla JS (in-memory filter), zero backend |
| **Mobile layout** | CSS media queries, vanilla JS sidebar toggle |
| **Copy to clipboard** | `navigator.clipboard` API |
| **Keyboard shortcuts** | vanilla JS `keydown` listener |
| **Latency observability** | LangFuse, audit.py (`time.perf_counter`), JSONL logging |
| **RAG quality evaluation** | RAGAS, langchain-google-genai, Gemini |
| **Spend / cost monitoring** | audit.py, `cost.jsonl`, `spend_alert.py` |
| **Injection defence** | audit.py (`after_tool_callback` pattern scan) |
| **Financial disclaimer enforcement** | audit.py (`_check_disclaimer`), agent prompts |
| **Circuit breaking** | `circuit_breaker.py` (custom CLOSED/OPEN/HALF_OPEN) |
| **Price data caching** | `_PRICE_CACHE`, `_HISTORY_CACHE` (in-process TTL dicts) |

---

## 4. Dependency Graph

The diagram below shows which technologies depend on each other to deliver the most complex feature — the **Investment Research pipeline**:

```
User query
    │
    ▼
Gemini 2.5 Flash (intent_agent)
    │  JSON: intent=INVESTMENT_RESEARCH, ticker=MSFT
    ▼
Google ADK (orchestrator) ──────────────────────► LangFuse (trace)
    │
    ▼
investment_research_agent (Gemini 2.5 Flash)
    │
    ├─► query_investment_research()
    │       │
    │       ▼
    │   LightRAG (hybrid mode)
    │       │
    │       ├─► knowledge graph traversal  ──► LightRAG storage (files)
    │       └─► vector similarity search   ──► ChromaDB (investment_research)
    │                                              └─► gemini-embedding-001
    │
    └─► response narrative (Gemini reasoning over retrieved passages)
            │
            ▼
        SSE stream (FastAPI + uvicorn)
            │
            ▼
        marked.js (browser) → rendered HTML
```

And the **PDF Report pipeline** (most technology touchpoints):

```
User: "Generate a PDF report for AAPL"
    │
Gemini intent_agent → PDF_REPORT
    │
pdf_agent (Gemini)
    │
    ├─► A2A call → financial_report_agent (separate process)
    │       │         └─► yfinance + pandas → P&L, balance sheet
    │       │         └─► Gemini → narrative synthesis
    │       ▼
    │   financial summary (text)
    │
    ├─► yfinance (direct) → price history, key metrics
    ├─► matplotlib → 3 embedded charts (PNG)
    └─► ReportLab → A4 PDF assembly
            │
            ▼
        output/AAPL_report_YYYYMMDD.pdf
            │
            ▼
        FastAPI FileResponse (with path-traversal guard)
            │
            ▼
        Browser download (Blob URL via fetch + JWT auth header)
```
