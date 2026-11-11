# Product Requirements Document — Stock Analysis Agent

**Version:** 8.1  
**Date:** 2026-05-10  
**Status:** Active

---

## Changelog

| Version | Date | Summary |
|---------|------|---------|
| 1.0 | 2026-05-01 | Initial draft |
| 2.0 | 2026-05-02 | Add comparison pipeline, full guardrails system (PII, injection, scope, advice), encrypted PII store, evaluation framework |
| 3.0 | 2026-05-02 | Add web UI (FastAPI + SSE streaming + session history + inline chart rendering) |
| 3.1 | 2026-05-03 | Add prompt versioning, per-agent token budgets, cost tracking, monthly spend alert, compliance audit logging (90-day retention, disclaimer tracking), circuit breakers (Gemini/Yahoo/A2A), RAGAS eval gate |
| 4.0 | 2026-05-03 | Add mock paper trading agent with human-in-the-loop approval, signal scoring, portfolio tracking |
| 4.1 | 2026-05-03 | Add /health and /ready endpoints; user-friendly error message classification |
| 5.0 | 2026-05-03 | FinanceAI brand identity (SVG logo + favicon, tab title); split-screen login with trading-chart photo; per-user session isolation; session deletion (`DELETE /api/sessions/{id}`); resizable sidebar; session keyword search with match highlighting; sign-out footer with avatar and role; client-side Trading History tab |
| 5.1 | 2026-05-03 | Analytics tab: summary cards, asset-allocation doughnut chart, holdings table, per-stock price cards, portfolio value trend area chart, individual stock trend multi-line chart; `GET /api/prices` and `GET /api/price-history` backend endpoints |
| 5.2 | 2026-05-04 | `start.sh` orchestrator launches both web UI and A2A PDF server in one terminal with sequenced startup, port-conflict pre-flight, and trap-based clean shutdown; intent classification gives explicit PDF/export keywords priority 0 (overrides TRADE_ANALYSIS) so queries like "Export AAPL as a PDF" route correctly |
| 5.3 | 2026-05-04 | Smart pending-trade bypass: stale pending trades are auto-cancelled when the user pivots to an unrelated request (PDF / chart / analysis), so `has_pending_trade()` no longer hijacks intent classification; only short approval/cancellation messages ("yes", "buy", "no", "cancel", etc.) still route directly to `trading_agent` |
| 5.4 | 2026-05-04 | Browser-native PDF download: `GET /api/downloads/{filename}` (auth-required, path-traversal-guarded) serves files from `output/`; PDF agent emits a markdown download link; frontend click interceptor fetches with JWT and triggers a real browser download via Blob URL — files land in the user's Downloads folder |
| 6.0 | 2026-05-05 | Switch all agents to `gemini-2.5-flash` with `thinking_budget=0` for cheap-tier agents (replaces gemini-2.0-flash cost strategy); `pdf_agent` refactored to fetch financial data directly via MCP tools (`get-ticker-info`, `ticker-earning`) and build `financial_summary` itself — A2A delegation to `financial_report_agent` removed; alert_agent default watchlist reduced from 10 to 3 stocks (MSFT, NVDA, CRM) to avoid LLM context overflow; RBAC enforced on Trading History and Analytics tabs (analyst/admin only — viewer sees Chat tab only); RBAC check added to orchestrator pending-trade bypass; eval E2E suite expanded from 14 to 17 cases |
| 7.0 | 2026-05-08 | SAP EDGAR filings ingested into LightRAG knowledge graph (10 filings: 3× 20-F annual FY2023–2025 + 7× 6-K quarterly); `update_pending_trade_shares` tool added to `trading_agent` so users can adjust share count before approving a trade; eval E2E suite expanded from 17 to 22 cases (added `e2e_prediction_nvda`, `e2e_pdf_report`, `e2e_visualization_price_chart`, `e2e_comparison_msft_nvda`, `e2e_comparison_three_stocks`); per-case RAGAS thresholds (`factual_correctness`, `answer_relevancy`, `faithfulness`) calibrated against actual tool outputs and added directly to each `E2ECase` in `cases.py`; eval harness bug fixed — `__routing__` events now filtered alongside `__progress__` (routing JSON was leaking into RAGAS-evaluated response text and inflating hallucination scores); ALERT pipeline bug fixed — routing event injects default companies `["MSFT", "NVDA", "CRM"]` when `intent=ALERT` and `companies=[]` (previously produced empty response for sector-level alert queries); RAGAS FC references for financial/RAG cases updated with actual yfinance and 10-K figures; thresholds set to achievable levels based on observed NLI matching behaviour |
| 8.0 | 2026-05-09 | **Market Alert Monitor**: background asyncio task (`alert_monitor.py`) polls all enabled alert configs every 15 minutes; pure-Python condition evaluation (RSI, moving-average, volume-spike, price-move checks) with 4-hour per-ticker cooldown; Gemini Flash content generation fires only on condition match; results persisted to `alert_store.py` (SQLite `alerts.db` — three tables: `alert_configs`, `alert_notifications`, `user_alert_settings`); in-browser SSE delivery via `GET /api/alerts/stream` (JWT via `?token=` query param; EventSource cannot set headers); optional SMTP email delivery (env-var configured); full alert CRUD REST API (`/api/alerts/configs`, `/api/alerts/notifications`, `/api/alerts/settings`, `/api/alerts/monitor-status`); Alerts tab added to web UI (live agent status dashboard, notification log, config panel, settings modal); bell icon with unread badge in chat header; no auto-trade guarantee — alert content describes what happened / why it matters / confidence / next steps only; sub-agent context trim guardrail (`before_model_context_trim_guardrail_with_audit`) applied to all sub-agents — strips accumulated session history before token estimation, eliminating context-limit messages mid-session; TOKEN_LIMIT raised from 20 000 to 120 000 |
| 8.1 | 2026-05-10 | **Alert UX improvements**: (1) "Running Agents" stat card renamed to **Triggers Today** — now shows count of notifications fired in last 24 h, sourced from `summary.triggers_today` in `/api/alerts/monitor-status` response; (2) **Continue in Chat →** button added to alert toast, notification cards, and detail modal — creates a new chat session pre-seeded with a framed draft message that tells the agent the alert has already been confirmed, preventing incorrect re-verification of conditions; draft routes to `investment_research_agent` for analysis or `trading_agent` for trade decisions; (3) alert setup **Tickers to monitor** field replaced from free-text with searchable inline picker — always-visible scrollable list of 80+ common tickers, filters by symbol prefix or company name, selected tickers shown with ✓ checkmark, supports custom tickers; (4) `_fallback_content()` improved — now uses pre-fetched `price_data` and `matched` conditions to generate a factual `what_happened` summary instead of a generic placeholder; `_parse_agent_response` logs raw agent response (up to 300 chars) at WARNING when fallback fires |

---

## 0. Product Vision

> **To be a trustworthy, role-aware AI co-analyst for equity research — turning natural-language questions into auditable, multi-modal answers in a single conversational turn.**

The vision rests on five pillars:

| Pillar | What it means | How we deliver it |
|---|---|---|
| **Conversational depth** | A single question can span price, forecast, fundamentals, charts, and 10-K narrative, and return one coherent answer. | Multi-agent orchestration with 13 intent routes; comparison and investment-research pipelines chain specialists deterministically. |
| **Trustworthy by construction** | Every LLM call is bounded, every action is auditable, and every financial response carries an appropriate disclaimer. | Six-check guardrail system, 90-day rotating audit logs, circuit breakers, disclaimer tracking, RAGAS eval gate. |
| **Role-aware access** | Different users see different capabilities; sessions and data never leak across users. | JWT-authenticated viewer / analyst / admin roles; per-user session isolation in `sessions.db` and `sessions_meta.db`. |
| **Grounded in real data, not hallucination** | Answers are anchored in live market data and primary-source filings, with explicit source citations. | yfinance for live prices; ChromaDB + LightRAG GraphRAG over SEC 10-K / 10-Q filings; per-tool citation capture. |
| **Operator-friendly** | A single browser tab gives a complete research, analytics, paper-trading, and market-monitoring workspace — no broker integration, no real money risk. | Single-page UI with Chat, Trading History, Analytics, and Alerts tabs; mock paper trading with human-in-the-loop approval; client-side trade ledger; background alert monitor with in-app and email notifications. |

