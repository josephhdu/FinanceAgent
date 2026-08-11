"""Price agent — live price + snapshot for a ticker.

Tools: resolve_ticker (direct Python) + get_ticker_info (MCP). Least-privilege:
it only sees the one finance tool it needs.
"""
from __future__ import annotations

from google.adk.agents import LlmAgent
from google.genai import types

from . import audit, guardrails
from .mcp_config import make_finance_toolset
from .model_config import model_for_agent, output_token_limit
from .prompt_loader import load_prompt
from .tools import resolve_ticker

price_agent = LlmAgent(
    name="price_agent",
    model=model_for_agent("price_agent"),
    description="Looks up live stock price and key financial stats for a company.",
    instruction=load_prompt("price_v1"),
    tools=[resolve_ticker, make_finance_toolset(["get_ticker_info"])],
    generate_content_config=types.GenerateContentConfig(
        max_output_tokens=output_token_limit("price_agent"),
        temperature=0.2,
    ),
    before_model_callback=guardrails.before_model_guardrails,
    before_agent_callback=audit.before_agent_callback,
    after_agent_callback=audit.after_agent_callback,
    before_tool_callback=audit.before_tool_callback,
    after_tool_callback=audit.after_tool_callback,
)
