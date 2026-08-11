"""CLI entry point (optional dev harness).

Chunk 0: a placeholder that confirms the package imports cleanly. Chunk 1 wires
this to the orchestrator so you can chat from the terminal without the web UI.
"""
from __future__ import annotations

from stock_agent.model_config import MODEL_VERSION


def main() -> None:
    print(f"FinanceAI CLI — model: {MODEL_VERSION}")
    print("Orchestrator wiring arrives in Chunk 1. Use the web UI for now:")
    print("  uvicorn web_server:app --port 8080 --reload")


if __name__ == "__main__":
    main()
