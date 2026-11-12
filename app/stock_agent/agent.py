"""GraphOrchestrator — deterministic root agent.

Runs the intent_agent, parses its JSON, then executes an ordered pipeline of
specialist agents chosen by a pure-Python dict lookup (_ROUTE_MAP). No LLM
decides which agent runs next — that is the whole point.
"""
from __future__ import annotations

import asyncio
import re
from typing import AsyncGenerator

from google.adk.agents import BaseAgent, LlmAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types

from . import audit, guardrails
from .intent_agent import classify_intent
from .prediction_agent import prediction_agent as _prediction_agent
from .price_agent import price_agent as _price_agent
from .tenk_agent import tenk_agent as _tenk_agent
from .trade_tools import cancel_pending_trade, execute_pending_trade, has_pending_trade
from .trading_agent import trading_agent as _trading_agent
from .visualization_agent import visualization_agent as _visualization_agent

# intent -> ordered list of specialist names (keys into `specialists`).
_ROUTE_MAP: dict[str, list[str]] = {
    "PRICE": ["price_agent"],
    "PREDICTION": ["prediction_agent"],
    "VISUALIZATION": ["visualization_agent"],
    "PRICE_PREDICTION": ["price_agent", "prediction_agent"],
    "PRICE_PREDICT_CHART": ["price_agent", "prediction_agent", "visualization_agent"],
    "ANNUAL_REPORT": ["tenk_agent"],
    "TRADE_ANALYSIS": ["trading_agent"],
}

# Approving a pending trade is decided here in Python, never by a model. A reply
# counts as a decision only if EVERY word is an approve/decline word or harmless
# filler — so "yes" or "no thanks" qualify, but "should I buy NVDA?" or
# "ok what is MSFT at" don't. Anything ambiguous cancels the proposal (fail safe).
_APPROVE_WORDS = {
    "yes", "y", "yeah", "yep", "yup", "sure", "ok", "okay", "confirm", "confirmed",
    "approve", "approved", "execute", "proceed",
}
_DECLINE_WORDS = {"no", "n", "nope", "nah", "cancel", "stop", "abort", "decline", "reject", "don't", "dont"}
_FILLER_WORDS = {"please", "thanks", "thank", "you", "it", "do", "go", "ahead", "for", "the", "trade", "that"}
_APPROVE_PHRASES = {"do it", "go ahead", "go for it"}


def _parse_decision(text: str) -> str | None:
    """Return "approve", "decline", or None if the message isn't a clear yes/no."""
    words = re.findall(r"[a-z']+", (text or "").lower())
    if not words or len(words) > 6:
        return None
    if set(words) - _APPROVE_WORDS - _DECLINE_WORDS - _FILLER_WORDS:
        return None
    approve = bool(set(words) & _APPROVE_WORDS) or " ".join(words) in _APPROVE_PHRASES
    decline = bool(set(words) & _DECLINE_WORDS)
    if approve == decline:
        return None
    return "approve" if approve else "decline"


def _trade_result_text(res: dict) -> str:
    if res.get("status") != "success":
        return f"Couldn't record that trade: {res.get('message', 'unknown error')}."
    return (
        f"✅ Recorded paper trade **{res['trade_id']}**: {res['action']} {res['shares']} "
        f"{res['ticker']} at ${res['price']:,.2f} (≈ ${res['notional']:,.2f})."
    )


def _event_text(event: Event) -> str:
    if event.content and event.content.parts:
        return "".join(p.text or "" for p in event.content.parts)
    return ""


def _user_text(ctx: InvocationContext) -> str:
    """Best-effort extraction of the current user message."""
    uc = getattr(ctx, "user_content", None)
    if uc and getattr(uc, "parts", None):
        text = "".join(p.text or "" for p in uc.parts)
        if text.strip():
            return text
    # Fallback: last user-authored event in the session.
    for event in reversed(getattr(ctx.session, "events", []) or []):
        if (event.content and event.content.role == "user") or event.author == "user":
            return _event_text(event)
    return ""