**Whom it serves:** individual investors, financial analysts, portfolio managers, academic researchers, and active traders — each persona is mapped to a documented workflow in §2 and §4.

**What it deliberately is *not*:** FinanceAI is **not a broker, not a regulated investment advisor, and not a full-universe research platform**. It is **software-sector focused**, **mock-trading only**, and **explicitly non-advisory**. These boundaries are design choices that keep the trust contract honest and the surface area defensible.

---

## 1. Product Overview

The **FinanceAI** platform is a conversational AI system built on Google's Agent Development Kit (ADK) that delivers on-demand stock intelligence for software-sector equities. Users interact via a browser-based chat interface or terminal CLI. The system classifies their intent, routes to one or more specialist agents, and returns price data, forecasts, financial summaries, charts, PDF reports, 10-K filing answers, multi-stock comparisons, or mock paper trade analysis with human-in-the-loop approval — all in a single turn.

A persistent background alert monitor (`alert_monitor.py`) runs independently of user sessions, polling user-defined market conditions every 15 minutes and delivering notifications in-browser via SSE and optionally via email — without requiring the user to be actively in a session.

The web UI (`web_server.py` + `static/index.html`) streams responses token-by-token over SSE, renders all markdown (tables, code, charts) inline via marked.js, and maintains a session history sidebar for multi-session conversations. It presents a branded identity (FinanceAI logo, favicon, split-screen login) and role-gated access for three user types across four tabs: Chat, Trading History, Analytics, and Alerts.

All six guardrail checks fire at every LLM boundary: prompt injection detection, out-of-scope rejection, PII tokenisation, token limit enforcement (120 000 tokens), PII detokenisation, and inappropriate financial advice detection.

---

## 2. Target Users

| Persona | Primary Need |
|---------|-------------|
| Individual investor | Quick price checks, 2-week forecasts, drop alerts |
| Financial analyst | Structured financial reports, annual filing deep-dives |
| Portfolio manager | Multi-stock comparisons, sector overview charts, PDF exports |
| Researcher / student | 10-K qualitative analysis, combined annual + financial context |
| Active trader | Trade signal analysis, mock trade execution, portfolio tracking |

---

## 3. System Architecture

### 3.1 High-Level Flow

```
User Input  (browser chat UI or terminal CLI)
    │
    ▼
Web Server  (web_server.py — FastAPI + uvicorn, port 8080)
    • Session management (UUID sessions, SQLite-backed)
    • SSE streaming (token / image / done events)
    • Image capture (ContextVar intercepts base64 before audit strips it)
    • Alert API (CRUD configs, notifications, settings, monitor-status)
    • Alert SSE stream (GET /api/alerts/stream — JWT via ?token= param)
    │
    ▼
Guardrails (before_model_callback)
    • Prompt injection detection
    • Out-of-scope rejection
    • PII tokenisation → pii_store.db (Fernet-encrypted)
    • Context trim (sub-agents) — strips accumulated session history
    • Token limit check (> 120 000 → block)
    │
    ▼
GraphOrchestrator  (deterministic Python router — no LLM dispatch)
    │
    ├─ intent_agent  →  JSON: {intent, companies, time_horizon, ...}
    │
    └─ _ROUTE_MAP lookup  →  ordered agent pipeline
           │
           ├─ single-agent routes   (price, prediction, alert, …)
           ├─ multi-agent pipelines (price→predict, price→predict→chart, …)
           └─ comparison pipeline   (comparison_trend → comparison_insights)
    │
    ▼
Guardrails (after_model_callback)
    • PII detokenisation + output re-masking
    • Inappropriate financial advice detection

═══════════════════════════════════════════════════════════
Background (independent of user sessions):

alert_monitor.py  (asyncio task — started at server boot)
    • Polls all enabled alert configs every 15 minutes
    • Evaluates conditions (pure Python: RSI, MA, volume, price-move)
    • On match: Gemini Flash generates alert content
    • Persists notification to alert_store.py (SQLite alerts.db)
    • Pushes SSE event to open browser connections
    • Sends SMTP email if user has email alerts enabled
    • 4-hour per-(config, ticker) cooldown
```

### 3.2 Component Inventory

