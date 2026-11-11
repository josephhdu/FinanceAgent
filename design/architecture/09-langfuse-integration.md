# LangFuse Integration

## Overview

`stock_agent/tracing.py` provides two functions:

1. **LangFuse observability** — sends structured trace/span/generation data to the LangFuse cloud dashboard (optional, enabled by environment variables)
2. **In-process eval metrics** — collects tool spans and token usage in memory regardless of whether LangFuse is configured (always on)

The split design means evaluation always works even without LangFuse credentials, while production deployments get full observability when credentials are present.

---

## Architecture

```
ADK callbacks (audit.py)
    │
    ├─ before_agent_callback  → tracing.on_agent_start(agent_name, inv_id)
    ├─ after_agent_callback   → tracing.on_agent_end(agent_name, inv_id)
    ├─ before_model_callback  → tracing.on_llm_request(agent, inv_id, model, contents, user_input)
    ├─ after_model_callback   → tracing.on_llm_response(agent, inv_id, text, tool_calls, usage)
    ├─ before_tool_callback   → tracing.on_tool_start(agent, inv_id, tool_name, args)
    └─ after_tool_callback    → tracing.on_tool_end(agent, inv_id, tool_name, result)
                                              │
               ┌──────────────────────────────┴────────────────────────────────┐
               │                                                               │
    ┌──────────▼──────────┐                                        ┌──────────▼──────────┐
    │  LangFuse client    │  (if LANGFUSE_PUBLIC_KEY set)          │   _metrics dict      │  (always)
    │                     │                                        │                     │
    │  Trace              │                                        │  _metrics[inv_id] = │
    │  └─ Span: agent:X   │                                        │   {                 │
    │     ├─ Gen: X:llm   │                                        │     "tool_spans":   │
    │     └─ Span: tool:Y │                                        │     [{name, succ}…] │
    │                     │                                        │     "token_usage":  │
    │  Flushed on agent_end│                                        │     {in, out, total}│
    └─────────────────────┘                                        └──────────┬──────────┘
                                                                              │
                                                                   eval/langfuse_client.py
                                                                   fetch_trace_metrics(inv_id)
                                                                   → TraceMetrics(tool_spans, cost_usd)
```

---

## LangFuse Trace Hierarchy

When `LANGFUSE_PUBLIC_KEY` is set, each user turn creates a full trace:

```
Trace: "stock-agent"  (one per invocation)
├─ input: { "query": "What is MSFT's price?" }
│
├─ Span: agent:stock_orchestrator
│   └─ Span: agent:intent_agent
│       └─ Generation: intent_agent:llm
│           ├─ model: gemini-2.5-flash
│           ├─ input: [conversation contents]
│           └─ output: '{"intent":"PRICE",...}'
│           └─ usage: {input: 312, output: 87, total: 399}
│
└─ Span: agent:price_agent
    ├─ Generation: price_agent:llm
    │   ├─ model: gemini-2.5-flash
    │   └─ usage: {input: 1840, output: 210, total: 2050}
    │
    ├─ Span: tool:resolve_ticker
    │   ├─ input: {"ticker_or_name": "MSFT"}
    │   └─ output: {"ticker": "MSFT", "original_input": "MSFT"}
    │
    └─ Span: tool:get-ticker-info
        ├─ input: {"symbol": "MSFT"}
        └─ output: {"currentPrice": 425.30, ...}
```

The trace is flushed to LangFuse when the root agent (`stock_orchestrator`) ends.

---

## Configuration

```bash
# .env
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com   # or your self-hosted URL
```

LangFuse is initialised once at startup in `agent.py`:

```python
from stock_agent import tracing
tracing.setup()   # returns True if enabled, False if credentials missing
```

If `LANGFUSE_PUBLIC_KEY` is not set, all LangFuse code paths are skipped silently via:

```python
if not _lf:
    return
```

---

## In-Process Metrics Collection

Regardless of LangFuse, every invocation populates `_metrics`:

```python
_metrics: dict[str, dict] = {}
# Structure per invocation:
# {
#   "tool_spans": [
#     {"name": "resolve_ticker", "succeeded": True},
#     {"name": "get-ticker-info", "succeeded": True},
#     {"name": "fetch_and_forecast", "succeeded": True},
#   ],
#   "token_usage": {
#     "input":  2345,
#     "output": 412,
#     "total":  2757,
#   }
# }
```

### Tool Span Tracking

```python
# on_tool_start: append span with succeeded=None
_metrics[inv_id]["tool_spans"].append({"name": tool_name, "succeeded": None})

# on_tool_end: find the most recent pending span and mark it
succeeded = result is not None and not (
    isinstance(result, dict) and result.get("status") == "error"
)
for span in reversed(_metrics[inv_id]["tool_spans"]):
    if span["name"] == tool_name and span["succeeded"] is None:
        span["succeeded"] = succeeded
        break
```

`transfer_to_agent` is excluded (internal ADK routing, not a data tool).

