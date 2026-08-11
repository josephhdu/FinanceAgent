"""Structured audit logging + tool-response post-processing.

Every significant event (agent start/stop, model call, tool call) is written as
one JSON object per line to ``audit.log``. This is always-on, zero-dependency
observability — useful in the terminal during development and the substrate the
eval harness reads later (Chunk 7).

In Chunk 0 the ADK lifecycle callbacks are thin loggers. Chunk 3 adds the
critical ``after_tool_callback`` behavior: stripping large base64 chart payloads
out of tool responses before they reach the LLM's context window.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

# Per-request sink for captured chart images. The web server sets a fresh list at
# the start of each SSE stream; the after_tool_callback appends the full base64
# markdown here BEFORE stripping it from the LLM-facing response. ContextVars are
# copied into child tasks/executors, so a tool running deep inside the ADK runner
# still appends to the same list the request coroutine is draining.
current_images: ContextVar[list | None] = ContextVar("current_images", default=None)

# Per-request sink for source citations (e.g. which 10-K passages were used).
# Populated by the after_tool_callback for RAG tools; drained by the web server
# into a `citations` SSE event after the answer.
current_citations: ContextVar[list | None] = ContextVar("current_citations", default=None)

# Per-request sink for trade signals — the web server emits a `signal` SSE event
# (BUY/SELL/HOLD badge) before the first text token.
current_signals: ContextVar[list | None] = ContextVar("current_signals", default=None)

# The current chat session id, so trade tools can key the in-memory pending-trade
# store per session (set by the web server at the start of each request).
current_session_id: ContextVar[str | None] = ContextVar("current_session_id", default=None)

# The current authenticated user (JWT `sub`), so the trade log and portfolio are
# scoped per-user. Set by the web server on every request — both the SSE chat and
# the REST endpoints — so an executed trade is stamped with its owner and reads
# only return that owner's trades. A platform where everyone shared one portfolio
# wouldn't be a real portfolio.
current_user_id: ContextVar[str | None] = ContextVar("current_user_id", default=None)

# Set True by the orchestrator when a turn runs a disclaimer-required agent (e.g.
# trading). The web server reads it after streaming and appends the financial-
# advice disclaimer if the model didn't already include one (Chunk 6 guardrail).
current_disclaimer_required: ContextVar[bool] = ContextVar(
    "current_disclaimer_required", default=False
)

# --- log sink -------------------------------------------------------------

_LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "audit.log")


def log_event(event_type: str, **fields: Any) -> None:
    """Append one structured JSON line to audit.log.

    Never raises — logging must not break a request. Serialization failures
    fall back to a repr so we always get *something* on disk.
    """
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        **fields,
    }
    try:
        line = json.dumps(record, default=str)
    except Exception:  # pragma: no cover - defensive
        line = json.dumps({"ts": record["ts"], "event": event_type, "raw": repr(fields)})
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:  # pragma: no cover - disk issues shouldn't crash a turn
        pass


# --- in-process metrics ---------------------------------------------------
# Always-on counters + value samples (latencies, token counts), aggregated
# process-wide. Cheap, dependency-free observability the eval harness and the
# /api/metrics endpoint read. Guarded by a lock since tools may run in threads.

_METRICS_LOCK = threading.Lock()
_COUNTERS: dict[str, int] = defaultdict(int)
_SAMPLES: dict[str, list[float]] = defaultdict(list)

# Per-request span-start times, keyed within the request's context so before/
# after callback pairs can measure a duration without a shared global.
_span_starts: ContextVar[dict | None] = ContextVar("_span_starts", default=None)


def incr(name: str, n: int = 1) -> None:
    with _METRICS_LOCK:
        _COUNTERS[name] += n


def observe(name: str, value: float) -> None:
    """Record a numeric sample (latency ms, token count, …) under `name`."""
    with _METRICS_LOCK:
        _SAMPLES[name].append(float(value))


def _mark_start(key: tuple) -> None:
    d = _span_starts.get()
    if d is None:
        d = {}
        _span_starts.set(d)
    d[key] = time.perf_counter()


def _elapsed_ms(key: tuple) -> float | None:
    d = _span_starts.get()
    if not d or key not in d:
        return None
    return (time.perf_counter() - d.pop(key)) * 1000.0


def get_metrics() -> dict:
    """Snapshot of counters + sample summaries (count / avg / p95)."""
    with _METRICS_LOCK:
        summary = {}
        for name, vals in _SAMPLES.items():
            if not vals:
                continue
            s = sorted(vals)
            p95 = s[min(len(s) - 1, int(len(s) * 0.95))]
            summary[name] = {
                "count": len(s),
                "avg": round(sum(s) / len(s), 1),
                "p95": round(p95, 1),
            }
        return {"counters": dict(_COUNTERS), "samples": summary}


def reset_metrics() -> None:
    with _METRICS_LOCK:
        _COUNTERS.clear()
        _SAMPLES.clear()


# --- tool responses that carry large base64 image payloads ----------------
# Chunk 3 wires these up. Declared here so the strip logic has one home.
_CHART_RENDER_TOOLS = frozenset(
    {
        "render_price_chart_for_ticker",
        "render_prediction_chart_for_ticker",
        "render_comparison_chart_for_tickers",
        "render_financial_chart_for_ticker",
    }
)

# Agents whose output must always carry a financial-risk disclaimer (Chunk 5/6).
_DISCLAIMER_REQUIRED_AGENTS = frozenset({"trading_agent"})


# --- ADK lifecycle callbacks (thin in Chunk 0, extended later) ------------

def before_agent_callback(callback_context: Any = None, **_: Any):
    name = getattr(callback_context, "agent_name", None)
    _mark_start(("agent", name))
    log_event("agent_start", agent=name)
    return None


def after_agent_callback(callback_context: Any = None, **_: Any):
    name = getattr(callback_context, "agent_name", None)
    ms = _elapsed_ms(("agent", name))
    incr(f"agent.{name}.calls")
    if ms is not None:
        observe(f"agent.{name}.latency_ms", ms)
    log_event("agent_end", agent=name, latency_ms=round(ms, 1) if ms is not None else None)
    return None


def before_tool_callback(tool: Any = None, args: Any = None, **_: Any):
    name = getattr(tool, "name", str(tool))
    _mark_start(("tool", name))
    log_event("tool_start", tool=name, args=args)
    return None


def after_tool_callback(tool: Any = None, args: Any = None, tool_response: Any = None, **_: Any):
    """Log the tool call, then apply the one-shot chart defense.

    For chart-render tools the response contains a ~50KB base64 PNG in its
    ``markdown`` field. Left in place it tokenises to ~170K tokens and hangs the
    model. So we (1) capture the full markdown into the request's image sink for
    out-of-band delivery to the browser, then (2) return a copy WITHOUT the
    markdown so the LLM only sees ``{status, title}`` (~20 tokens). Returning a
    non-None value replaces the tool response the model sees.
    """
    tool_name = getattr(tool, "name", str(tool))
    ms = _elapsed_ms(("tool", tool_name))
    incr(f"tool.{tool_name}.calls")
    if ms is not None:
        observe(f"tool.{tool_name}.latency_ms", ms)
    log_event("tool_end", tool=tool_name, latency_ms=round(ms, 1) if ms is not None else None)

    if (
        tool_name in _CHART_RENDER_TOOLS
        and isinstance(tool_response, dict)
        and "markdown" in tool_response
    ):
        sink = current_images.get()
        if sink is not None:
            sink.append(tool_response["markdown"])
        return {k: v for k, v in tool_response.items() if k != "markdown"}

    # Capture 10-K passage citations for out-of-band display.
    if (
        tool_name == "search_10k"
        and isinstance(tool_response, dict)
        and tool_response.get("results")
    ):
        cites = current_citations.get()
        if cites is not None:
            ticker = tool_response.get("ticker", "")
            for r in tool_response["results"]:
                cites.append(
                    {
                        "label": f"{ticker} {r.get('form', '10-K')}",
                        "detail": f"{r.get('section', '10-K')} · chunk {r.get('chunk_index')} · relevance {r.get('relevance')}",
                    }
                )

    # Capture a trade signal for the BUY/SELL/HOLD badge.
    if (
        tool_name == "get_trade_signals"
        and isinstance(tool_response, dict)
        and tool_response.get("status") == "success"
    ):
        sink = current_signals.get()
        if sink is not None:
            sink.append(
                {
                    "ticker": tool_response.get("ticker"),
                    "action": tool_response.get("action"),
                    "signal_score": tool_response.get("signal_score"),
                    "confidence_pct": tool_response.get("confidence_pct"),
                }
            )
    return None
