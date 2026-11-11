# Epics & User Stories — Stock Analysis Agent

**Version:** 7.0 | **Date:** 2026-05-08

---

## Epic 1: Real-Time Stock Price Intelligence

**Goal:** Users can instantly retrieve current price data and compare stocks in natural language.

---

**US-1.1 — Single stock price lookup**
> As an investor, I want to ask for a stock's current price in plain English, so that I can quickly check a position without opening a brokerage app.

**Acceptance Criteria:**
- Given a company name or ticker (e.g. "What's Apple's price?"), the system returns current price, daily change $, daily change %, and market cap.
- Ticker resolution works for both symbols (AAPL) and common names (Apple).
- Response delivered in a single conversational turn.

---

**US-1.2 — Multi-stock price comparison**
> As a portfolio manager, I want to compare the daily performance of several software stocks side by side, so that I can see which positions are moving most.

**Acceptance Criteria:**
- Given a query naming 2+ companies, the system returns price and daily change % for each.
- Data is presented in a clear tabular or list format.
- All companies are resolved to canonical tickers before lookup.

---

**US-1.3 — Sector overview**
> As an analyst, I want to ask "how is the software sector doing today?" and receive a summary across major names, so that I can get a quick pulse without specifying every ticker.

**Acceptance Criteria:**
- System uses a default software-sector watchlist when no specific companies are named.
- Returns daily change % for each stock in the watchlist.
- Clearly labels the response as a sector snapshot.

---

## Epic 2: Price Forecasting

**Goal:** Users can obtain a data-driven 2-week price forecast for any supported stock.

---

**US-2.1 — 2-week price forecast**
> As an investor, I want to see a projected price trajectory for the next two weeks, so that I can make more informed short-term decisions.

**Acceptance Criteria:**
- Given a company name or ticker, the system returns a 10-trading-day forecast table (date + predicted price).
- Forecast includes current price, trend direction (upward/downward), and projected % change.
- A disclaimer is shown stating the forecast is based on linear regression and is not investment advice.

---

**US-2.2 — Combined price + forecast in one query**
> As an investor, I want to ask for both the current price and a 2-week forecast together, so that I don't have to ask two separate questions.

**Acceptance Criteria:**
- A single query like "give me MSFT's price and predict the next 2 weeks" returns both current price data and the forecast in one response.
- No chart is generated unless explicitly requested.
- The system does not trigger the visualization pipeline for this intent.

---

## Epic 3: Drop Alert Monitoring

**Goal:** Users can identify stocks that have breached a drop threshold on the current trading day.

---

**US-3.1 — Default sector drop alert**
> As a risk-conscious investor, I want to know which major software stocks have dropped more than 5% today, so that I can react quickly to significant moves.

**Acceptance Criteria:**
- System checks the default 3-stock watchlist (MSFT, NVDA, CRM) — reduced from 10 stocks to stay within the LLM context budget (each `get-ticker-info` call returns ~2 KB of JSON; 10 calls would exhaust the context window).
- Stocks with a daily drop ≥ 5% are flagged as alerts; others are listed as safe.
- Alert message includes ticker, company name, current price, previous close, and exact % drop.

---

**US-3.2 — Custom threshold alert**
> As a trader, I want to set my own drop threshold (e.g. 3%), so that I can tune the sensitivity of the alert to my risk tolerance.

**Acceptance Criteria:**
- User can specify a threshold in natural language (e.g. "fell more than 3%").
- System applies that threshold instead of the default 5%.
- Threshold is shown in the response so users can confirm what was applied.

---

**US-3.3 — Specific company alert**
> As a portfolio manager, I want to check whether a specific stock I own has dropped significantly today, so that I can monitor individual positions.

**Acceptance Criteria:**
- User can name one or more specific companies in the alert query.
- System evaluates only those companies, not the default watchlist.
- Response clearly shows alert/safe status for each named company.

---

## Epic 4: Financial Report Analysis

**Goal:** Users can retrieve and understand key financial metrics from a company's most recent annual filing.

---

**US-4.1 — Revenue and profitability summary**
> As a financial analyst, I want to ask about a company's revenue, margins, and profitability, so that I can assess its financial health without downloading SEC filings.

**Acceptance Criteria:**
- System returns: total revenue, gross profit, operating income, net income, gross margin %, operating margin %, net margin %.
- Values are formatted in readable units (e.g. "$45.2B").
- Data sourced from the most recent annual financial statements.

---

**US-4.2 — Balance sheet and valuation metrics**
> As an analyst, I want to see debt levels, cash position, and valuation ratios, so that I can evaluate a company's solvency and market pricing.

**Acceptance Criteria:**
- System returns: total debt, cash & equivalents, debt-to-equity ratio, P/E ratio, EPS.
- Clearly labelled as annual figures with fiscal year indicated where available.

---

**US-4.3 — Free cash flow summary**
> As an investor, I want to understand a company's free cash flow, so that I can assess how much cash the business is actually generating.

**Acceptance Criteria:**
- System surfaces operating cash flow and free cash flow figures.
- Contextualises FCF relative to net income where data is available.

---

## Epic 5: Annual Report (10-K) Q&A

**Goal:** Users can ask qualitative questions about a company's SEC 10-K filing and receive grounded, cited answers.

---

**US-5.1 — Risk factor lookup**
> As an analyst, I want to ask "what are the main risk factors in Snowflake's 10-K?", so that I can understand the key risks disclosed by management without reading hundreds of pages.

**Acceptance Criteria:**
- System retrieves relevant passages from the Risk Factors section of the 10-K using RAG (ChromaDB semantic similarity via `search_10k`).
- Response summarises the top risks with direct references to the source filing.
- If the company is not indexed, the system clearly states that and lists available companies via `list_indexed_companies`.

