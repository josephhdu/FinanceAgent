"""Trading agent — mock BUY/SELL/HOLD recommendations with human approval.

This agent only PROPOSES: it computes a signal, stores a pending trade, and
presents a recommendation card. It has no tool that can execute a trade. The
user's yes/no is parsed by the orchestrator in plain Python, which executes or
cancels the pending trade itself. All trades are paper trades in trades.jsonl.
"""
from __future__ import annotations

from google.adk.agents import LlmAgent
from google.genai import types

from . import audit, guardrails
from .model_config import model_for_agent, output_token_limit
from .prompt_loader import load_prompt
from .tools import resolve_ticker
from .trade_tools import (
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
