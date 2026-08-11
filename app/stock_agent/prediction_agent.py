"""Prediction agent — 14-day OLS forecast for a ticker.

Tools: resolve_ticker + fetch_and_forecast (both direct Python, no MCP). The
forecast tool is one-shot: it fetches history, fits the regression, and returns a
compact table — no raw price arrays ever enter the LLM context.
"""
from __future__ import annotations

from google.adk.agents import LlmAgent
from google.genai import types

from . import audit, guardrails
from .model_config import model_for_agent, output_token_limit
from .prompt_loader import load_prompt
from .tools import fetch_and_forecast, resolve_ticker

prediction_agent = LlmAgent(
    name="prediction_agent",
    model=model_for_agent("prediction_agent"),
    description="Projects a short-term price forecast using linear regression.",
    instruction=load_prompt("prediction_v1"),
    tools=[resolve_ticker, fetch_and_forecast],
    generate_content_config=types.GenerateContentConfig(
        max_output_tokens=output_token_limit("prediction_agent"),
        temperature=0.2,
    ),
    before_model_callback=guardrails.before_model_guardrails,
    before_agent_callback=audit.before_agent_callback,
    after_agent_callback=audit.after_agent_callback,
    before_tool_callback=audit.before_tool_callback,
    after_tool_callback=audit.after_tool_callback,
)