---

**US-5.2 — MD&A and business strategy**
> As a portfolio manager, I want to ask about management's discussion of business performance and strategy, so that I can understand how the company views its own trajectory.

**Acceptance Criteria:**
- System retrieves passages from the MD&A section.
- Response captures management's narrative on revenue drivers, growth strategy, and outlook.

---

**US-5.3 — Executive compensation query**
> As a governance-focused investor, I want to ask about executive pay and incentive structures from the 10-K, so that I can evaluate alignment between management and shareholder interests.

**Acceptance Criteria:**
- System retrieves executive compensation tables or narrative from the filing.
- Response includes named executives, compensation types, and total values where available.

---

**US-5.4 — Combined 10-K + financial data query**
> As an analyst, I want to ask about both the qualitative annual report content AND the financial metrics together, so that I can form a complete picture in one query.

**Acceptance Criteria:**
- A query like "analyse Snowflake's annual report and financial performance" triggers both `tenk_agent` and `financial_report_agent` sequentially.
- Response combines qualitative insights from the 10-K with quantitative financial metrics.
- Sections are clearly differentiated in the output.

---

**US-5.5 — Cross-company knowledge graph queries**
> As an analyst, I want to ask cross-cutting questions across multiple companies' filings — such as "which companies share AI regulation risks?" — and get an answer that draws on entity and relationship context, not just keyword matching.

**Acceptance Criteria:**
- Query classified as `INVESTMENT_RESEARCH` intent routes to `investment_research_agent`.
- Agent calls `query_investment_research` which queries the LightRAG knowledge graph.
- Graph covers MSFT 10-K and SAP 20-F/6-K (FY2023–2025) filings; additional companies added as they are ingested.
- Response surfaces entity+relationship context (e.g. named risks, competitors, technologies shared across companies).
- If no relevant graph content exists, agent states the limitation and suggests using `tenk_agent` for single-company queries.

---

## Epic 6: Data Visualisation

**Goal:** Users can generate inline charts for stock prices, forecasts, comparisons, and financial metrics.

---

**US-6.1 — Historical price chart**
> As an investor, I want to see a price history chart for a stock, so that I can visually assess trends over the past 3 months.

**Acceptance Criteria:**
- System renders a line chart of 3-month daily closing prices.
- Chart is embedded inline in the response as a PNG image.
- A one-sentence caption describes what the chart shows.

---

**US-6.2 — Forecast overlay chart**
> As an investor, I want to see a chart that shows both historical prices and the predicted trajectory, so that I can visually assess the forecast in context.

**Acceptance Criteria:**
- Chart shows historical price line + 10-day regression forecast.
- Historical and forecast segments are visually distinct.
- Embedded inline with caption.

---

**US-6.3 — Price + forecast + chart in one query**
> As an investor, I want to ask for a stock's current price, its forecast, and a chart all at once, so that I get a complete picture in a single response.

**Acceptance Criteria:**
- Query like "show me NVDA's price, predict next 2 weeks, and chart it" triggers price_agent → prediction_agent → visualization_agent.
- Response includes current price data, forecast table, and inline chart.
- Pipeline runs sequentially; each agent's output is visible in the final response.

---

**US-6.4 — Sector comparison bar chart**
> As a portfolio manager, I want to see a bar chart comparing daily performance across multiple software stocks, so that I can visually identify today's leaders and laggards.

**Acceptance Criteria:**
- System generates a bar chart with one bar per stock showing daily change %.
- Positive and negative bars are colour-coded.
- Works with both user-specified tickers and default sector watchlist.

---

**US-6.5 — Financial metrics chart**
> As an analyst, I want to see a chart of a company's key financial metrics, so that I can visually assess revenue scale and margin profile at a glance.

**Acceptance Criteria:**
- System generates a dual-panel chart: income statement bars and margin % bars.
- Values formatted in readable units ($M).
- Chart embedded inline with caption.

---

**US-6.6 — Multi-stock normalised returns chart**
> As an investor, I want to see a single chart showing the relative performance of multiple stocks over 1-year and 5-year horizons, so that I can visually compare long-term trajectories.

**Acceptance Criteria:**
- Chart shows normalised cumulative returns (all stocks indexed to 100 at start) so different price scales are comparable.
- Triggered as part of the `STOCK_COMPARISON` pipeline.
- Chart is embedded inline; prose response shows the period-by-period trend table separately.

---

## Epic 7: PDF Report Export

**Goal:** Users can generate and download a comprehensive PDF report for any supported stock.

---

**US-7.1 — Full PDF report generation**
> As a portfolio manager, I want to generate a PDF report for a stock that I can save and share, so that I can distribute research to colleagues without manual formatting.

**Acceptance Criteria:**
- System generates a PDF containing: price snapshot, 2-week forecast, drop alert status, and financial summary.
- PDF saved to a file path returned in the response.
- Report formatted for readability (headers, sections, data tables).

---

**US-7.2 — PDF generated in a single conversational turn**
> As a user, I want to request a PDF with a simple phrase like "generate a PDF report for Salesforce", so that I don't have to navigate multiple steps.

**Acceptance Criteria:**
- Intent classified as `PDF_REPORT` from natural language.
- `pdf_agent` fetches financial data directly via MCP tools (`get-ticker-info`, `ticker-earning`), builds a brief `financial_summary` string, then calls `compile_pdf_report` — all in a single agent turn with no additional user prompting.
- Final response provides the file path and a browser-downloadable link.

---

## Epic 8: Multi-Stock Comparison

**Goal:** Users can compare two or more stocks across quantitative price trends and qualitative 10-K insights in a single query.

---

