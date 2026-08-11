"""Visualization agent — renders one chart and writes a caption.

The chart tools are one-shot: they fetch, compute, and render a PNG internally.
The audit after_tool_callback strips the base64 image from what this agent sees
(the browser gets it separately), so the agent only ever receives {status, title}
and writes a one-line caption.
"""
from __future__ import annotations

from google.adk.agents import LlmAgent
from google.genai import types

from . import audit, guardrails
from .model_config import model_for_agent, output_token_limit
from .prompt_loader import load_prompt
from .tools import (
    render_comparison_chart_for_tickers,
    render_financial_chart_for_ticker,
    render_price_chart_for_ticker,
    render_prediction_chart_for_ticker,
    resolve_ticker,
)

visualization_agent = LlmAgent(
    name="visualization_agent",
    model=model_for_agent("visualization_agent"),
    description="Renders a stock chart (price, forecast, comparison, or financials).",
    instruction=load_prompt("visualization_v1"),
    tools=[
        resolve_ticker,
        render_price_chart_for_ticker,
        render_prediction_chart_for_ticker,
        render_comparison_chart_for_tickers,
        render_financial_chart_for_ticker,
    ],
    generate_content_config=types.GenerateContentConfig(
        max_output_tokens=output_token_limit("visualization_agent"),
        temperature=0.2,
    ),
    before_model_callback=guardrails.before_model_guardrails,
    before_agent_callback=audit.before_agent_callback,
    after_agent_callback=audit.after_agent_callback,
    before_tool_callback=audit.before_tool_callback,
    after_tool_callback=audit.after_tool_callback,
)
