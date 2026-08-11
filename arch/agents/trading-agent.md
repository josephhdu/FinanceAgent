# Trading Agent

## Overview

The trading agent is a mock brokerage interface layered on top of the stock analysis system. It pulls real signal data from yfinance and analyst ratings, computes a composite signal score, and then guides the user through a two-turn approval flow: turn one produces a recommendation and stages a pending trade in memory; turn two executes or cancels it. All trade records are appended to a local `trades.jsonl` file for persistence and audit. No real money moves — broker API calls and order routing are intentionally mocked, making this suitable for local simulation and strategy back-testing without connecting to a live brokerage.

---

## Configuration

| Field                | Value                                                        |
|----------------------|--------------------------------------------------------------|
| Name                 | `trading_agent`                                              |
| Model                | `gemini-2.5-flash`                                           |
| Max output tokens    | 1024 (set in `model_config.py`)                              |
| Registered in        | `stock_agent/trading_agent.py`                               |
| Tools module         | `stock_agent/trade_tools.py`                                 |
| System prompt        | `prompts/trading_agent_v1.md`                                |
| Disclaimer required  | Yes — added to `_DISCLAIMER_REQUIRED_AGENTS` in `audit.py`  |
| Intent class         | `TRADE_ANALYSIS`                                             |

---

## Two-Turn Approval Flow

The orchestrator implements a bypass that short-circuits intent classification whenever a pending trade exists for the current session. This prevents the user's one-word "yes" or "no" from being misclassified.

```
Turn 1 — Recommendation
────────────────────────

User ──► orchestrator (agent.py)
              │
              │  has_pending_trade()? → NO
              │
              ▼
         intent_agent
              │  classifies: TRADE_ANALYSIS
              ▼
         trading_agent
              │
              ├─► get_pending_trade()        → none
              ├─► get_trade_signals(ticker)  → signal_score, action, confidence_pct
              ├─► store_pending_trade(...)   → staged in _pending_trades[session_id]
              │
              └─► LLM outputs recommendation with yes/no prompt


Turn 2 — Execution or Cancellation
────────────────────────────────────

User ──► orchestrator (agent.py)
              │
              │  has_pending_trade()? → YES  ← bypass: skips intent_agent
              │
              │  RBAC check: is_allowed(role, "TRADE_ANALYSIS")?
              │    NO  → cancel_pending_trade() + forbidden_event (role denied)
              │    YES ↓
              ▼
         trading_agent
              │
              ├─► get_pending_trade()         → retrieves staged trade
              │
              ├── if user said "yes":
              │       execute_pending_trade() → pops from _pending_trades
              │                               → appends to trades.jsonl
              │                               → returns trade_id TRD-YYYYMMDD-XXXXXX
              │
              └── if user said "no":
                      cancel_pending_trade()  → pops from _pending_trades, no write
```

**Orchestrator bypass code pattern (agent.py):**

```python
if has_pending_trade():
    if not is_allowed(ctx.session.state.get("user_role", "viewer"), "TRADE_ANALYSIS"):
        cancel_pending_trade()
        yield forbidden_event(ctx, "TRADE_ANALYSIS")
        return
    async for event in trading_agent.run_async(ctx):
        yield event
    return
# only then run intent_agent
```

---

## Signal Scoring

### Formula

| Component         | Formula                                          | Weight |
|-------------------|--------------------------------------------------|--------|
| `forecast_score`  | `clamp(forecast_return_14d_pct / 10.0, -1, 1)`  | 0.4    |
| `analyst_score`   | mapped from `recommendationKey` (see table below)| 0.4    |
| `upside_score`    | `clamp(upside_to_target_pct / 20.0, -1, 1)`     | 0.2    |
| **`signal_score`**| `0.4×forecast_score + 0.4×analyst_score + 0.2×upside_score` | — |

### Decision thresholds

| Condition                  | Action  |
|----------------------------|---------|
| `signal_score >= 0.3`      | BUY     |
| `signal_score <= -0.3`     | SELL    |
| otherwise                  | HOLD    |

`confidence_pct = min(|signal_score| × 100, 100)`

### Analyst score mapping

| `recommendationKey` | `analyst_score` |
|---------------------|-----------------|
| `strong_buy`        | 1.0             |
| `buy`               | 0.7             |
| `outperform`        | 0.6             |
| `hold`              | 0.0             |
| `underperform`      | -0.6            |
| `sell`              | -0.7            |
| `strong_sell`       | -1.0            |

All three input scores are clamped to `[-1, 1]` before weighting so that a single extreme data point cannot dominate the composite.

---

## Tool Descriptions

| Tool | Signature | Description |
|------|-----------|-------------|
| `get_trade_signals` | `(ticker: str) -> dict` | Fetches yfinance price history (OLS 14-day forecast return) and analyst consensus (`recommendationKey`, `targetMeanPrice`). Computes `signal_score` and returns `action` (BUY/SELL/HOLD), `confidence_pct`, and the raw sub-scores. |
| `get_pending_trade` | `() -> dict \| None` | Reads `_pending_trades[session_id]` via the `audit_session_id` ContextVar. Returns the staged trade dict or `None` if none exists. |
| `store_pending_trade` | `(ticker, action, shares, price, reasoning) -> None` | Writes a trade proposal into `_pending_trades[session_id]`. Overwrites any previously staged trade for the same session. |
| `execute_pending_trade` | `() -> dict` | Pops the pending trade, appends it to `trades.jsonl` with a generated `trade_id` (`TRD-YYYYMMDD-XXXXXX`), and returns the confirmation dict. |
| `cancel_pending_trade` | `() -> None` | Pops the pending trade without writing to `trades.jsonl`. |
| `get_portfolio` | `() -> dict` | Reads all of `trades.jsonl` and aggregates BUY/SELL lines into current positions (shares held per ticker). |
| `get_trade_history` | `(limit: int) -> list[dict]` | Returns the last `limit` trades from `trades.jsonl`, most recent first. |