**US-8.1 — Multi-period price trend comparison**
> As a portfolio manager, I want to compare the 1-week, 1-month, 3-month, 1-year, and 5-year returns of two or more stocks side by side, so that I can evaluate relative performance across timeframes.

**Acceptance Criteria:**
- Query like "compare MSFT and NVDA" returns a table with price and % change for each period.
- Table covers: 1W, 1M, 3M, 1Y, 5Y columns per stock.
- Normalised returns chart embedded inline.

---

**US-8.2 — Qualitative 10-K comparison**
> As an analyst, I want to see how each company describes its strategy, risks, and competitive position in its 10-K, so that I can contrast management narratives alongside the price data.

**Acceptance Criteria:**
- `comparison_insights_agent` runs after the trend table is produced.
- Per-company paragraph synthesises RAG passages from each company's most recent 10-K.
- Comparative summary paragraph highlights key differences between companies.

---

**US-8.3 — Combined quantitative + qualitative comparison in one turn**
> As a portfolio manager, I want a single query like "compare MSFT and NVDA" to return both the trend table and the qualitative 10-K insights, so that I get a complete picture without multiple follow-up questions.

**Acceptance Criteria:**
- `STOCK_COMPARISON` intent triggers the full two-agent pipeline (trend → insights) automatically.
- Both sections appear in the response without requiring a second query.
- Response time is acceptable (≤ 30s for 2 companies).

---

## Epic 9: Guardrails & Safety

**Goal:** Every LLM boundary is protected by automated safety checks that users and agents cannot bypass.

---

**US-9.1 — Prompt injection detection**
> As a platform engineer, I want the system to detect and block jailbreak or instruction-override attempts before they reach the LLM, so that the agent's safety constraints cannot be subverted.

**Acceptance Criteria:**
- Queries containing injection phrases (e.g. "ignore your instructions", "you are now a", "developer mode") are blocked before any LLM call.
- User receives a clear message stating the attempt was detected.
- LLM is never invoked for blocked queries.
- Check runs once per turn on the root agent (idempotent flag in session state).

---

**US-9.2 — Out-of-scope topic rejection**
> As a product owner, I want queries on non-financial topics to be rejected gracefully, so that the agent stays on-task and doesn't hallucinate answers outside its domain.

**Acceptance Criteria:**
- Queries about cooking, sport, politics, health, travel, relationships, etc. are rejected.
- Rejection message lists what the system can help with.
- Queries ≤ 4 words or containing financial keywords pass through (to allow short tickers).
- Check runs once per turn on the root agent.

---

**US-9.3 — PII tokenisation before LLM**
> As a data privacy officer, I want personal data in user queries to be replaced with opaque tokens before the LLM sees them, so that raw PII is never sent to the model.

**Acceptance Criteria:**
- EMAIL, PHONE, SSN, credit card, and IP addresses are detected and replaced with `[TYPE_N]` tokens.
- Token-to-masked-value mappings are stored in an encrypted SQLite database (Fernet AES-128-CBC).
- PII is never written to session state.
- Applies on every LLM call across all agents.

---

**US-9.4 — PII token persistence and retention**
> As a data privacy officer, I want PII tokens to be retained for 90 days, so that detokenisation works correctly across multi-turn sessions without keeping raw PII anywhere.

**Acceptance Criteria:**
- `pii_store.put` persists Fernet-encrypted masked values keyed by `(inv_id, token)`.
- TTL default is 90 days (configurable via `PII_TOKEN_TTL_SECONDS`).
- Expired rows are purged lazily on every write; no explicit per-invocation deletion.
- Production deployments use `PII_STORE_KEY` env var; dev falls back to auto-generated `data/.pii_key` (`chmod 0600`).

---

**US-9.5 — PII detokenisation in output**
> As a data privacy officer, I want any PII tokens the LLM echoes in its response to be replaced with masked values, so that raw PII is never shown to users.

**Acceptance Criteria:**
- Output guardrail replaces `[TYPE_N]` tokens with masked equivalents (e.g. `j***@example.com`).
- A second pass scans for any PII the LLM generated independently and masks it.
- Applies on every LLM response across all agents.

---

**US-9.6 — Token limit enforcement**
> As a platform engineer, I want LLM requests that exceed 20 000 tokens to be blocked, so that I prevent context overflow errors and control costs.

**Acceptance Criteria:**
- Token count estimated from system instruction + all conversation turns + tool responses (chars / 4 heuristic).
- Base64 image data stripped before counting (prevents 50KB chart from inflating estimate by ~12 500 tokens).
- Requests exceeding 20 000 tokens return a user-facing message asking for a shorter or fresh query.
- Applies to root agent and all sub-agents.

---

**US-9.7 — Financial advice disclaimer**
> As a compliance officer, I want the system to automatically prepend a disclaimer when the LLM output contains directive investment advice patterns, so that users are not misled about the nature of the information.

**Acceptance Criteria:**
- Patterns like "you should buy", "I recommend investing in", "guaranteed return", "it will definitely rise" trigger the disclaimer.
- Disclaimer is prepended to the response, not replacing it.
- Applies to all agent outputs.

---

## Epic 10: Observability

**Goal:** Engineering and operations teams have full visibility into agent behaviour, costs, and failures.

---

**US-10.1 — Audit log for every agent interaction**
> As a platform engineer, I want every agent invocation, LLM call, and tool execution to be logged in structured JSON, so that I can debug issues and audit behaviour.

**Acceptance Criteria:**
- `before/after_agent_callback` log agent name, invocation ID, timestamps.
- `before_model_callback` logs model, estimated token count, input summary, conversation history summary.
- `after_model_callback` logs response text, tool calls, finish reason, token usage.
- `before/after_tool_callback` log tool name, arguments, result status, duration.
- Logs written to `audit.log` (JSON lines) and mirrored to stdout.