| Layer | Component | Purpose |
|-------|-----------|---------|
| **Web UI** | `web_server.py` | FastAPI server: per-user session CRUD (create, list, get, delete with ownership check), SSE streaming, image capture callback patching; `GET /health` (liveness) and `GET /ready` (readiness) probes; static file serving (`/static/*`); user-friendly error classification; full alert REST API (`/api/alerts/*`); alert SSE stream (`GET /api/alerts/stream`) |
| | `static/index.html` | Single-page dark chat UI: split-screen login with trading-chart photo; FinanceAI logo + favicon; resizable session sidebar with keyword search and session delete; sign-out footer with avatar and role badge; Chat, Trading History, Analytics, and Alerts tabs; marked.js markdown rendering; SSE client; Alerts tab: live monitor status, agent grid, notification log, alert config CRUD, settings modal, bell badge |
| | `static/logo.svg` | FinanceAI horizontal lockup — blue diamond icon + gold "FinanceAI" wordmark |
| | `static/favicon.svg` | FinanceAI icon-only 48×48 SVG (diamond + trend line, no wordmark) |
| | `static/bull.jpg` | Trading-chart photo used as login background |
| **Analytics** | `GET /api/prices` | Returns current price, daily change $, and change % for a comma-separated list of tickers via yfinance |
| | `GET /api/price-history` | Returns daily closing prices (default 3-month lookback) per ticker for portfolio and stock trend charts |
| **Alert Monitor** | `alert_monitor.py` | Asyncio background task (started at server boot via `asyncio.create_task()`). Poll loop: loads all enabled configs from SQLite every 15 min, evaluates pure-Python conditions per ticker (RSI, MA50, volume-spike, price-move), calls Gemini Flash when a condition fires, persists notification, pushes SSE to all open browser connections, sends SMTP email if enabled. 4-hour per-(config_id, ticker) cooldown tracked in-memory. |
| | `alert_store.py` | SQLite persistence layer (`stock_agent/alerts.db`, WAL mode). Three tables: `alert_configs` (user monitoring rules — name, tickers, alert_type, conditions JSON, enabled flag), `alert_notifications` (triggered records — what_happened, why_it_matters, confidence, next_steps, is_read, email_sent), `user_alert_settings` (notification_email, email_alerts_enabled). Functions: `create/get/update/delete_alert_config`, `create/get_notifications`, `mark_notification_read`, `mark_all_read`, `get_unread_count`, `get/update_user_settings`. |
| **Downloads** | `GET /api/downloads/{filename}` | Streams a generated PDF report from `output/` to the browser as a real download (`Content-Disposition: attachment`); JWT-required; rejects any path component / dotfiles / paths outside `output/` |
| **Orchestration** | `GraphOrchestrator` (BaseAgent) | Deterministic routing via `_ROUTE_MAP` |
| **Intent** | `intent_agent` | LLM classification & entity extraction |
| **Specialists** | `price_agent` | Real-time price & market data |
| | `prediction_agent` | 2-week linear regression forecast |
| | `alert_agent` | Drop-threshold monitoring |
| | `financial_report_agent` | Annual financial metrics summary |
| | `visualization_agent` | Inline chart generation |
| | `pdf_agent` | PDF report compilation (direct MCP tools — no A2A) |
| | `tenk_agent` | RAG over SEC 10-K / 20-F filings |
| | `comparison_trend_agent` | Multi-stock price trend table + comparison chart |
| | `comparison_insights_agent` | Per-company 10-K RAG insights + comparative synthesis |
| | `investment_research_agent` | Multimodal cross-section analysis using LightRAG knowledge graph over SEC filings |
| | `trading_agent` | Trade signal analysis and mock execution with human-in-the-loop approval |
| **Tools** | `tools.py` | `resolve_ticker`, `fetch_and_forecast`, `fetch_price_trends`, `compute_linear_regression_forecast`, `evaluate_drop_alerts` |
| | `visualization_tools.py` | `render_price_chart_for_ticker`, `render_prediction_chart_for_ticker`, `render_comparison_chart_for_tickers`, `render_financial_chart_for_ticker` (one-shot wrappers); `render_price_chart`, `render_comparison_chart`, `render_financial_chart` (underlying renderers) |
| | `pdf_tools.py` | `compile_pdf_report` |
| | `tenk_tools.py` | `search_10k`, `list_indexed_companies` |
| | `trade_tools.py` | `get_trade_signals`, `store/execute/cancel/update_pending_trade`, `get_portfolio`, `get_trade_history`, `update_pending_trade_shares` |
| **Data** | `finance_mcp_server.py` | MCP server wrapping yfinance (`get-ticker-info`, `get-price-history`, `ticker-earning`) |
| | `rag_mcp_server.py` | MCP server exposing ChromaDB vector store for 10-K embeddings |
| | `lightrag_config.py` | Shared LightRAG + RAGAnything instances; Gemini LLM wrapper; `get_lightrag()` lazy initialiser; filing manifest at `lightrag_storage/manifest.jsonl` |
| | `data/10k_chroma/` | ChromaDB `sec_10k` collection — `all-MiniLM-L6-v2` embeddings; 669 chunks for MSFT; used by `tenk_agent` for semantic similarity search |
| | `lightrag_storage/` | LightRAG knowledge graph — entity+relationship graph over SEC filings; MSFT 10-K + SAP 20-F/6-K (FY2023–2025); used by `investment_research_agent` |
| | `trades.jsonl` | Append-only mock trade log; portfolio computed by replaying |
| | `cost.jsonl` | Append-only LLM cost log; one JSON line per response |
| **Safety** | `guardrails.py` | Six-check guardrail system (injection, scope, PII, token limit, output PII, advice) |
| | `pii_store.py` | Encrypted SQLite PII token store (Fernet / AES-128-CBC) |
| | `circuit_breaker.py` | CLOSED→OPEN→HALF_OPEN breakers for Gemini, Yahoo Finance MCP, A2A |
| | `spend_alert.py` | Monthly spend alert at 80%/100% of configurable limit |
| **Observability** | `audit.py` | Structured JSON audit logging via ADK callbacks; daily-rotating 90-day compliant logs, disclaimer tracking, circuit breaker events, cost recording to cost.jsonl |
| | `tracing.py` | LangFuse tracing + in-process metrics collection for eval |
| **Evaluation** | `eval/eval_harness.py` | ADK agent runner + result capture |
| | `eval/metrics.py` | Three-level metrics computation |
| | `eval/langfuse_client.py` | Tool-span and cost extraction from in-process metrics |
| | `eval/run_eval.py` | CLI entry point; outputs JSON + Markdown dashboard |
| | `eval/thresholds.yaml` | Pass/fail thresholds for all 15 metrics |

### 3.3 Model

All agents use **Gemini 2.5 Flash** (`gemini-2.5-flash`).

---

## 4. Supported Workflows

### Intent Classification

The `intent_agent` produces a JSON payload with the following schema:

```json
{
  "intent": "<INTENT_LABEL>",
  "companies": ["MSFT"],
  "time_horizon": "2 weeks",
  "metrics": ["revenue", "margins"],
  "alert_threshold_percent": 5.0,
  "chart_type": "prediction",
  "output_format": "text",
  "raw_query": "<original user message>"
}
```

### Classification Priority Rules (applied top-to-bottom)

0. Explicit output-format keywords (`PDF`, `download`, `export`, `generate a report`, `save as a file`) → `PDF_REPORT` — overrides all topic-based rules so an explicit format always wins
1. Trading intent (`should I buy/sell`, `trade X`, `paper trade`, `portfolio`, `trade signals`) → `TRADE_ANALYSIS`
2. Chart/graph/visual of a forecast → `PRICE_PREDICT_CHART`
3. Price AND prediction, no chart → `PRICE_PREDICTION`
4. 10-K/annual report AND financial data together → `ANNUAL_FINANCIAL`
5. Comparison of 2+ stocks → `STOCK_COMPARISON`
6. Cross-section / multimodal report analysis → `INVESTMENT_RESEARCH`
7. Otherwise: single-purpose intent

### Workflow Catalogue

| # | Intent Label | Agent Pipeline | Example Query |
|---|-------------|----------------|---------------|
| 1 | `PRICE` | price_agent | "What is MSFT's stock price?" |
| 2 | `PREDICTION` | prediction_agent | "Forecast NVDA for the next 2 weeks" |
| 3 | `ALERT` | alert_agent | "Which software stocks dropped more than 5% today?" |
| 4 | `FINANCIAL_REPORT` | financial_report_agent | "Show me Apple's revenue and margins" |
| 5 | `VISUALIZATION` | visualization_agent | "Chart MSFT price history" |
| 6 | `PDF_REPORT` | pdf_agent | "Generate a PDF report for Salesforce" |
| 7 | `ANNUAL_REPORT` | tenk_agent | "What are the risk factors in Google's 10-K?" |
| 8 | `PRICE_PREDICTION` | price_agent → prediction_agent | "Give me Microsoft's price and predict the next 2 weeks" |
| 9 | `PRICE_PREDICT_CHART` | price_agent → prediction_agent → visualization_agent | "Show me NVDA's price, forecast, and chart" |
| 10 | `ANNUAL_FINANCIAL` | tenk_agent → financial_report_agent | "Analyze Snowflake's annual report and financial metrics" |
| 11 | `STOCK_COMPARISON` | comparison_trend_agent → comparison_insights_agent | "Compare MSFT and NVDA" |
| 12 | `TRADE_ANALYSIS` | trading_agent | "Should I buy NVDA? Analyse and place a mock trade." |
| — | `UNKNOWN` | clarification message | Ambiguous or out-of-scope queries |

---

## 5. Specialist Agent Specifications

### 5.1 `price_agent`
- **Purpose:** Fetches current price, daily change %, market cap, and previous close for one or more tickers.
- **Tools:** `resolve_ticker`, `get-ticker-info` (MCP)
- **Supports:** Single-stock lookup, multi-stock comparison, sector overview

### 5.2 `prediction_agent`
- **Purpose:** Generates a 10-trading-day (≈2-week) price forecast using linear regression on 3 months of closing prices.
- **Tools:** `resolve_ticker`, `fetch_and_forecast`
- **Algorithm:** Ordinary least squares linear regression; slope + intercept extrapolated 10 days forward (weekdays only)
- **Design note:** One-shot tool avoids passing large price-history JSON through the LLM context

