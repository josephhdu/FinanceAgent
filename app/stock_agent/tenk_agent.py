"""10-K RAG agent — answers questions from SEC filings with citations.

Tools are direct Python (ChromaDB vector search), not MCP — see tenk_tools for
the embedding-model warm-up rationale. Runs on the full-tier model since RAG
synthesis benefits from stronger reasoning.
"""
from __future__ import annotations

from google.adk.agents import LlmAgent
from google.genai import types

from . import audit, guardrails
from .model_config import model_for_agent, output_token_limit
from .prompt_loader import load_prompt
from .tenk_tools import list_indexed_companies, search_10k
from .tools import resolve_ticker

tenk_agent = LlmAgent(
    name="tenk_agent",
    model=model_for_agent("tenk_agent"),
    description="Answers questions about companies' SEC 10-K annual reports via RAG.",
    instruction=load_prompt("tenk_v1"),
    tools=[resolve_ticker, list_indexed_companies, search_10k],
    generate_content_config=types.GenerateContentConfig(
        max_output_tokens=output_token_limit("tenk_agent"),
        temperature=0.2,
    ),
    before_model_callback=guardrails.before_model_guardrails,
    before_agent_callback=audit.before_agent_callback,
    after_agent_callback=audit.after_agent_callback,
    before_tool_callback=audit.before_tool_callback,
    after_tool_callback=audit.after_tool_callback,
)