class GraphOrchestrator(BaseAgent):
    """Deterministic root agent: classify → dict lookup → run pipeline."""

    model_config = {"arbitrary_types_allowed": True}

    specialists: dict[str, LlmAgent]
    route_map: dict[str, list[str]]

    def __init__(
        self,
        specialists: dict[str, LlmAgent],
        route_map: dict[str, list[str]],
        name: str = "stock_orchestrator",
    ) -> None:
        super().__init__(
            name=name,
            specialists=specialists,
            route_map=route_map,
            sub_agents=list(specialists.values()),
        )

    def _msg(self, ctx: InvocationContext, text: str, author: str | None = None) -> Event:
        return Event(
            author=author or self.name,
            invocation_id=ctx.invocation_id,
            content=types.Content(role="model", parts=[types.Part(text=text)]),
        )

    def _progress(self, ctx: InvocationContext, text: str) -> Event:
        return self._msg(ctx, text, author="__progress__")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        user_text = _user_text(ctx)

        # -1) Guardrail: block prompt-injection attempts before ANY model runs.
        hit = guardrails.scan_injection(user_text)
        if hit:
            audit.incr("guardrail.injection_blocked")
            audit.log_event("guardrail_block", kind="injection", match=hit[:80])
            yield self._msg(
                ctx,
                "I can't help with that. I'm a stock-analysis assistant — ask me "
                "about prices, forecasts, charts, filings, or paper trades.",
            )
            return

        # 0) Pending-trade decision — runs BEFORE classification. The human
        #    approval step is enforced in code: only an unambiguous yes executes
        #    the trade, and no model is involved. Any other message cancels the
        #    stale proposal and falls through to normal handling.
        if has_pending_trade():
            decision = _parse_decision(user_text)
            if decision:
                audit.current_disclaimer_required.set(True)
                if decision == "approve":
                    res = await asyncio.to_thread(execute_pending_trade)
                    audit.log_event("trade_decision", decision=decision, status=res.get("status"))
                    yield self._msg(ctx, _trade_result_text(res))
                else:
                    cancel_pending_trade()
                    audit.log_event("trade_decision", decision=decision)
                    yield self._msg(ctx, "Cancelled — no trade was recorded.")
                return
            cancel_pending_trade()
            yield self._progress(ctx, "Previous trade proposal cancelled — handling your new request…")

        # 1) Classify with a direct, history-free model call (see intent_agent).
        #    PII is masked out of the text before it reaches the classifier model.
        yield self._progress(ctx, "Understanding your question…")
        intent_obj = await asyncio.to_thread(classify_intent, guardrails.mask_text(user_text))
        intent = intent_obj.get("intent", "UNKNOWN")
        audit.incr(f"intent.{intent}")
        audit.log_event("intent_classified", intent=intent, raw=intent_obj.get("raw_query"))

        # 2) Route via pure-Python dict lookup.
        pipeline = self.route_map.get(intent, [])
        if not pipeline:
            yield self._msg(
                ctx,
                "I'm a stock-analysis assistant — I can look up prices and key stats "
                "for tech-sector companies. Try asking something like *“What's MSFT "
                "trading at?”*",
            )
            return

        # 3) Run the specialist pipeline in order.
        ctx.session.state["pipeline"] = intent
        ctx.session.state["pipeline_total"] = len(pipeline)
        for step, name in enumerate(pipeline, start=1):
            agent = self.specialists[name]
            ctx.session.state["pipeline_step"] = step
            if name in audit._DISCLAIMER_REQUIRED_AGENTS:
                audit.current_disclaimer_required.set(True)
            yield self._progress(ctx, f"Running {name.replace('_', ' ')}…")
            async for event in agent.run_async(ctx):
                yield event


# --- root agent wiring ----------------------------------------------------

SPECIALISTS: dict[str, LlmAgent] = {
    "price_agent": _price_agent,
    "prediction_agent": _prediction_agent,
    "visualization_agent": _visualization_agent,
    "tenk_agent": _tenk_agent,
    "trading_agent": _trading_agent,
}

root_agent = GraphOrchestrator(
    specialists=SPECIALISTS,
    route_map=_ROUTE_MAP,
)
