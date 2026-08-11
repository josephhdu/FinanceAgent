"""Load agent system prompts from versioned markdown files in prompts/.

Keeping prompts in files (not inline strings) is the "prompt skill registry"
practice — prompts are versioned artifacts you can diff and eval independently
(arch/Architecture.md 5.13/5.14).
"""
from __future__ import annotations

import os
from functools import lru_cache

_PROMPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """Return the text of prompts/{name}.md."""
    path = os.path.join(_PROMPT_DIR, f"{name}.md")
    with open(path, encoding="utf-8") as fh:
        return fh.read().strip()
