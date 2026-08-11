"""Intent classification.

The classifier is a pure function of the CURRENT user message — it deliberately
does NOT see conversation history. Running it through the stateful ADK session
(as an LlmAgent) meant the growing transcript would distract the lightweight
model and occasionally produce unparseable output, misrouting to UNKNOWN. So the
orchestrator calls `classify_intent()` here, which makes one direct, history-free
Gemini call with JSON output forced on. (This mirrors the blueprint's eval-bypass
`run_intent_extraction`.)

The LlmAgent object is kept for reference/eval but is not in the live pipeline.
"""
from __future__ import annotations

import json
import os
import re

from google import genai
from google.adk.agents import LlmAgent
from google.genai import types

from .model_config import model_for_agent, output_token_limit
from .prompt_loader import load_prompt

# Reference agent definition (not run in the live pipeline anymore).
intent_agent = LlmAgent(
    name="intent_agent",
    model=model_for_agent("intent_agent"),
    description="Classifies the user query into a structured intent JSON object.",
    instruction=load_prompt("intent_agent_v1"),
    generate_content_config=types.GenerateContentConfig(
        max_output_tokens=output_token_limit("intent_agent"),
        temperature=0.0,
    ),
)

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
    return _client


def _parse_intent(text: str) -> dict:
    """Extract the intent JSON object from the model output; UNKNOWN on failure."""
    if not text:
        return {"intent": "UNKNOWN"}
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        return {"intent": "UNKNOWN"}
    try:
        obj = json.loads(match.group(0))
        if isinstance(obj, dict) and obj.get("intent"):
            return obj
    except json.JSONDecodeError:
        pass
    return {"intent": "UNKNOWN"}


def classify_intent(user_text: str) -> dict:
    """Classify a single user message into an intent dict (history-free)."""
    resp = _get_client().models.generate_content(
        model=model_for_agent("intent_agent"),
        contents=user_text,
        config=types.GenerateContentConfig(
            system_instruction=load_prompt("intent_agent_v1"),
            temperature=0.0,
            max_output_tokens=output_token_limit("intent_agent"),
            response_mime_type="application/json",  # force clean JSON, no fences
        ),
    )
    return _parse_intent(resp.text or "")