### 5.3 `alert_agent`
- **Purpose:** Evaluates whether any monitored stock has dropped ≥ N% from the previous close.
- **Default watchlist:** MSFT, NVDA, CRM (3 stocks — reduced from 10 to stay within LLM context budget when each `get-ticker-info` call returns ~2 KB of JSON)
- **Default threshold:** 5%
- **Tools:** `resolve_ticker`, `get-ticker-info` (MCP), `evaluate_drop_alerts`

### 5.4 `financial_report_agent`
- **Purpose:** Summarises the most recent annual financial filing — revenue, gross/operating/net margins, EPS, P/E, debt-to-equity, free cash flow.
- **Tools:** `resolve_ticker`, `get-ticker-info` (MCP), `ticker-earning` (MCP)
- **Data source:** yfinance financial statements

### 5.5 `visualization_agent`
- **Purpose:** Renders inline charts as base64-encoded PNG images embedded in markdown.
- **Chart types:**
  1. Historical price line chart (3-month daily closes)
  2. Prediction overlay chart (history + 10-day regression forecast band)
  3. Multi-stock daily change bar chart (sector comparison)
  4. Financial metrics chart (income statement + margin bars)
- **Tools:** `resolve_ticker`, `render_price_chart_for_ticker`, `render_prediction_chart_for_ticker`, `render_comparison_chart_for_tickers`, `render_financial_chart_for_ticker`
- **Design note:** All four chart tools are one-shot wrappers — they accept only a ticker symbol, fetch all required data internally (yfinance), and return the base64 PNG embed. MCP tools are not used by this agent; raw OHLCV arrays and ticker-info dicts never pass through the LLM context. Additionally, `after_tool_callback` in `audit.py` strips the `"markdown"` (base64) field from chart tool responses before they reach the LLM, preventing a Gemini hang caused by tokenising ~170K tokens of base64 as input. The ADK event stream delivers the image to the frontend before the callback fires, so the user sees the chart while the LLM only receives `{"status": "success", "title": "..."}` and writes a one-sentence caption.

### 5.6 `pdf_agent`
- **Purpose:** Compiles a multi-section PDF report including price snapshot, 2-week forecast, drop alert status, and financial summary.
- **Tools:** `resolve_ticker`, `get-ticker-info` (MCP), `ticker-earning` (MCP), `compile_pdf_report`
- **Workflow:** Fetches financial data directly via MCP tools, builds a brief `financial_summary` string (2–4 sentences), then calls `compile_pdf_report`. A2A delegation to `financial_report_agent` was removed — the ADK `transfer_to_agent` hand-off permanently yielded control to the sub-agent, preventing `compile_pdf_report` from ever being called.
- **Output:** Downloadable PDF file path returned to user

### 5.7 `tenk_agent`
- **Purpose:** Answers qualitative questions about a company's SEC 10-K or 20-F annual filing using RAG.
- **Covered sections:** Business description, risk factors, MD&A, legal proceedings, executive compensation, segment reporting, competitive landscape
- **Tools:** `resolve_ticker`, `list_indexed_companies`, `search_10k`
- **Backend:** ChromaDB vector store (`data/10k_chroma/`); `all-MiniLM-L6-v2` embedding model (warm-up at startup); 669 MSFT chunks indexed
- **Note:** For cross-company entity+relationship queries see `investment_research_agent` (LightRAG backend)

### 5.8 `comparison_trend_agent`
- **Purpose:** Computes and presents a multi-period price trend table and a normalised returns chart for 2+ stocks.
- **Tools:** `resolve_ticker`, `fetch_price_trends`, `render_comparison_trend_chart`
- **Design note:** Both tools are one-shot — raw OHLCV arrays never pass through the LLM context. The chart is rendered as an embedded PNG; the agent instruction explicitly forbids copying the base64 markdown into the prose response (prevents MAX_TOKENS via 50KB context pollution).

### 5.9 `comparison_insights_agent`
- **Purpose:** Reads the trend table from conversation history, classifies the trend direction per stock, then runs RAG searches against each company's 10-K to produce qualitative per-company paragraphs and a comparative summary.
- **Tools:** `resolve_ticker`, `list_indexed_companies`, `search_10k`
- **Design note:** Runs after `comparison_trend_agent`; picks up the trend table from shared session context — no explicit data handoff required. Calls `list_indexed_companies` first to confirm which companies have indexed 10-K data before attempting searches.

### 5.11 Market Alert Monitor (`alert_monitor.py`)
- **Purpose:** Continuously monitors the market in the background and proactively notifies the user when user-defined conditions are met — without requiring an active session.
- **Two-layer design:** Monitor (pure-Python watchman, always running) + `alert_agent` (ADK `LlmAgent`, invoked only when a condition fires via ephemeral `InMemorySessionService` session). The monitor handles scheduling, data fetching, and delivery; the agent handles analysis.
- **Alert types and conditions:**

  | Alert type | Conditions checked |
  |------------|-------------------|
  | `buy_opportunity` | RSI < `rsi_threshold` (default 35), price < MA50 × `ma_threshold` (default 0.95), volume spike > `volume_multiplier`× (default 1.5), optional earnings proximity window |
  | `sell_signal` | RSI > `rsi_threshold` (default 70), price > MA50 × `ma_threshold` (default 1.05), volume spike > `volume_multiplier`× (default 1.5) |
  | `price_move` | |Δ%| over `lookback_days` > `threshold_percent`; bidirectional by default |

- **Alert content (generated by `alert_agent`):** what happened · why it matters · confidence level (High / Medium / Low) · suggested next review step. No trade directives. If the agent call fails, `_fallback_content()` builds a factual summary from the pre-fetched price snapshot and matched conditions (not a generic placeholder).
- **Delivery channels:**
  - **In-browser SSE:** `GET /api/alerts/stream?token=<jwt>` — persistent EventSource connection; `{"type":"alert", ...}` event pushed to all open connections for the user
  - **Email:** SMTP via `ALERT_SMTP_HOST/PORT/USER/PASS` env vars; HTML email; opted in per user via `PUT /api/alerts/settings`
- **Cooldown:** 4-hour per-(config_id, ticker) cooldown tracked in-memory; prevents alert spam across consecutive poll cycles
- **No auto-trade:** Alert content contains no buy/sell directives; `alert_monitor.py` has no code path to `execute_pending_trade`
- **REST API:**

  | Method | Endpoint | Description |
  |--------|----------|-------------|
  | `GET` | `/api/alerts/configs` | List user's alert configs |
  | `POST` | `/api/alerts/configs` | Create a new alert config |
  | `PATCH` | `/api/alerts/configs/{id}` | Update/enable/disable a config |
  | `DELETE` | `/api/alerts/configs/{id}` | Delete a config |
  | `GET` | `/api/alerts/notifications` | Get notifications (all or unread-only) |
  | `GET` | `/api/alerts/count` | Unread notification count |
  | `POST` | `/api/alerts/read/{id}` | Mark notification as read |
  | `POST` | `/api/alerts/read-all` | Mark all notifications as read |
  | `GET` | `/api/alerts/stream` | SSE stream (JWT via `?token=`) |
  | `GET` | `/api/alerts/settings` | Get email preferences |
  | `PUT` | `/api/alerts/settings` | Update email preferences |
  | `GET` | `/api/alerts/monitor-status` | Live monitor stats + recent notifications |

- **UI (Alerts tab):**
  - **Stats bar:** Monitor status, **Triggers Today** (notifications fired in last 24 h), Total configured, Unread, Next check countdown
  - **Agent grid:** one card per config — status, cooldown tickers, last triggered, pause/resume, delete
  - **Notification log:** 10 most recent with confidence badge; click → detail modal
  - **Detail modal:** full analysis + **💬 Continue in Chat →** button
  - **Toast:** 8-second overlay on new SSE alert; **View →** and **Continue in Chat →** buttons
  - **Continue in Chat:** creates a new chat session pre-seeded with a framed draft message; agent routes to `investment_research_agent` (analysis) or `trading_agent` (trade decision); draft tells the agent the alert is already confirmed to prevent re-verification
  - **Alert setup modal:** ticker input is a searchable inline picker (80+ common tickers, filter by symbol/name, ✓ for selected, custom tickers supported)
  - Bell icon with unread badge in chat header
