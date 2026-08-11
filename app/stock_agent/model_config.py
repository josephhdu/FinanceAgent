"""Central model + token configuration.

A single source of truth for the Gemini model string and per-agent output
token budgets. Kept deliberately static (not resolved dynamically) so behavior
is reproducible — see arch/Architecture.md 5.14.
"""
from __future__ import annotations

import os

# Two model tiers to balance cost against quality (cost-aware routing):
#   - FULL: the balanced "flash" workhorse — reasoning-heavy agents.
#   - LITE: the cheaper "flash-lite" — simple, low-risk agents (classification,
#           price formatting, chart captions).
#
# NOTE: the blueprint targeted "gemini-2.5-flash", which is now 404-gated for
# new API keys ("no longer available to new users"), along with 2.5-flash-lite.
# gemini-3.6-flash is its direct successor. Centralizing the strings here is
# exactly why swapping models is a trivial change (arch/Architecture.md 5.14).
MODEL_FULL = "gemini-3.6-flash"
MODEL_LITE = "gemini-3.5-flash-lite"
MODEL_VERSION = MODEL_FULL  # default / back-compat alias

# Which tier each agent runs on. "cheap" -> MODEL_LITE, "full" -> MODEL_FULL.
# intent_agent is on the cheap tier by choice (cost); if eval later shows
# misroutes we can promote it back to MODEL_FULL — a one-line change here.
_AGENT_TIER: dict[str, str] = {
    "intent_agent": "cheap",
    "price_agent": "cheap",
    "visualization_agent": "cheap",   # writes a one-line caption only
    "prediction_agent": "full",
    "tenk_agent": "full",             # RAG synthesis
    "trading_agent": "full",          # signal reasoning + rationale
}


def model_for_agent(agent_name: str) -> str:
    """Return the model string for an agent based on its cost tier."""
    return MODEL_LITE if _AGENT_TIER.get(agent_name, "full") == "cheap" else MODEL_FULL

# Per-agent maximum OUTPUT tokens. Keeps responses tight and costs predictable.
AGENT_TOKEN_LIMITS: dict[str, int] = {
    "intent_agent": 500,
    "price_agent": 512,
    "prediction_agent": 1024,
    "visualization_agent": 256,   # caption only — the chart is delivered out-of-band
    "tenk_agent": 3000,
    "trading_agent": 1024,
}
DEFAULT_OUTPUT_TOKENS = 1024

# Guardrail input ceiling (Chunk 6). Authoritative value per arch/05-guardrails.md.
TOKEN_LIMIT = int(os.getenv("TOKEN_LIMIT", "120000"))


def output_token_limit(agent_name: str) -> int:
    """Output-token cap for a given agent, falling back to the default."""
    return AGENT_TOKEN_LIMITS.get(agent_name, DEFAULT_OUTPUT_TOKENS)