---

**US-10.2 — LangFuse distributed tracing**
> As a platform engineer, I want every conversation to produce a trace in LangFuse with nested spans for each agent, LLM call, and tool, so that I can visualise latency, cost, and errors end-to-end.

**Acceptance Criteria:**
- Each conversation creates one LangFuse Trace keyed by `invocation_id`.
- Each sub-agent run creates a child Span.
- Each LLM call creates a Generation span (input, output, token counts, cost).
- Each tool call creates a tool Span (args, result).
- Trace is flushed when the root orchestrator finishes.
- If LangFuse is unavailable, agent degrades gracefully; in-process metrics still collected.

---

**US-10.3 — In-process metrics collection for eval**
> As a quality engineer, I want tool span outcomes and token usage to be collected in-process regardless of LangFuse availability, so that the evaluation framework can compute metrics without a cloud dependency.

**Acceptance Criteria:**
- `tracing._metrics[inv_id]` accumulates tool spans (name + succeeded flag) and cumulative token usage.
- `get_run_metrics(inv_id)` returns and pops the metrics for a completed invocation.
- `transfer_to_agent` spans are excluded (internal routing, not a domain tool).
- Success is determined by absence of `{"status": "error"}` in the tool response.

---

## Epic 11: Evaluation Framework

**Goal:** Product and engineering teams can measure system quality across three levels — model, product, and business — with a single CLI command.

---

**US-11.1 — Intent extraction accuracy measurement**
> As a quality engineer, I want to run the 33 intent test cases and see a pass rate, so that I can detect regressions in the intent agent's classification.

**Acceptance Criteria:**
- Each test case specifies a query, expected intent label, and expected entities.
- Eval harness calls Gemini directly (bypasses ADK) for speed.
- Reports number passed, failed, and accuracy %.

---

**US-11.2 — End-to-end pipeline evaluation**
> As a quality engineer, I want to run the 22 E2E test cases against the live ADK agent and measure tool selection, response content, and latency, so that I can detect regressions in the full pipeline.

**Acceptance Criteria:**
- Each test case specifies a query, expected keywords in the response, and expected tool calls.
- Eval harness patches `after_tool_callback` on all agents to capture tool call names.
- `__routing__` and `__progress__` events are filtered from captured response text before RAGAS evaluation; only user-facing agent output is assessed.
- `RunResult` records: response text, tool calls, latency, invocation ID.
- Test cases with `category="guardrail"` are excluded from violation rate counting.
- Test cases are defined in `eval/cases.py` (22 E2E cases covering all 13 intent routes + 3 guardrail checks + 3 compound pipelines + 4 edge cases).

---

**US-11.3 — Three-level metrics dashboard**
> As a product manager, I want to see Level 1 (model quality), Level 2 (product), and Level 3 (business) metrics in a single dashboard, so that I can assess quality from model benchmarks to business ROI in one view.

**Acceptance Criteria:**
- **L1:** Action Success Rate ≥ 95%, Tool Select Accuracy ≥ 85%, Hallucination Rate ≤ 5%, Context Utilisation ≤ 70%, Guardrail Violation Rate ≤ 2%
- **L2:** Containment Rate ≥ 90%, Task Completion Rate ≥ 80%, Response Confidence ≥ 0.7, Response Latency ≤ 10 000 ms
- **L3:** Cost per Task ≤ $0.05, displayed alongside productivity gain and cost savings vs. analyst baseline
- Each metric shows pass/fail against its threshold.
- Dashboard rendered as ASCII box-drawing output in the terminal.
- Results also saved as JSON + Markdown to `eval/results/`.

---

**US-11.4 — Configurable thresholds**
> As a quality engineer, I want to override pass/fail thresholds via a YAML file, so that I can tune acceptance criteria without changing code.

**Acceptance Criteria:**
- Default thresholds defined in `eval/thresholds.yaml`.
- `--thresholds` CLI flag accepts a custom YAML file path.
- Metrics with `null` threshold always display the value but never fail.

---

**US-11.5 — Per-case RAGAS thresholds**
> As a quality engineer, I want each E2E test case to carry its own RAGAS pass/fail thresholds, so that static 10-K cases can be held to strict factual correctness standards while live-data cases use achievable levels without inflating the overall pass rate.

**Acceptance Criteria:**
- Every `E2ECase` in `cases.py` has an optional `ragas_thresholds: RagasThresholds(factual_correctness, answer_relevancy, faithfulness)`.
- Thresholds are calibrated per case type:
  - Static 10-K / filing cases: `factual_correctness ≥ 0.50` (text indexed verbatim, NLI can match reliably).
  - Live financial data cases: `factual_correctness ≥ 0.25` (yfinance figures shift; NLI matching of approximate numbers is noisy).
  - Forecast / trade signal cases: FC omitted (future prices cannot be verified against a static reference).
  - Guardrail / edge cases: all thresholds set to 0.00 or omitted (non-factual response type).
- A case with no threshold for a given metric always passes that metric (the score is still displayed).
- The eval dashboard clearly marks each case's per-metric pass/fail alongside the score.

---

## Epic 12: Ticker & Company Resolution

**Goal:** Users can refer to companies by name or ticker interchangeably, and the system resolves to a canonical symbol.

---

**US-12.1 — Name-to-ticker resolution**
> As a user, I want to refer to companies by their common name (e.g. "Snowflake", "Salesforce"), so that I don't need to remember ticker symbols.

**Acceptance Criteria:**
- Built-in resolver maps 40+ common software/tech company names to canonical tickers.
- Resolution is case-insensitive.
- If no mapping exists, the input is uppercased and passed through as-is (best-effort).

---