- **Files:** `stock_agent/alert_monitor.py`, `stock_agent/alert_store.py`, `stock_agent/alerts.db`
- **Design document:** `arch/agents/market-alert-monitor.md`

### 5.10 `trading_agent`
- **Purpose:** Analyses trade signals for a given ticker, proposes a mock paper trade for human approval, and executes or cancels it on confirmation.
- **Tools:** `get_trade_signals`, `get_pending_trade`, `store_pending_trade`, `execute_pending_trade`, `cancel_pending_trade`, `update_pending_trade_shares`, `get_portfolio`, `get_trade_history`
- **Signal scoring formula:**
  - 40% × OLS 14-day forecast return
  - 40% × analyst consensus score
  - 20% × analyst price target upside
  - **BUY** if composite score ≥ 0.3 · **SELL** if ≤ −0.3 · **HOLD** otherwise
- **Two-turn approval flow:**
  - Turn 1: Agent computes signals, presents analysis, calls `store_pending_trade`
  - Turn 2: Orchestrator detects `has_pending_trade()` and bypasses `intent_agent` entirely; `trading_agent` receives the user's confirmation ("yes"/"no") and calls `execute_pending_trade` or `cancel_pending_trade`
  - If the user replies with a different share count ("10 shares instead"), agent calls `update_pending_trade_shares` to revise the quantity, then re-presents the updated trade for final approval
- **Persistence:** `trades.jsonl` (append-only); portfolio positions computed by replaying the full log
- **Mock scope:** All trades are paper/mock — no real money moves; target notional per trade is ~$2,000

---

## 6. Data Sources & Integrations

| Source | How Used | Agent(s) |
|--------|---------|---------|
| **yfinance** | Real-time quotes, historical OHLCV, financial statements | price, prediction, alert, financial_report, visualization, pdf, comparison_trend |
| **SEC EDGAR / 10-K filings (ChromaDB)** | Chunked and embedded into ChromaDB `sec_10k` collection; searched via semantic similarity | tenk, comparison_insights |
| **SEC EDGAR / 10-K + 20-F + 6-K filings (LightRAG)** | Ingested into LightRAG knowledge graph; entity+relationship traversal for cross-company analysis; MSFT 10-K + SAP 20-F FY2023–2025 + SAP 6-K quarterly indexed | investment_research |
| **Finance MCP** (`finance_mcp_server.py`) | Tools: `get-ticker-info`, `get-price-history`, `ticker-earning` | price, alert, financial_report, pdf, visualization |

### Supported Tickers (built-in resolver)
40+ software/tech companies including: MSFT, AAPL, GOOGL, AMZN, META, NVDA, CRM, ORCL, ADBE, NOW, SNOW, PLTR, CRWD, DDOG, MDB, NET, TWLO, SHOP, SPOT, NFLX, ZM, WDAY, INTU, PYPL, SQ, GTLB, TEAM, ESTC, HUBS, OKTA, CSCO, FTNT, ZS, S, AMD, INTC, QCOM, AVGO, SAP, IBM, ACN.

---

## 7. Observability & Safety

### 7.1 Audit Logging (`audit.py`)
- Structured JSON logs for every agent start/end, LLM request/response, and tool call/response
- Implemented via ADK callbacks: `before_agent_callback`, `after_agent_callback`, `before_model_callback`, `after_model_callback`, `before_tool_callback`, `after_tool_callback`
- Daily-rotating audit logs with 90-day retention (gzip compressed); `session_id` and `user_id` are present on every log entry
- **Disclaimer tracking:** `_DISCLAIMER_REQUIRED_AGENTS` frozenset — 9 agents must include a disclaimer phrase in every text response; if absent, a `disclaimer_missing` event is emitted and `disclaimer: "missing"` is recorded
- **Circuit breaker events:** `circuit_open` events logged when a breaker trips and a graceful fallback is returned
- **Cost recording:** every LLM response writes a JSON line to `cost.jsonl` with `agent`, `model`, `input_tokens`, `output_tokens`, `cost_usd`