**Suggested notional size:** ~$2,000 per trade. `shares = max(1, floor(2000 / price))`.

---

## Pending Trade Lifecycle

```
[NONE]
   │
   │  store_pending_trade(...)
   ▼
[PENDING]  ──  session_id key exists in _pending_trades
   │
   ├──── execute_pending_trade() ──► [EXECUTED]  →  appended to trades.jsonl
   │                                               trade_id returned
   │
   └──── cancel_pending_trade()  ──► [CANCELLED] →  no write, key removed
```

The `[PENDING]` state is in-memory only (`_pending_trades` dict in `trade_tools.py`). It does not survive a server restart, which is acceptable for local/simulation use. The `[EXECUTED]` state is durable — `trades.jsonl` is append-only and is the single source of truth for portfolio and history queries.

---

## What's Mocked vs Real

| Real | Mocked |
|------|--------|
| Signal data — yfinance closing prices, analyst ratings | Broker API and order routing |
| OLS 14-day forecast return | Real money movement |
| Trade records persisted to `trades.jsonl` | Bid/ask spread and slippage |
| Audit log of every recommendation and execution | Margin and buying-power checks |
| Disclaimer enforcement via `_DISCLAIMER_REQUIRED_AGENTS` | Regulatory reporting |
| Portfolio aggregation from `trades.jsonl` | Settlement and clearing |

---

## Integration Points

### Orchestrator (`stock_agent/agent.py`)

Three changes were made:

1. **Pending-trade bypass with RBAC** — before the intent routing block, `has_pending_trade()` is evaluated. If true, an RBAC check runs first: if the current role does not have `TRADE_ANALYSIS` permission, the pending trade is cancelled and a `forbidden_event` is returned. Only if the role is authorised does the request go directly to `trading_agent`, bypassing `intent_agent`.
2. **`_ROUTE_MAP`** — `TRADE_ANALYSIS` is added as a key mapping to `trading_agent`.
3. **`sub_agents` list** — `trading_agent` is registered so ADK discovers it.

### Intent Agent (`prompts/intent_agent_v1.md`)

`TRADE_ANALYSIS` is added as the highest-priority classification rule so that any phrasing involving buying, selling, portfolio, or trade history routes to the trading agent before other intents are considered.

### Audit (`stock_agent/audit.py`)

`trading_agent` is added to `_DISCLAIMER_REQUIRED_AGENTS`. This ensures every response from the trading agent is checked for the required investment-risk disclaimer before being delivered to the user.

### Model config (`stock_agent/model_config.py`)

`trading_agent: 1024` caps the output token budget. Trade recommendations are structured and short; the limit prevents runaway generation.

### Session identity

The `audit_session_id` ContextVar (set by the orchestrator at request entry) is used as the dictionary key for `_pending_trades`. This means pending trades are scoped to a single user session and do not leak across concurrent requests.

### Web server — signal badge (`web_server.py`)

When `get_trade_signals` returns a successful response, the web server captures `ticker`, `recommendation`, `signal_score`, and `confidence_pct` into a `_current_signals` ContextVar list (the same mechanism used for chart images). The `_stream()` generator flushes these as a `{"type":"signal",...}` SSE event **before** the first text token, so the browser can render a structured badge above the LLM prose.

```
get_trade_signals returns →  _patch_for_image_capture captures signal data
                          →  _stream() yields {"type":"signal","ticker":"MSFT",
                                               "recommendation":"BUY",
                                               "signal_score":0.605,
                                               "confidence_pct":60.5}
                          →  browser renders badge: [BUY] MSFT  ████░ 61%
                          →  LLM text tokens arrive below badge
```

The badge (`.signal-badge` in `static/index.html`) shows:
- A coloured pill: green for BUY, red for SELL, grey for HOLD
- Ticker symbol and raw signal score
- A confidence bar (width = `confidence_pct%`) with percentage label

The LLM response text still includes the signal score inline (per the `trading_agent_v1.md` template), so the information is present whether the badge renders or not.

---

## Future Extension: Replacing the Mock with a Real Broker

The mock boundary is entirely contained within `execute_pending_trade()` in `trade_tools.py`. To connect a real broker:

1. **Swap `execute_pending_trade`** — replace the `trades.jsonl` append with an authenticated call to the broker REST API (e.g. Alpaca `POST /v2/orders`, Interactive Brokers TWS API, or Schwab `POST /trader/v1/accounts/{accountHash}/orders`).
2. **Add buying-power check** — call `get_portfolio()` and a broker account-balance endpoint before `store_pending_trade` to validate that the trade is feasible.
3. **Persist order IDs** — store the broker-returned order ID alongside the internal `trade_id` in `trades.jsonl` for reconciliation.
4. **Add order-status polling** — introduce a `get_order_status(trade_id)` tool that queries the broker for fill status, enabling a third confirmation turn.
5. **Margin and risk controls** — add a pre-execution circuit-breaker that rejects orders exceeding a configurable notional limit or position concentration threshold.
6. **Secret management** — broker credentials should be loaded from environment variables or a secrets manager, never hard-coded. The `model_config.py` pattern used for token limits can be extended to hold broker endpoint configuration.

No changes to `trading_agent.py`, `agent.py`, or the prompt are required for steps 1–3; the agent only observes the return value of the tool, not how the tool executes the trade.
