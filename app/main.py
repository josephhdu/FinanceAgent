"""Terminal chat harness for FinanceAI.

A thin CLI over the *same* orchestrator the web server uses — handy for exercising
routing without a browser.

    python main.py            # interactive chat (needs GOOGLE_API_KEY in .env)
    python main.py --check    # build the agent graph and print the routing table,
                              # then exit — a quick wiring smoke test, no model calls
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid

from dotenv import load_dotenv

load_dotenv()

# `--check` only inspects wiring, so skip the RAG warm-up (and its heavy imports).
if "--check" in sys.argv:
    os.environ.setdefault("FINANCEAI_DISABLE_WARMUP", "1")

from google.adk.agents.run_config import RunConfig, StreamingMode  # noqa: E402
from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions.in_memory_session_service import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

from stock_agent import audit  # noqa: E402
from stock_agent.agent import SPECIALISTS, _ROUTE_MAP, root_agent  # noqa: E402
from stock_agent.model_config import MODEL_FULL, MODEL_LITE  # noqa: E402

APP_NAME = "financeai-cli"
USER_ID = "cli-user"


def _print_wiring() -> None:
    print(f"FinanceAI — models: full={MODEL_FULL}  lite={MODEL_LITE}")
    print(f"Specialists ({len(SPECIALISTS)}): {', '.join(SPECIALISTS)}")
    print("Routing table (intent → pipeline):")
    for intent, pipeline in _ROUTE_MAP.items():
        print(f"  {intent:<20} → {' → '.join(pipeline)}")


async def _chat() -> None:
    sessions = InMemorySessionService()
    session_id = uuid.uuid4().hex
    await sessions.create_session(app_name=APP_NAME, user_id=USER_ID, session_id=session_id)
    runner = Runner(app_name=APP_NAME, agent=root_agent, session_service=sessions)

    audit.current_user_id.set(USER_ID)
    audit.current_session_id.set(session_id)

    print("FinanceAI CLI — ask about prices, forecasts, charts, filings, or trades.")
    print("(charts render in the web UI, not here). Type 'exit' to quit.\n")
    while True:
        try:
            msg = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not msg:
            continue
        if msg.lower() in {"exit", "quit"}:
            break

        new_message = types.Content(role="user", parts=[types.Part(text=msg)])
        print("ai>  ", end="", flush=True)
        streamed = False
        async for event in runner.run_async(
            user_id=USER_ID,
            session_id=session_id,
            new_message=new_message,
            run_config=RunConfig(streaming_mode=StreamingMode.SSE),
        ):
            if (event.author or "") in ("__progress__", "intent_agent"):
                continue  # internal routing/progress, not shown
            if not (event.content and event.content.parts):
                continue
            text = "".join(p.text or "" for p in event.content.parts)
            if not text:
                continue
            if getattr(event, "partial", False):
                streamed = True
                print(text, end="", flush=True)
            elif not streamed:
                print(text, end="", flush=True)
            else:
                streamed = False  # final aggregate after a streamed message
        print("\n")


def main() -> None:
    if "--check" in sys.argv:
        _print_wiring()
        print("\n✓ Agent graph built successfully (no model calls made).")
        return
    asyncio.run(_chat())


if __name__ == "__main__":
    main()