### 7.2 LangFuse Tracing (`tracing.py`)
- Full distributed tracing hierarchy: **Trace → agent spans → generations + tool spans**
- Root trace created when `stock_orchestrator` starts; flushed when it ends
- **In-process metrics collection** (`_metrics` dict): tool spans and token usage are accumulated regardless of LangFuse availability, feeding the eval framework
- Configured via: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`
- Graceful degradation: if LangFuse is unavailable, in-process metrics still collected

### 7.3 Guardrails (`guardrails.py` + `pii_store.py`)

Six checks fire automatically at every LLM boundary via ADK model callbacks. Agents cannot bypass them.

| Check | Scope | Description |
|-------|-------|-------------|
| 1 — Prompt injection | Root agent, once per turn | Phrase-based blocklist (20 patterns); blocks jailbreak attempts |
| 2 — Out-of-scope | Root agent, once per turn | Rejects non-financial topics (sport, food, politics, etc.) |
| 3 — PII tokenisation | All agents, every LLM call | Replaces EMAIL/PHONE/SSN/CC/IP with `[TYPE_N]` tokens before the model sees the input |
| 4 — Token limit | All agents, every LLM call | Blocks requests estimated > 120 000 tokens; sub-agents trim accumulated session history before estimation (context trim guardrail) |
| 5 — PII detokenisation | All agents, every LLM call | Replaces `[TYPE_N]` tokens in output with masked values; scans output for independently generated PII |
| 6 — Financial advice | All agents, every LLM call | Prepends disclaimer if directive advice patterns detected ("you should buy", "guaranteed return", etc.) |

**PII storage** (`pii_store.py`):
- Backend: SQLite at `data/pii_tokens.db` (git-ignored)
- Encryption: Fernet (AES-128-CBC + HMAC-SHA256) via `cryptography>=42.0.0`
- Key: `PII_STORE_KEY` env var (production); auto-generated `data/.pii_key` (dev, `chmod 0600`)
- Retention: 90 days (configurable via `PII_TOKEN_TTL_SECONDS`); tokens kept for multi-turn session detokenisation; expired rows purged lazily on every write
- PII is never written to session state

### 7.4 Evaluation Framework (`eval/`)

Three-level metrics computed against 33 intent test cases + 22 E2E test cases:

| Level | Metrics |
|-------|---------|
| **L1 — Model Quality** | Action Success Rate, Tool Select Accuracy, Hallucination Rate, Context Utilisation, Guardrail Violation Rate |
| **L2 — Product** | Containment Rate, Task Completion Rate, Response Confidence, Response Latency, Human Override Rate |
| **L3 — Business** | Cost per Task (USD), Productivity Gain (hrs saved), Cost Savings vs. analyst baseline |

Each metric has a pass/fail threshold defined in `eval/thresholds.yaml`. In addition, every `E2ECase` carries **per-case RAGAS thresholds** (`factual_correctness`, `answer_relevancy`, `faithfulness`) that are calibrated against actual tool outputs — static cases use real filing figures; live-data cases use achievable NLI-matching levels. Results are saved to `eval/results/` as JSON + Markdown.

### 7.5 Circuit Breakers (`circuit_breaker.py`)

Implements a CLOSED→OPEN→HALF_OPEN state machine to prevent cascading failures when downstream services degrade.

| Breaker | Failure threshold | Reset window | Protected service |
|---------|------------------|--------------|------------------|
| `_gemini_breaker` | 5 failures | 30 s | Gemini LLM API |
| `_yahoo_breaker` | 5 failures | 30 s | Yahoo Finance MCP |
| `_a2a_breaker` | 3 failures | 60 s | A2A remote agents |

Integration via `audit.py` callbacks: `before_model_callback` returns a graceful `LlmResponse` if the Gemini breaker is open; `before_tool_callback` returns an error dict if the Yahoo or A2A breaker is open; `after_model/tool_callback` records success or failure to update breaker state.

### 7.6 Cost Tracking & Spend Alerts

**Cost tracking (`cost.jsonl` + `cost_report.py`):**
- Every LLM response appends a JSON line to `cost.jsonl`: `{agent, model, input_tokens, output_tokens, cost_usd, timestamp}`
- `python -m stock_agent.cost_report` aggregates totals by day and agent and prints a Markdown table

**Spend alerts (`spend_alert.py`):**
- Reads `cost.jsonl` at startup and sums the current calendar month's spend
- Warns at **80% of `MONTHLY_SPEND_LIMIT_USD`** (yellow terminal warning) and **100%** (red terminal warning)
- Called from both `main.py` and `web_server.py` on startup

### 7.7 Prompt Versioning & Per-Agent Token Budgets

**Prompt versioning (`prompt_loader.py` + `prompts/`):**
- Agent system prompts are extracted from inline Python strings to `prompts/{agent_name}_v{n}.md` files
- `stock_agent/prompt_loader.py` loads the correct version at startup; A/B testing is enabled by changing the version number

**Per-agent token budgets (`model_config.py`):**
- `stock_agent/model_config.py` defines per-agent `max_output_tokens` (e.g. `intent_agent=500`, `trading_agent=1024`, `investment_research_agent=3000`)
- Injected into every `LlmRequest` via `before_model_callback` in `audit.py`

### 7.8 RAGAS Eval Gate

- `python -m eval.run_eval --gate` exits with code 1 if any metric regresses below its threshold defined in `eval/thresholds.yaml`
- New `intent` section in `thresholds.yaml` with `intent_accuracy: {threshold: 0.80, direction: min}`
- Intended for use as a CI gate to block regressions before deployment

---

## 8. Design Decisions

| Decision | Rationale |
|----------|-----------|
| **FastAPI web server over ADK Web** | ADK Web is a generic development tool — no session history, no custom streaming layout, and no domain-specific chart rendering. FastAPI exposes only the events the UI needs (text tokens, images) and supports the session lifecycle precisely. |
| **SSE over WebSocket for streaming** | SSE is unidirectional (server→client), requires no handshake, and is natively retried by browsers. Chat streaming is strictly unidirectional, so SSE is simpler and correct. |
| **ContextVar for image capture** | Chart images must reach the browser before `audit.py` strips the base64 from the LLM context. Wrapping `after_tool_callback` via a `ContextVar` lets each concurrent SSE request accumulate its own image list without shared mutable state. |
| **marked.js for markdown rendering** | Renders GitHub-flavoured markdown — tables, code blocks, and `![](data:image/png;base64,...)` tags — natively in the browser. No server-side rendering step; no separate image server required. |
| **Deterministic Python routing** | Eliminates non-determinism of a second routing LLM call; routing is fast and fully auditable |
| **`intent_agent` has zero tools** | Prevents infinite LLM call loops from un-committed `function_call` events when the orchestrator swallows events |
| **One-shot tools** (`fetch_and_forecast`, `render_prediction_chart_for_ticker`, `fetch_price_trends`, `render_comparison_trend_chart`) | Avoids passing large OHLCV JSON (60+ rows) or base64 PNGs (~50KB) through LLM context; prevents `MAX_TOKENS` and `MALFORMED_FUNCTION_CALL` errors |
| **Comparison pipeline split** (trend agent + insights agent) | A single comparison agent overloads context with price data + multiple RAG searches + synthesis simultaneously; the split keeps each agent's context small and focused |
| **Callback-based guardrails** | Safety logic cannot be bypassed by individual agents; every new agent automatically inherits all six checks |
| **PII store in encrypted SQLite** | Keeps PII token maps off session state (which is plain-text); SQLite + Fernet requires no additional infrastructure; `cryptography` already in the dependency tree |
| **90-day PII retention** | Tokens may need to be detokenised in later turns of a multi-turn session; TTL expiry is the only deletion mechanism |
| **Direct MCP tools in `pdf_agent`** | `pdf_agent` previously delegated to `financial_report_agent` via A2A, but ADK's `transfer_to_agent` permanently yields control — `pdf_agent` never resumed to call `compile_pdf_report`. Refactored to fetch `get-ticker-info` and `ticker-earning` directly via MCP and build a brief `financial_summary` inline, then call `compile_pdf_report`. |
| **RBAC tab visibility (analyst/admin only)** | Trading History and Analytics tabs are hidden from viewer-role users in `_showApp()` via `display:none`; the backend also RBAC-gates the pending-trade bypass so a viewer cannot approve a trade even by typing "yes". Viewers default to the Chat tab. |
| **RAG lazy init** | ChromaDB + `all-MiniLM-L6-v2` loaded on first query in a background thread; avoids startup latency when 10-K is not needed |
| **In-process metrics collection** | `tracing._metrics` accumulates tool spans and token counts regardless of LangFuse availability, enabling eval without a cloud dependency |
| **In-memory pending trade state** | Pending trades are keyed by `session_id` via a `ContextVar` — isolates per-session approval flow without DB writes until the user confirms |
| **Orchestrator bypass for pending trades** | A bare "yes" must not re-classify via `intent_agent`; when `has_pending_trade()` is true the orchestrator routes directly to `trading_agent`, skipping intent classification entirely |
| **Circuit breakers in `audit.py` callbacks** | Breaker checks live in the shared callback layer rather than per-agent — ensures every agent benefits from protection without per-agent configuration |
| **Per-user session isolation** | Sessions scoped by `username` (from JWT) rather than a single hardcoded `_USER_ID`. Both `_sessions` dict and ADK `SqliteSessionService`/`ChromaMemoryService` filter by `user_id` so users never see each other's data. |
| **Session deletion with ownership check** | `DELETE /api/sessions/{id}` verifies the authenticated user owns the session before removing it from the in-memory store, `sessions_meta.db`, and the ADK session service. |
| **SVG-based brand identity** | Logo and favicon are hand-authored SVG files (no external design tool dependency): scalable to any resolution, inlined via `<img src="/static/...">`, and served as static files by FastAPI's `StaticFiles` mount at `/static`. |
| **Split-screen login layout** | Left panel is a trading-chart photo with CSS `saturate`/`brightness` filter and a gradient overlay; right panel is the fixed-width form. No JavaScript — pure CSS `display:flex`. The photo is desaturated and darkened so the white form remains legible against any image. |
| **Resizable sidebar via drag handle** | A 5px `#sidebar-resizer` div sits between the sidebar and main area. `mousedown/mousemove/mouseup` listeners on `document` drive the resize; `min-width`/`max-width` clamps prevent unusable extremes. Width is persisted to `localStorage` so the preference survives page reloads. CSS `transition` is disabled during drag to prevent janky animation. |
| **Session keyword search with highlight** | `renderSidebar(query)` filters the sessions list client-side and wraps matching substrings in `<mark>` tags via `_highlightMatch()`. No server round-trip. The search input value is read inside `renderSidebar` so any code path that mutates sessions and calls `renderSidebar()` automatically respects the active filter. |
| **Trading History in localStorage** | Client-side trade ledger stored as a JSON array in `localStorage` keyed per user (`trades_{username}`). No backend endpoint required. Suitable for personal annotation; data is local to the browser. |
| **Analytics computed client-side from localStorage + live API** | Summary cards, doughnut chart, and holdings table are computed in the browser from the localStorage trade ledger combined with live prices from `GET /api/prices`. The portfolio value trend replays the trade history against `GET /api/price-history` closing prices so no server-side portfolio state is required. Chart.js renders all charts as `<canvas>` elements. |
| **Two RAG backends for different query types** | ChromaDB (semantic similarity) serves `tenk_agent` for section-level keyword retrieval from 10-K chunks. LightRAG (knowledge graph) serves `investment_research_agent` for entity+relationship traversal — e.g. "which companies share risk factors around AI regulation?". The two backends share the same source filings but index them differently; there is no duplication of query logic across agents. |
| **`__routing__` event filtering in eval harness** | The orchestrator emits a `__routing__` ADK event (`author="__routing__"`, `role="model"`) containing `{"pipeline": "PRICE", "companies": ["MSFT"]}`. Without filtering, this JSON blob appears at the start of every captured response text and is passed to RAGAS as part of the agent's answer — depressing faithfulness (routing JSON is not grounded in tool outputs) and inflating hallucination rate. Filtering both `__routing__` and `__progress__` authors ensures RAGAS only evaluates the actual user-facing response. |
| **ALERT pipeline default company injection** | When the orchestrator emits a `__routing__` event for `intent=ALERT` with `companies=[]`, the empty list is stored in ADK session history and injected into the `alert_agent` LLM context. The LLM sees `companies: []` as a prior model message and produces no tool calls or output. The fix injects the agent's configured default watchlist (`["MSFT", "NVDA", "CRM"]`) into the routing event when companies is empty, matching what the agent prompt already declares as defaults. |
| **Alert monitor as asyncio task, not separate process** | A separate process would need IPC to reach SSE queues held by the web server, and would require either network access or file-level locking for SQLite writes. An asyncio task runs inside the FastAPI process, shares `_sse_queues` directly, and accesses `alerts.db` with WAL mode (safe for concurrent reads from the API). No IPC, no port management, no serialisation overhead. |
| **Cheap-then-expensive evaluation in alert monitor** | Running a Gemini LLM call on every ticker on every poll cycle would be expensive (e.g. 10 tickers × 96 polls/day = 960 calls/config/day). Condition evaluation is pure arithmetic: 1 yfinance HTTP call per ticker. Gemini Flash is invoked only when a condition fires, which is rare in calm markets. |
| **SSE EventSource auth via `?token=` query param** | The browser `EventSource` API cannot set custom HTTP headers — there is no way to pass `Authorization: Bearer` to an EventSource connection. The alert stream endpoint accepts the JWT as a `?token=` query parameter as a fallback when no Bearer header is present. The same `_require_auth` dependency handles both paths. |
| **4-hour in-memory cooldown per (config, ticker)** | Without a cooldown, a sustained condition (e.g. RSI staying below 35) would generate a notification on every 15-minute poll cycle. The cooldown is stored in-memory (`_last_fired` dict) rather than in SQLite — a server restart intentionally resets cooldown state cleanly. |
| **No-auto-trade guarantee in alert content** | Alert content is deliberately limited to factual description: what happened, why it matters, confidence level, and suggested next review step. No buy/sell directives appear in alert text. `alert_monitor.py` contains no trade execution code and has no path to `execute_pending_trade` — the user must explicitly start a `TRADE_ANALYSIS` session to act on an alert. |
| **Sub-agent context trim guardrail** | ADK passes the full session event history to every sub-agent LLM call. In a long session this accumulates thousands of tokens the sub-agent has no use for. `_trim_contents_to_current_invocation()` strips history to only the current invocation before token estimation, so the 120 000-token check sees an accurate (and much smaller) number. Without this trim, sub-agents hit the limit mid-session even for simple single-question turns. |
| **Per-case RAGAS thresholds in `cases.py`** | Global thresholds in `thresholds.yaml` are too coarse: live-data cases (price, alerts) can never achieve FC≥0.45 because the reference is static but yfinance numbers move; RAG cases achieve FC≥0.90 because the text is indexed verbatim. Embedding thresholds directly on each `E2ECase` lets each case set an achievable bar: static 10-K cases use FC≥0.50, live financial cases use FC≥0.25, and forecast/trade cases omit FC entirely. |
| **Chart.js over custom SVG** | Chart.js (loaded from CDN) provides interactive tooltips, responsive sizing, and animation out of the box. Alternatives (Recharts, D3, hand-rolled SVG) were not considered because the project has no build step; Chart.js UMD bundle works with a plain `<script>` tag. |
| **Smart pending-trade bypass** | The original orchestrator routed *every* query to `trading_agent` while a pending trade was open — silently hijacking PDF/chart/analysis requests. The bypass now only fires when the user message is a short approval/cancellation phrase (≤30 chars, matches a yes/no/buy/cancel keyword as a whole word). Any other query auto-cancels the stale pending trade and continues to normal intent classification, with a "Previous trade proposal cancelled" progress event so the user understands what happened. |
| **Authenticated downloads via Blob URL** | Markdown links can't carry an `Authorization` header, and adding the JWT to the URL would leak it in server logs and browser history. Instead, the frontend installs a delegated click handler on `document` that intercepts any click on `/api/downloads/...`, calls `fetch()` with the auth header, receives the file as a `Blob`, and triggers a real download via a temporary `<a download>` + Blob URL. Server-side, `Content-Disposition: attachment` forces the browser to save rather than render inline. |