### Token Accumulation

```python
# on_llm_response:
if usage and inv_id in _metrics:
    m = _metrics[inv_id]["token_usage"]
    m["input"]  += usage.get("input_tokens",  0) or 0
    m["output"] += usage.get("output_tokens", 0) or 0
    m["total"]  += usage.get("total_tokens",  0) or 0
```

Tokens accumulate across all agents in a multi-agent pipeline — the `_metrics` dict for one `inv_id` captures the total cost of the entire turn.

---

## `get_run_metrics(inv_id)` — Eval Integration

```python
def get_run_metrics(inv_id: str) -> dict | None:
    """Return and discard eval metrics for one invocation."""
    return _metrics.pop(inv_id, None)
```

Called by `eval/langfuse_client.py` after each test run:

```python
def fetch_trace_metrics(inv_id: str) -> Optional[TraceMetrics]:
    raw = tracing.get_run_metrics(inv_id)
    if not raw:
        return None

    spans = [ToolSpan(name=s["name"], succeeded=bool(s.get("succeeded")))
             for s in raw.get("tool_spans", [])]

    usage = raw.get("token_usage", {})
    inp   = usage.get("input",  0) or 0
    out   = usage.get("output", 0) or 0
    cost  = (inp * 0.075 + out * 0.300) / 1_000_000   # Gemini 2.5 Flash pricing

    return TraceMetrics(
        tool_spans  = spans,
        token_usage = usage,
        cost_usd    = round(cost, 6),
    )
```

The `pop` is intentional — metrics are consumed once and discarded to prevent stale data accumulating between eval runs.

---

## Token Cost Formula

```
Gemini 2.5 Flash pricing (as of 2026-05, prompts ≤ 200K tokens):
  Input:  $0.075 / 1M tokens
  Output: $0.300 / 1M tokens

cost_usd = (input_tokens × 0.075 + output_tokens × 0.300) / 1_000_000
```

Example for a `PRICE` query:
```
input_tokens:  2345   (system prompt + conversation + tool responses)
output_tokens:  412   (agent's text response)

cost = (2345 × 0.075 + 412 × 0.300) / 1_000_000
     = (175.875 + 123.600) / 1_000_000
     = $0.000300 per query
```

---

## Message Flow: Full Trace for a PRICE Query

```
User: "What is Microsoft's price?"
    │
    ├─ on_agent_start("stock_orchestrator", "e-d3f2918e")
    │     _metrics["e-d3f2918e"] = {tool_spans:[], token_usage:{in:0,out:0,total:0}}
    │     LangFuse: Trace("stock-agent") created
    │
    ├─ on_agent_start("intent_agent", "e-d3f2918e")
    │     LangFuse: Span("agent:intent_agent") created
    │
    ├─ on_llm_request("intent_agent", ...)
    │     LangFuse: Generation("intent_agent:llm") started
    │
    ├─ on_llm_response("intent_agent", ..., usage={input:312, output:87})
    │     _metrics["e-d3f2918e"]["token_usage"] += {in:312, out:87}
    │     LangFuse: Generation ended with usage
    │
    ├─ on_agent_end("intent_agent", ...)
    │     LangFuse: Span ended
    │
    ├─ on_agent_start("price_agent", "e-d3f2918e")
    │     LangFuse: Span("agent:price_agent") created
    │
    ├─ on_tool_start("price_agent", "e-d3f2918e", "resolve_ticker", {"ticker":"MSFT"})
    │     _metrics["e-d3f2918e"]["tool_spans"].append({name:"resolve_ticker", succeeded:None})
    │     LangFuse: Span("tool:resolve_ticker") started
    │
    ├─ on_tool_end("price_agent", "e-d3f2918e", "resolve_ticker", {"ticker":"MSFT",...})
    │     succeeded = True (no "status":"error")
    │     span["succeeded"] = True
    │     LangFuse: Span ended
    │
    ├─ on_tool_start("price_agent", "e-d3f2918e", "get-ticker-info", {"symbol":"MSFT"})
    │     _metrics appended, LangFuse Span started
    │
    ├─ on_tool_end("price_agent", "e-d3f2918e", "get-ticker-info", {"currentPrice":425.30,...})
    │     succeeded = True
    │     LangFuse Span ended
    │
    ├─ on_llm_response("price_agent", ..., usage={input:1840, output:210})
    │     _metrics token_usage += {in:1840, out:210}
    │     LangFuse Generation ended
    │
    └─ on_agent_end("stock_orchestrator", "e-d3f2918e")
          LangFuse: root trace ended + flushed

Total _metrics["e-d3f2918e"]:
  tool_spans: [{resolve_ticker:✓}, {get-ticker-info:✓}]
  token_usage: {input: 2152, output: 297, total: 2449}

eval/langfuse_client.fetch_trace_metrics("e-d3f2918e"):
  cost_usd = (2152×0.075 + 297×0.300) / 1_000_000 = $0.000250
```