**US-12.2 — Intent-level entity extraction**
> As a system, I want the `intent_agent` to extract all company names from the user's query and map them to tickers, so that downstream agents receive normalised symbols without needing their own resolution logic.

**Acceptance Criteria:**
- `intent_agent` returns a `companies` array in its JSON output with resolved tickers.
- Multiple companies in a single query are all extracted.
- Resolution uses model knowledge for names not in the built-in dictionary.

---

## Epic 13: Future Capabilities (Backlog)

> Stories in this epic are scoped for future sprints and are not part of the current release.

---

**US-13.1 — Scheduled drop alerts**
> As an investor, I want to subscribe to automated drop alerts that notify me when a stock falls beyond my threshold, so that I don't have to manually check the system each day.

**Acceptance Criteria:**
- User can set a recurring alert (daily, market open/close).
- Notifications delivered via email or Slack integration.
- Alerts persist across sessions.

---

**US-13.2 — Backtesting forecast accuracy**
> As an analyst, I want to see how accurate past forecasts were against actual prices, so that I can calibrate my trust in the prediction model.

**Acceptance Criteria:**
- System can compare a historical forecast against realised prices.
- Reports RMSE or MAPE accuracy metric alongside a chart.

---

**US-13.3 — Portfolio-level aggregation**
> As a portfolio manager, I want to input my holdings and get an aggregate view of portfolio performance, correlations, and risk exposure, so that I can manage at the portfolio level rather than stock by stock.

**Acceptance Criteria:**
- User provides a list of tickers and weights.
- System returns weighted return, portfolio daily P&L, and correlation matrix.

> **Note:** (Basic mock portfolio tracking implemented in Epic 14; this story covers real positions, correlation matrix, and weighted returns)

---

**US-13.4 — Expanded 10-K coverage**
> As an analyst, I want to query 10-K filings for any US-listed company (not just a pre-indexed set), so that I'm not limited by which companies were manually ingested.

**Acceptance Criteria:**
- System auto-ingests 10-K from EDGAR when a company is queried for the first time.
- Ingestion is asynchronous; user is notified when the index is ready.

---

**US-13.5 — Conversational memory across sessions**
> As a returning user, I want the system to remember my preferred companies and alert thresholds from previous sessions, so that I don't have to repeat my preferences every time.

**Acceptance Criteria:**
- User preferences (watchlist, thresholds, default companies) are persisted in a user profile store.
- Subsequent sessions load preferences automatically.
- User can explicitly update or clear preferences.

---

## Epic 14: Mock Paper Trading

**Goal:** Users can request data-driven trade recommendations, approve them through a two-turn human-in-the-loop flow, and track their mock portfolio — all without risking real capital.

---

**US-14.1 — Trade signal analysis**
> As an active trader, I want to ask "Should I buy NVDA?" and receive a data-driven BUY/SELL/HOLD recommendation with confidence score, so that I can make informed trading decisions.

**Acceptance Criteria:**
- System fetches current price, 14-day OLS forecast return, analyst consensus, and analyst price target from yfinance.
- Signal score computed: 40% forecast component + 40% analyst consensus + 20% price-target upside.
- BUY if score ≥ 0.3, SELL if ≤ -0.3, HOLD otherwise; confidence % = min(|score| × 100, 100).
- Recommendation card shows: current price, forecast return, analyst consensus, signal score, suggested order (shares × price = notional).
- Disclaimer always included: "Not investment advice. For informational purposes only."

---

**US-14.2 — Human-in-the-loop trade approval**
> As a trader, I want to explicitly approve a trade recommendation before it executes, so that the system never places a trade without my confirmed consent.

**Acceptance Criteria:**
- After presenting a recommendation, the agent asks "Reply yes to execute or no to cancel".
- Pending trade stored in-memory keyed by session_id.
- On "yes": trade executed, written to trades.jsonl with unique trade ID (TRD-YYYYMMDD-XXXXXX).
- On "no"/"cancel": pending trade cleared, cancellation confirmed.
- If user replies with a different share count (e.g. "10 shares instead"), agent calls `update_pending_trade_shares`, revises the notional, and re-presents the updated trade summary for final approval.
- If user sends an unrelated message while a trade is pending, agent reminds them of the pending trade.
- Orchestrator bypasses intent classification on the approval turn — bare "yes" goes directly to trading_agent.
- **RBAC gate:** before routing to `trading_agent` on the approval turn, the orchestrator checks `is_allowed(role, "TRADE_ANALYSIS")`; viewer-role users receive a permission-denied message and the pending trade is cancelled (analyst and admin roles only).

---

**US-14.3 — Mock trade execution and confirmation**
> As a trader, I want to receive a clear confirmation when a mock trade executes, including trade ID, ticker, action, shares, price, and notional, so that I have a record of what was executed.

**Acceptance Criteria:**
- Confirmation card shows: Trade ID, Action (BUY/SELL), Ticker, Shares, Price, Notional (mock).
- Trade record written to trades.jsonl with timestamp, session_id, reasoning.
- Pending trade state cleared after execution.
- Disclaimer included on confirmation.

---

**US-14.4 — Portfolio view**
> As a trader, I want to type "show portfolio" and see all my current mock positions, so that I can track what I've accumulated across multiple trades.

**Acceptance Criteria:**
- System reads trades.jsonl and aggregates BUY/SELL into net positions per ticker.
- Shows: ticker, shares held, average cost per share, total invested.
- Positions with 0 shares (fully sold) are omitted.
- If no trades yet, clearly states the portfolio is empty.

---

**US-14.5 — Trade history**
> As a trader, I want to view my recent mock trade history, so that I can review past decisions.