---

## 9. Known Limitations

| Limitation | Impact | Potential Mitigation |
|-----------|--------|---------------------|
| Linear regression forecast | Naive — ignores earnings, news, macro events | Upgrade to ARIMA, Prophet, or ML-based model |
| 40-ticker built-in resolver | Unknown tickers pass through as-is (may fail) | Dynamic lookup via yfinance `search()` |
| 10-K RAG coverage | Only companies with pre-indexed filings are searchable | Automated EDGAR ingestion pipeline |
| No real-time streaming data | Prices are point-in-time snapshots | WebSocket feed integration |
| Token guardrail may block valid requests | Complex multi-company queries can hit 120K limit (raised from 20K; sub-agent context trim makes this much rarer) | Summarisation pass before LLM |
| Alert cooldown state is in-memory | Server restart resets the 4-hour cooldown — an alert may fire again sooner than expected after a restart | Persist `_last_fired` to SQLite |
| Alert monitor polls on a fixed 15-minute interval | Real-time events (sudden crashes) may be missed between polls | Reduce interval or subscribe to a WebSocket price feed |
| SMTP email requires manual env-var configuration | No in-app email setup wizard; admin must set `ALERT_SMTP_*` env vars at deploy time | Add SMTP test-send button in settings modal |
| Comparison limited to software-sector tickers | Out-of-universe tickers may not resolve | Extend resolver or use yfinance search |
| Web UI sessions are in-memory | ~~Lost on server restart~~ **Fixed** — `sessions_meta.db` + `sessions.db` persist across restarts | — |
| Mock trading only | No real broker integration; no real money | Integrate Alpaca/IB broker SDK in `execute_mock_trade()` |
| Trading History stored client-side | `localStorage` is browser-local; no sync across devices or users | Add `POST /api/trades` / `GET /api/trades` backend endpoints |
| Analytics price data is real-time, not intra-day streaming | `GET /api/prices` snapshots yfinance at request time — prices do not auto-refresh | Add a polling interval or WebSocket feed to the analytics panel |
| Portfolio trend uses cost basis as fallback | When a stock has no price history entry for a given day (e.g. newly bought ticker not yet in yfinance cache), the position's cost basis is used instead of a market price | Use previous day's close as fallback instead |

