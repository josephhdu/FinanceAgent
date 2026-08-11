"""Chunk 6 — safety guardrails.

Two tiers, wired where each check actually belongs in this architecture:

* **Root (GraphOrchestrator)** — runs *before* any model sees the message:
  prompt-injection blocking and PII masking of the text handed to intent
  classification. Out-of-scope requests are already turned away by the intent
  classifier's ``UNKNOWN`` branch.

* **Sub-agents (LlmAgent)** — a ``before_model_callback`` that masks PII in the
  outgoing request and enforces a hard input-token ceiling. We deliberately do
  the PII/token work in *before_model* (which operates on the request) rather
  than *after_model*: under SSE streaming ``after_model_callback`` fires on every
  partial chunk, so rewriting responses there would corrupt the stream.

The financial-advice disclaimer is enforced deterministically by the web server
after the answer is assembled (see web_server.generate) — the model is prompted
to add it, and the server guarantees it, which streaming callbacks can't.

v1 simplification (per the plan): PII is masked in-memory per request; there is
no Fernet-encrypted token store, and output-side masking is best-effort.
"""
from __future__ import annotations

import re
from typing import Any

from google.adk.models.llm_response import LlmResponse
from google.genai import types

from . import audit
from .model_config import TOKEN_LIMIT

# --- 1. Prompt-injection detection (root only) ----------------------------

_INJECTION_PATTERNS = [
    r"ignore\s+(?:all|any|the|your)?\s*(?:previous|prior|above|earlier)?\s*(?:instructions|prompts?|rules)",
    r"disregard\s+(?:all|any|the|your|previous|prior)",
    r"forget\s+(?:all|everything|your|the)\s+(?:instructions|prompt|rules|context)",
    r"(?:reveal|show|print|repeat|expose)\s+(?:your|the)\s+(?:system\s+)?(?:prompt|instructions|rules)",
    r"system\s+prompt",
    r"you\s+are\s+now\s+(?:a|an|no longer)",
    r"developer\s+mode",
    r"jailbreak|dan\s+mode",
    r"</?\s*(?:system|instruction|admin)\s*>",
    r"pretend\s+(?:you|to\s+be)",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)


def scan_injection(text: str) -> str | None:
    """Return the matched injection phrase, or None if the text looks clean."""
    m = _INJECTION_RE.search(text or "")
    return m.group(0).strip() if m else None


# --- 2. PII detection + masking -------------------------------------------
# Ordered; each match becomes a ``[TYPE_n]`` placeholder. Patterns are written
# to avoid false positives on ordinary finance text (prices, dates, market caps).

_PII_SPECS: list[tuple[str, re.Pattern]] = [
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    # 16-digit card, grouped (won't hit bare long numbers like volumes).
    ("CARD", re.compile(r"\b(?:\d{4}[-\s]){3}\d{4}\b")),
    # Phone: requires separators between groups (so a plain 10-digit number
    # such as a share count or market-cap figure won't match).
    ("PHONE", re.compile(r"(?:\+?1[-.\s])?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")),
]


def mask_pii(text: str) -> tuple[str, dict[str, str]]:
    """Replace PII with ``[TYPE_n]`` tokens. Returns (masked_text, {token: original})."""
    if not text:
        return text, {}
    mapping: dict[str, str] = {}
    counters: dict[str, int] = {}
    out = text
    for kind, rx in _PII_SPECS:
        def _repl(m: re.Match, _kind=kind) -> str:
            counters[_kind] = counters.get(_kind, 0) + 1
            token = f"[{_kind}_{counters[_kind]}]"
            mapping[token] = m.group(0)
            return token
        out = rx.sub(_repl, out)
    return out, mapping


def mask_text(text: str) -> str:
    """Convenience: masked text only (drops the mapping)."""
    return mask_pii(text)[0]


# --- 3. Token accounting --------------------------------------------------

_DATA_URI_RE = re.compile(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+")


def estimate_tokens(contents: list[Any]) -> int:
    """Rough token estimate for a request's contents.

    Base64 image payloads are collapsed to ``[IMAGE]`` before counting so a chart
    that slipped through doesn't blow the estimate (~4 chars/token heuristic).
    """
    chars = 0
    for c in contents or []:
        for p in getattr(c, "parts", None) or []:
            t = getattr(p, "text", None)
            if t:
                chars += len(_DATA_URI_RE.sub("[IMAGE]", t))
    return chars // 4


# --- 4. Advice language + disclaimer --------------------------------------

DISCLAIMER = (
    "⚠️ *This is a mock trade for educational purposes only and is not financial "
    "advice. Paper trading only — no real orders are placed.*"
)
# Substring used to detect whether a disclaimer is already present.
DISCLAIMER_MARKER = "not financial advice"

_ADVICE_RE = re.compile(
    r"\b(?:you\s+should\s+(?:buy|sell)|i\s+(?:would\s+)?recommend|guaranteed\s+returns?|"
    r"can'?t\s+lose|risk[-\s]?free|will\s+(?:surely|certainly|definitely)\s+"
    r"(?:rise|increase|go\s+up|moon))\b",
    re.IGNORECASE,
)


def contains_advice(text: str) -> bool:
    return bool(_ADVICE_RE.search(text or ""))


# --- 5. before_model_callback (sub-agents): PII mask + token ceiling ------

def _blocked_response(message: str) -> LlmResponse:
    """Build a short-circuit model response (skips the real model call)."""
    return LlmResponse(
        content=types.Content(role="model", parts=[types.Part(text=message)])
    )


def before_model_guardrails(callback_context: Any = None, llm_request: Any = None, **_: Any):
    """Enforce the input-token ceiling and mask PII before the model is called."""
    agent = getattr(callback_context, "agent_name", None)
    contents = getattr(llm_request, "contents", None) or []

    tokens = estimate_tokens(contents)
    audit.observe("input_tokens", tokens)
    if tokens > TOKEN_LIMIT:
        audit.incr("guardrail.token_blocked")
        audit.log_event("guardrail_block", kind="token_limit", agent=agent, tokens=tokens)
        return _blocked_response(
            "This request is too large for me to process safely. "
            "Please shorten it and try again."
        )

    masked = 0
    for c in contents:
        for p in getattr(c, "parts", None) or []:
            t = getattr(p, "text", None)
            if t:
                new, mapping = mask_pii(t)
                if mapping:
                    p.text = new
                    masked += len(mapping)
    if masked:
        audit.incr("guardrail.pii_masked", masked)
        audit.log_event("guardrail_pii_masked", agent=agent, count=masked)
    return None