**Acceptance Criteria:**
- "Trade history" or "past trades" returns the last 10 executed trades (configurable up to 50).
- Shows: trade ID, ticker, action, shares, price, notional, executed_at.
- Most recent trade shown first.

---

## Epic 15: Platform Reliability & Compliance

**Goal:** The platform satisfies financial services audit requirements and degrades gracefully under dependency failures, while keeping API costs within budget.

---

**US-15.1 — Compliance audit log with retention**
> As a compliance officer, I want every agent interaction logged with user identity and session, retained for 90 days with automatic compression, so that I can satisfy financial services audit requirements.

**Acceptance Criteria:**
- Every audit entry includes session_id and user_id.
- Logs rotate daily; previous day's log is gzip-compressed automatically.
- 90 days of logs retained; older logs deleted automatically.
- Logs written to audit.log (JSON lines) with daily rotation handler.

---

**US-15.2 — Mandatory financial disclaimer tracking**
> As a compliance officer, I want the system to detect when a financial agent response omits the required disclaimer and log it as a compliance event, so that I can identify and remediate gaps.

**Acceptance Criteria:**
- 9 financial agents required to include one of: "not investment advice", "informational purposes only", "not a licensed financial advisor", "consult a licensed financial advisor".
- After every text response from these agents, disclaimer presence is checked.
- If absent: `disclaimer_missing` event emitted to audit log; `disclaimer: "missing"` recorded on the llm_response entry.
- If present: `disclaimer: "present"` recorded.

---

**US-15.3 — Circuit breakers for external services**
> As a platform engineer, I want external service failures to trigger a circuit breaker that returns graceful error responses instead of hanging, so that one failing dependency doesn't cascade into a system-wide outage.

**Acceptance Criteria:**
- Three breakers: Gemini LLM (5 failures/30s cooldown), Yahoo Finance MCP (5 failures/30s), A2A server (3 failures/60s).
- CLOSED: normal; OPEN: immediate graceful error; HALF_OPEN: one probe allowed after cooldown.
- Gemini open → LlmResponse with "temporarily unable to reach AI service" message.
- Yahoo open → error dict "market data temporarily unavailable".
- A2A open → error dict "financial report service temporarily unavailable".
- `circuit_open` event emitted to audit log when a breaker fires.

---

**US-15.4 — Cost tracking and monthly spend alert**
> As a platform operator, I want to see cost per LLM call logged and receive a warning when monthly spend approaches the configured limit, so that I can control API costs.

**Acceptance Criteria:**
- Every LLM response appended to cost.jsonl: agent, model, input_tokens, output_tokens, cost_usd.
- `python -m stock_agent.cost_report` shows spend breakdown by day and by agent.
- At startup, system reads cost.jsonl and sums current month's spend.
- Warning at ≥80% of MONTHLY_SPEND_LIMIT_USD (yellow), alert at ≥100% (red).
- Default limit configurable via environment variable.

---

## Epic 16: Prompt & Model Management

**Goal:** ML engineers can version, swap, and gate-test agent prompts without touching application code.

---

**US-16.1 — Versioned prompt files**
> As an ML engineer, I want each agent's system prompt stored in a versioned Markdown file, so that I can compare versions, roll back to a previous prompt, and track changes in version control.

**Acceptance Criteria:**
- All 13 agent prompts stored as `prompts/{agent_name}_v{n}.md`.
- Loaded at startup via `load_prompt(agent_name, version)` in prompt_loader.py.
- Changing version number in the agent file switches the active prompt.
- Missing prompt file raises FileNotFoundError with a clear message.

---

**US-16.2 — Per-agent output token budgets**
> As a platform engineer, I want each agent to have a configurable maximum output token limit, so that I can prevent runaway responses from burning quota while allowing complex agents more headroom.

**Acceptance Criteria:**
- Token limits defined in model_config.py per agent (e.g. intent_agent=500, trading_agent=1024, tenk_agent=3000).
- Injected into every LlmRequest.config via before_model_callback.
- Logged in each llm_request audit entry.
- Default of 2048 applied for any agent not in the config.

---

**US-16.3 — Eval regression gate**
> As an ML engineer, I want to run `python -m eval.run_eval --gate` before merging prompt changes, so that I'm alerted if a change regresses any quality metric below its threshold.

**Acceptance Criteria:**
- `--gate` flag checks all thresholds in eval/thresholds.yaml.
- Exits with code 1 if any metric regresses; exit 0 if all pass.
- Prints a clear PASS/FAIL summary listing each metric, its value, and its threshold.
- Covers: intent_accuracy, action_success_rate, tool_select_accuracy, hallucination_rate, context_utilization, guardrail_violation_rate, containment_rate, task_complete_rate, user_confidence_score, response_latency_ms, cost_per_task_usd.

---

## Epic 17: FinanceAI Branding & UI Experience

**Goal:** Establish a coherent FinanceAI brand identity and improve the overall user experience of the web application.

---

**US-17.1 — FinanceAI brand identity**
> As a user, I want the application to present a professional, recognisable brand so that it feels like a polished product rather than a development prototype.

**Acceptance Criteria:**
- Browser tab displays "FinanceAI" as the page title.
- Browser tab shows the FinanceAI favicon (blue diamond + trend line, SVG, 48×48).
- The FinanceAI logo (horizontal lockup: blue diamond icon + gold "FinanceAI" wordmark) appears on the login screen and in the sidebar header.
- Logo and favicon are pure SVG files served from `/static/` — no raster images for icons.

---

**US-17.2 — Split-screen login page**
> As a first-time visitor, I want the login screen to feel professional and visually engaging, so that the product makes a strong first impression.