---

## 10. Future Opportunities

1. **Persistent sessions** — ✅ done (`sessions_meta.db` + `sessions.db`)
2. **Scheduled alerts** — ✅ done (`alert_monitor.py` background poll + SSE + email; see §3.2 Alert Monitor and §5.11)
3. **Streaming price updates** — WebSocket feed for live tickers displayed in the UI
4. **Expanded universe** — auto-ingest any S&P 500 ticker; extend RAG to cover all EDGAR 10-K filings
5. **Multi-model routing** — use a lighter model (Gemini Flash Lite) for simple price lookups; reserve 2.5 Flash for forecasts and RAG
6. **Backtesting** — evaluate forecast accuracy against historical data; display confidence intervals
7. **Portfolio-level analysis** — basic mock portfolio tracking is implemented; extend with real positions, correlation matrix, weighted returns
8. **Conversational memory** — persist company preferences and alert thresholds across sessions
9. **ADK Workflow API migration** — replace `GraphOrchestrator` with native sequential/parallel workflow primitives when available
10. **Server-side Trading History** — migrate `localStorage` trade ledger to a backend endpoint (`POST/GET /api/trades`) for cross-device and multi-user support
11. **Analytics auto-refresh** — polling interval or WebSocket price feed so the analytics panel stays current without a manual refresh
12. **Portfolio benchmark comparison** — overlay S&P 500 (SPY) or a custom index on the portfolio trend chart

---

## Appendix A — Environment Setup

```bash
# LangFuse (optional — tracing degrades gracefully if absent)
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://us.cloud.langfuse.com

# PII store encryption key (production — omit to auto-generate dev key)
PII_STORE_KEY=<base64url-encoded 32-byte key>

# PII token retention (optional — default 90 days)
PII_TOKEN_TTL_SECONDS=7776000

# Runtime — web UI (recommended)
uvicorn web_server:app --port 8080 --reload
# Open http://localhost:8080

# Runtime — terminal CLI (alternative)
python main.py
```

**Key dependencies:** `google-adk`, `fastapi`, `uvicorn`, `yfinance`, `langfuse>=3.0.0`, `chromadb`, `matplotlib`, `reportlab`, `cryptography>=42.0.0`, `ragas`

---

## Appendix B — File Map

```
web_server.py                      # FastAPI server: per-user sessions, SSE streaming, image capture, static file serving, GET /api/prices, GET /api/price-history
static/
├── index.html                     # Single-page chat UI (split-screen login, sidebar resize, session search/delete, trading history tab, analytics tab with Chart.js)
├── logo.svg                       # FinanceAI horizontal lockup — blue diamond + gold wordmark
├── favicon.svg                    # FinanceAI icon-only 48×48 SVG
└── bull.jpg                       # Trading-chart photo (login background)

stock_agent/
├── agent.py                       # GraphOrchestrator + _ROUTE_MAP (13 intents)
├── intent_agent.py                # LLM intent & entity extraction
├── price_agent.py                 # Real-time price lookup
├── prediction_agent.py            # 2-week OLS forecast
├── alert_agent.py                 # Drop threshold monitoring
├── financial_report_agent.py      # Annual financial summary
├── visualization_agent.py         # Chart rendering
├── pdf_agent.py                   # PDF report compilation (direct MCP — no A2A)
├── tenk_agent.py                  # 10-K RAG Q&A
├── comparison_trend_agent.py      # Multi-stock price trend table + chart
├── comparison_insights_agent.py   # Per-company 10-K insights + synthesis
├── trading_agent.py               # Mock paper trading agent with human-in-the-loop approval
├── trade_tools.py                 # get_trade_signals, store/execute/cancel_pending_trade, update_pending_trade_shares, get_portfolio, get_trade_history
├── alert_monitor.py               # Background asyncio poll loop: condition evaluation, Gemini content gen, SSE push, SMTP email, cooldown tracking
├── alert_store.py                 # SQLite persistence for alert_configs, alert_notifications, user_alert_settings
├── circuit_breaker.py             # CLOSED→OPEN→HALF_OPEN breakers for Gemini, Yahoo Finance MCP, A2A
├── spend_alert.py                 # Monthly spend alert at 80%/100% of configurable limit
├── cost_report.py                 # Aggregates cost.jsonl by day/agent; CLI: python -m stock_agent.cost_report
├── prompt_loader.py               # Loads versioned agent system prompts from prompts/ directory
├── model_config.py                # Per-agent max_output_tokens budgets
├── tools.py                       # resolve_ticker, fetch_and_forecast, fetch_price_trends, evaluate_drop_alerts
├── visualization_tools.py         # render_*_chart functions
├── pdf_tools.py                   # compile_pdf_report
├── tenk_tools.py                  # search_10k, list_indexed_companies
├── finance_mcp_server.py          # MCP: yfinance price/financial data
├── rag_mcp_server.py              # MCP: ChromaDB 10-K vector store
├── lightrag_config.py             # Shared LightRAG + RAGAnything instances (knowledge graph over SEC filings)
├── guardrails.py                  # Six-check guardrail system
├── pii_store.py                   # Fernet-encrypted SQLite PII token store
├── audit.py                       # Structured JSON audit logging; 90-day rotating logs, disclaimer tracking, cost recording
├── tracing.py                     # LangFuse tracing + in-process metrics
└── mcp_config.py                  # MCP toolset factory

prompts/                           # Versioned agent system prompt files ({agent_name}_v{n}.md)

eval/
├── eval_harness.py                # ADK runner + RunResult capture; filters __routing__ + __progress__ events
├── cases.py                       # 33 intent + 22 E2E test cases; per-case RAGAS thresholds on each E2ECase
├── metrics.py                     # Three-level metrics computation
├── langfuse_client.py             # Tool-span + cost extraction
├── run_eval.py                    # CLI: runs eval + prints dashboard
└── thresholds.yaml                # Pass/fail thresholds for all 15 metrics

arch/
├── Architecture.md                # Component map, rationale, 13 sequence diagrams (incl. 4.13 Alert Monitor)
├── 01-orchestration-and-workflows.md
├── 02-intent-extraction.md
├── 03-mcp-integration.md
├── 04-a2a-integration.md
├── 05-guardrails.md               # Six-check system, PII lifecycle, storage
├── 06-evaluation.md               # Three-level metrics, formulas, dashboard
├── 07-rag.md
├── 08-ragas-test-cases.md
├── 09-langfuse-integration.md
└── agents/                        # Per-agent design documents
    ├── market-alert-agent.md      # Agent design doc: chat alert_agent + background monitor, tools, conditions, integration points, message flows
    └── market-alert-monitor.md    # System architecture doc: component diagram, sequence diagrams, data model

prd/
├── PRD.md                         # This document
└── EPICS_AND_STORIES.md           # Epics and user stories

data/
├── 10k_chroma/                    # ChromaDB sec_10k collection (669 MSFT chunks + other tickers)
├── 10k_raw/                       # Downloaded SEC filing HTML files
├── pii_tokens.db                  # Encrypted PII token store (git-ignored)
└── .pii_key                       # Dev encryption key (git-ignored)

lightrag_storage/                  # LightRAG knowledge graph: MSFT 10-K + SAP 20-F/6-K (git-ignored)
├── manifest.jsonl                 # One JSON line per ingested filing
└── ...                            # LightRAG internal graph/vector/kv stores

stock_agent/
└── alerts.db                      # SQLite alert store: alert_configs, alert_notifications, user_alert_settings (WAL mode)

trades.jsonl                       # Append-only mock trade log (git-ignored)
cost.jsonl                         # Append-only LLM cost log; one JSON line per response (git-ignored)
```
