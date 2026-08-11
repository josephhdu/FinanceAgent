"""Trading agent — mock BUY/SELL/HOLD with two-turn human approval.

Turn 1: compute a signal, store a pending trade, present a recommendation card.
Turn 2: the orchestrator detects the pending trade and routes the user's yes/no
straight here (bypassing intent classification), and this agent executes or
cancels accordingly. All trades are paper trades appended to trades.jsonl.
"""
from __future__ import annotations

from google.adk.agents import LlmAgent
from google.genai import types

from . import audit, guardrails
from .model_config import model_for_agent, output_token_limit
from .prompt_loader import load_prompt
from .tools import resolve_ticker
from .trade_tools import (
    cancel_pending_trade,
    execute_pending_trade,
    get_pending_trade,
    get_portfolio,
    get_trade_history,
    get_trade_signals,
    store_pending_trade,
)

trading_agent = LlmAgent(
    name="trading_agent",
    model=model_for_agent("trading_agent"),
    description="Recommends and (with approval) records mock paper trades.",
    instruction=load_prompt("trading_agent_v1"),
    tools=[
        resolve_ticker,
        get_trade_signals,
        store_pending_trade,
        get_pending_trade,
        execute_pending_trade,
        cancel_pending_trade,
        get_portfolio,
        get_trade_history,
    ],
    generate_content_config=types.GenerateContentConfig(
        max_output_tokens=output_token_limit("trading_agent"),
        temperature=0.2,
    ),
    before_model_callback=guardrails.before_model_guardrails,
    before_agent_callback=audit.before_agent_callback,
    after_agent_callback=audit.after_agent_callback,
    before_tool_callback=audit.before_tool_callback,
    after_tool_callback=audit.after_tool_callback,
)