**Acceptance Criteria:**
- Login page splits into two panels: a full-height trading-chart photo on the left and a form panel (400px fixed width) on the right.
- Photo is desaturated and darkened via CSS `filter: saturate() brightness()` with a dark right-to-left gradient overlay to ensure legibility.
- The right panel contains the FinanceAI logo, a "Welcome back" heading, and username/password fields.
- Layout is purely CSS `display:flex` — no JavaScript.
- Photo is served as a static file at `/static/bull.jpg`.

---

**US-17.3 — Resizable sidebar**
> As a user who opens many sessions, I want to drag the sidebar wider or narrower so that long session titles are readable and I can give more space to the chat area.

**Acceptance Criteria:**
- A 5px drag handle (`#sidebar-resizer`) sits between the sidebar and the main area.
- Dragging adjusts sidebar width between 160px and 480px.
- Width preference is persisted in `localStorage` and restored on page load.
- CSS `transition` is disabled during drag (re-enabled on release) to prevent animation lag.
- Cursor changes to `col-resize` when hovering the handle.

---

**US-17.4 — Session keyword search**
> As a user with many sessions, I want to type a keyword and see only sessions whose titles match, so that I can quickly navigate to a past conversation.

**Acceptance Criteria:**
- A search input appears at the top of the session list.
- Typing filters sessions in real time (no submit required).
- Matching substring is highlighted with a `<mark>` element inside the session title.
- Sessions with no match are hidden; a "no results" state is shown if nothing matches.
- Clearing the search restores the full session list.

---

**US-17.5 — Session deletion**
> As a user, I want to delete sessions I no longer need, so that my session list stays manageable.

**Acceptance Criteria:**
- An ✕ button appears on hover over a session item in the sidebar.
- Clicking ✕ opens a styled confirmation dialog (matching the app's dark theme).
- Confirming deletes the session from the server (`DELETE /api/sessions/{id}`) and removes it from the sidebar.
- The server verifies ownership before deleting — a user cannot delete another user's session.
- If the deleted session was active, the chat area clears and no session is selected.

---

**US-17.6 — Sign-out footer with user identity**
> As a user, I want to always see who I'm logged in as and have a clear sign-out action at the bottom of the sidebar, so that I can confirm my identity and switch accounts easily.

**Acceptance Criteria:**
- The sidebar footer shows: an avatar circle (first letter of username), the username, and a "Role: \<role\>" label.
- Name and role are displayed on the same line without overlapping (flexbox with `justify-content: space-between`).
- A full-width "Sign out" button with a red hover state is placed below the user info.
- Signing out clears the JWT token, session list, chat area, and any displayed username.

---

## Epic 18: Client-Side Trading History

**Goal:** Users can maintain a personal log of their trading activity (real or simulated) directly in the application without requiring a backend.

---

**US-18.0 — Role-based tab visibility**
> As a platform administrator, I want the Trading History and Analytics tabs to be visible only to analyst and admin users, so that viewer-role users cannot access trading or portfolio data.

**Acceptance Criteria:**
- After login, `_showApp()` reads the JWT-decoded `role` field.
- If `role === 'analyst'` or `role === 'admin'`: Trading History and Analytics tabs are displayed normally.
- If `role === 'viewer'` (or any other role): the `#tab-trades` and `#tab-analytics` elements are hidden via `display: none`; the active tab is forced to Chat.
- A viewer who types a trade-approval message ("yes", "buy") while a pending trade exists receives a permission-denied error from the backend; the pending trade is cancelled.
- Tab visibility is re-evaluated on every login; role changes take effect on next sign-in.

---

**US-18.1 — Trading History tab**
> As a trader, I want a dedicated tab for my trade records so that they are clearly separated from the AI chat conversation.

**Acceptance Criteria:**
- The main area has two tabs: "Chat" and "Trading History".
- Switching tabs preserves the current chat state — no messages are lost.
- The active tab is visually distinguished from the inactive tab.

---

**US-18.2 — View trade ledger**
> As a trader, I want to see all my past transactions in a table so that I have a complete record of my activity.

**Acceptance Criteria:**
- The Trading History tab displays a table with columns: Date, Symbol, Type, Qty, Price ($), Total ($), Notes.
- BUY trades show a green badge; SELL trades show a red badge.
- Transactions are sorted newest-first.
- The table scrolls independently of the tab bar and toolbar.
- If no trades exist, an empty state message is shown.

---

**US-18.3 — Add transaction**
> As a trader, I want to manually record a transaction so that I can keep my ledger up to date.

**Acceptance Criteria:**
- An "Add Transaction" button opens a modal form.
- The form captures: Date (default today), Symbol (uppercase, required), Type (BUY/SELL dropdown), Qty (positive number), Price per share ($), Notes (optional).
- Saving the form appends the transaction to the ledger, closes the modal, and refreshes the table.
- The modal can be dismissed without saving via Cancel or clicking the overlay.

---

**US-18.4 — Per-user persistence**
> As a user sharing the application with others, I want my trade records to be private to my account so that other users cannot see or modify them.

**Acceptance Criteria:**
- Trades are stored in `localStorage` under the key `trades_{username}`.
- Logging in as a different user shows that user's own trades (or an empty ledger if none).
- Logging out clears the displayed trades.
- New users start with an empty ledger (no pre-seeded sample data — seeding caused all accounts to show identical trades on first login).

---

## Epic 19: Portfolio Analytics Dashboard

**Goal:** Users can see a live, data-driven overview of their portfolio's value, composition, and performance without leaving the application.

---

**US-19.1 — Portfolio summary cards**
> As a trader, I want four at-a-glance cards showing total portfolio value, cash balance, number of open positions, and unrealised P&L, so that I can assess my portfolio health in seconds.

**Acceptance Criteria:**
- Cards display: Total Portfolio ($), Cash ($), Open Positions (count), Unrealised P&L ($ and %).
- Values are computed from the localStorage trade ledger plus live prices from `GET /api/prices`.
- Starting virtual cash is $100,000; BUY trades reduce it, SELL trades increase it.
- P&L card shows green for positive, red for negative.
- All values refresh when the user opens the Analytics tab or clicks "⟳ Refresh".

---

**US-19.2 — Asset allocation chart**
> As a trader, I want a doughnut chart showing how my portfolio is split between cash and individual stock holdings, so that I can immediately see concentration risk.

**Acceptance Criteria:**
- Doughnut chart segments: Cash + one segment per held ticker.
- Segment size reflects current market value (shares × current price), not cost basis.
- Hovering a segment shows: label, market value, and percentage of total.
- Legend is displayed below the chart.
- Chart re-renders cleanly on each refresh (old Chart.js instance destroyed before creating a new one).

---

**US-19.3 — Holdings table**
> As a trader, I want a table of all my open positions with cost basis, current price, and gain/loss, so that I can evaluate each holding individually.

**Acceptance Criteria:**
- Columns: Symbol · Shares · Avg Cost · Current Price · Market Value · Gain/Loss · %.
- Gain/Loss and % columns show green for profit, red for loss.
- Positions with zero net shares (fully sold) are excluded.
- If there are no open positions, a clear empty-state message is shown instead of the table.

---

**US-19.4 — Current price cards**
> As a trader, I want a card for each of my held stocks showing today's price and daily change, so that I can quickly gauge intra-day movement.

**Acceptance Criteria:**
- One card per held ticker, showing: symbol, current price, daily change $ and %.
- Up moves shown in green with ▲; down moves in red with ▼.
- Cards are hidden if there are no open positions.
- Price data sourced from `GET /api/prices` (yfinance snapshot).

---

**US-19.5 — Portfolio value trend chart**
> As a trader, I want to see how the total value of my portfolio has changed over the past 3 months, so that I can judge overall performance over time.

**Acceptance Criteria:**
- Area line chart showing daily total portfolio value for the past 3 months.
- Value at each date is computed by replaying the trade history up to that date and multiplying net shares by the closing price from `GET /api/price-history`.
- Cash position changes with each trade are included.
- Y-axis shows dollar values; X-axis shows dates (up to 8 tick labels).
- If no price history is available (no positions), the chart is not rendered.

---

**US-19.6 — Individual stock trend charts**
> As a trader, I want to see each held stock's price history on a single multi-line chart, so that I can compare performance across my positions.

**Acceptance Criteria:**
- Multi-line Chart.js line chart, one line per held ticker.
- Each line uses a distinct colour from the palette.
- Shared x-axis (calendar dates); y-axis shows price in USD.
- Interactive tooltip shows all tickers' prices for a hovered date.
- Chart is hidden if there are no open positions.
- Section is labelled "Individual Stock Prices — 3-Month Trend".

---

## Epic 20: Knowledge Graph Ingestion (LightRAG)

**Goal:** A growing entity+relationship knowledge graph over SEC filings enables cross-company, context-aware investment research that goes beyond keyword similarity.

---

**US-20.1 — Ingest annual filings into knowledge graph**
> As an ML engineer, I want SEC annual filings (10-K / 20-F) to be ingested into the LightRAG knowledge graph, so that the `investment_research_agent` can answer cross-company questions using entity and relationship context.

**Acceptance Criteria:**
- Filings are downloaded from SEC EDGAR and converted to clean text (BeautifulSoup HTML → plain text).
- Text is chunked and passed to `rag.ainsert()` for entity/relationship extraction (Gemini 2.5 Flash LLM).
- Ingested filing is recorded in `lightrag_storage/manifest.jsonl` with ticker, filing type, fiscal year, and chunk count.
- Chunks that time out during entity extraction are logged as failures in the manifest; the remaining chunks are still indexed.
- Re-running ingestion for a previously indexed filing skips it (idempotent).

---

**US-20.2 — Ingest quarterly filings into knowledge graph**
> As an ML engineer, I want quarterly filings (10-Q / 6-K) to also be ingested, so that recent financials and disclosures are reflected in the knowledge graph alongside the annual report.

**Acceptance Criteria:**
- 6-K and 10-Q filings are downloaded and ingested using the same pipeline as US-20.1.
- Fiscal period (e.g. "Q1 FY2026") is captured in the manifest entry.
- Quarterly filings are lower priority than annual; ingestion is additive (does not replace annual entries).

---

**US-20.3 — Multi-company knowledge graph coverage**
> As an analyst, I want the knowledge graph to cover both US domestic (10-K) and foreign private issuer (20-F) companies, so that I can run cross-company queries across a diverse set of software/tech names.

**Acceptance Criteria:**
- MSFT 10-K and SAP 20-F/6-K (FY2023–2025, 10 filings) are indexed as the initial corpus.
- Coverage can be extended by running the ingestion script for additional companies.
- `query_investment_research` returns results citing entities and relationships from across all indexed companies.
- If the knowledge graph is empty or lacks relevant content, the agent states the limitation rather than hallucinating.

---

**US-20.4 — Investment research query interface**
> As an analyst, I want to ask questions like "Compare SAP and Microsoft's cloud strategy based on their filings" and receive an answer synthesised from the knowledge graph, so that I get cross-company insights rather than a single-filing summary.

**Acceptance Criteria:**
- Query classified as `INVESTMENT_RESEARCH` routes to `investment_research_agent`.
- Agent calls `query_investment_research(query, mode)` where `mode` can be `hybrid`, `global`, or `local`.
- Response includes entity-level context (companies, products, strategies, risks) derived from the graph.
- Disclaimer included: "Based on indexed SEC filings; not investment advice."
