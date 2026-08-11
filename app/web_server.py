"""FastAPI web server for FinanceAI.

Chunk 1: wraps the ADK runner in an SSE chat endpoint. A browser POST to
/api/chat/{session_id} streams the orchestrator's output back token-by-token as
Server-Sent Events. Auth (Chunk 2), inline charts (Chunk 3), citations (Chunk 4),
and the trade badge (Chunk 5) extend the same stream.

Run: uvicorn web_server:app --port 8080 --reload
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

from google.adk.agents.run_config import RunConfig, StreamingMode  # noqa: E402
from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions.sqlite_session_service import SqliteSessionService  # noqa: E402
from google.genai import types  # noqa: E402

from stock_agent import audit, auth, guardrails, market_data, session_store  # noqa: E402
from stock_agent import tenk_tools  # noqa: E402
from stock_agent.agent import root_agent  # noqa: E402
from stock_agent.trade_tools import (  # noqa: E402
    execute_trade_now,
    get_portfolio,
    get_trade_history,
    get_trade_signals,
    _read_trades,
)

# Watchlist shown by default (the dashboard lets you scope quotes to any set).
DEFAULT_WATCHLIST = ["AMD", "MSFT", "NVDA", "SNOW", "AAPL", "META"]
# Paper account starting cash — every user's portfolio is measured against this.
STARTING_CASH = 10_000.0

_HERE = os.path.dirname(__file__)
_STATIC_DIR = os.path.join(_HERE, "static")
_DATA_DIR = os.path.join(_HERE, "data")

APP_NAME = "financeai"

app = FastAPI(title="FinanceAI", version="0.4.0")
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

# Persistent sessions: the agent's working memory (events + state) survives a
# restart, so a continued conversation keeps its context (Chunk 8).
os.makedirs(_DATA_DIR, exist_ok=True)
_session_service = SqliteSessionService(os.path.join(_DATA_DIR, "sessions.db"))
_runner = Runner(app_name=APP_NAME, agent=root_agent, session_service=_session_service)

_bearer = HTTPBearer(auto_error=False)


@app.on_event("startup")
def _startup() -> None:
    auth.seed_default_user()
    session_store.init_db()


def _require_auth(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    """Validate the Bearer JWT and return its payload, else 401."""
    if creds is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = auth.decode_token(creds.credentials)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload


class ChatIn(BaseModel):
    message: str


class LoginIn(BaseModel):
    username: str
    password: str


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _event_text(event) -> str:
    if event.content and event.content.parts:
        return "".join(p.text or "" for p in event.content.parts)
    return ""


def _friendly_error(exc: Exception) -> str:
    """Map raw exceptions to safe, user-facing messages (no internals leaked)."""
    text = str(exc)
    if "503" in text or "UNAVAILABLE" in text or "overloaded" in text:
        return "The AI model is briefly overloaded. Please try again in a moment."
    if "429" in text or "RESOURCE_EXHAUSTED" in text:
        return "Rate limit or quota reached. Please wait a moment and try again."
    if "INVALID_ARGUMENT" in text:
        return "I hit a data formatting problem on that request. Please try rephrasing."
    return "Something went wrong handling that request. Please try again."


@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@app.get("/api/metrics")
def metrics_endpoint(user: dict = Depends(_require_auth)) -> JSONResponse:
    """In-process observability snapshot: counters + latency/token samples."""
    return JSONResponse(audit.get_metrics())


@app.get("/ready")
def ready() -> JSONResponse:
    """Readiness probe: 200 only once the RAG index has warmed up."""
    if tenk_tools.rag_ready():
        return JSONResponse({"status": "ready"})
    return JSONResponse({"status": "warming_up"}, status_code=503)


# --- chat session history (sidebar + rehydration) -------------------------


@app.get("/api/sessions")
def list_sessions(user: dict = Depends(_require_auth)) -> JSONResponse:
    """This user's chat sessions, newest first (for the history sidebar)."""
    return JSONResponse({"sessions": session_store.list_sessions(user["sub"])})


@app.get("/api/sessions/{session_id}/messages")
def session_messages(session_id: str, user: dict = Depends(_require_auth)) -> JSONResponse:
    """The stored transcript of one session, for rehydrating the chat panel."""
    return JSONResponse({"messages": session_store.get_messages(session_id, user["sub"])})


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str, user: dict = Depends(_require_auth)) -> JSONResponse:
    """Delete a chat session (metadata, transcript, and ADK working memory)."""
    ok = session_store.delete_session(session_id, user["sub"])
    try:
        await _session_service.delete_session(
            app_name=APP_NAME, user_id=user["sub"], session_id=session_id
        )
    except Exception:  # noqa: BLE001 - ADK session may not exist yet
        pass
    return JSONResponse({"deleted": ok})


class FeedbackIn(BaseModel):
    session_id: str
    rating: str  # "up" | "down"
    message: str | None = None


_FEEDBACK_PATH = os.path.join(_DATA_DIR, "feedback.jsonl")


@app.post("/api/feedback")
def feedback(body: FeedbackIn, user: dict = Depends(_require_auth)) -> JSONResponse:
    """Record a 👍/👎 on an assistant reply to feedback.jsonl."""
    if body.rating not in ("up", "down"):
        raise HTTPException(status_code=400, detail="rating must be 'up' or 'down'")
    os.makedirs(_DATA_DIR, exist_ok=True)
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "user": user["sub"],
        "session_id": body.session_id,
        "rating": body.rating,
        "message": (body.message or "")[:500],
    }
    with open(_FEEDBACK_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    audit.incr(f"feedback.{body.rating}")
    return JSONResponse({"status": "ok"})


@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(_STATIC_DIR, "index.html"))


@app.post("/api/login")
def login(body: LoginIn) -> JSONResponse:
    """Verify credentials and issue a JWT."""
    user = auth.authenticate(body.username, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = auth.make_token(user["username"], user["role"])
    return JSONResponse({"token": token, "username": user["username"], "role": user["role"]})


# --- Platform REST endpoints ---------------------------------------------
# The dashboard UI loads its watchlist, chart, stat strip, signal card, and
# portfolio through these JSON endpoints (the chat SSE stream powers only the AI
# copilot). All are auth-gated; portfolio/trades are scoped to the caller.


@app.get("/api/quotes")
async def quotes(
    tickers: str | None = None, user: dict = Depends(_require_auth)
) -> JSONResponse:
    """Lightweight quotes for the watchlist and top ticker strip."""
    syms = [t.strip().upper() for t in tickers.split(",") if t.strip()] if tickers else DEFAULT_WATCHLIST
    data = await asyncio.to_thread(market_data.get_quotes, syms)
    return JSONResponse({"quotes": data})


@app.get("/api/stock/{ticker}")
async def stock(ticker: str, user: dict = Depends(_require_auth)) -> JSONResponse:
    """Header + key stats for one stock (Markets page)."""
    data = await asyncio.to_thread(market_data.get_stock_detail, ticker)
    return JSONResponse(data)


@app.get("/api/history/{ticker}")
async def history(
    ticker: str, tf: str = "1M", user: dict = Depends(_require_auth)
) -> JSONResponse:
    """Historical close series + optional OLS forecast for the chart."""
    data = await asyncio.to_thread(market_data.get_price_series, ticker, tf)
    return JSONResponse(data)


@app.get("/api/signal/{ticker}")
async def signal(ticker: str, user: dict = Depends(_require_auth)) -> JSONResponse:
    """The BUY/SELL/HOLD trade signal for the copilot card.

    Cached ~60s: the signal blends a forecast + analyst data (several seconds of
    yfinance work), so recomputing it on every watchlist click would make ticker
    switching feel sluggish.
    """
    key = f"signal:{ticker.strip().upper()}"
    data = await asyncio.to_thread(
        market_data._cached, key, 60.0, lambda: get_trade_signals(ticker)
    )
    return JSONResponse(data)


class TradeIn(BaseModel):
    ticker: str
    action: str  # BUY | SELL
    shares: int


@app.post("/api/trade")
async def trade(body: TradeIn, user: dict = Depends(_require_auth)) -> JSONResponse:
    """Execute a paper trade from the GUI ticket (the confirm dialog is the
    human-in-the-loop approval). Scoped to the authenticated user."""
    uid_token = audit.current_user_id.set(user["sub"])
    try:
        result = await asyncio.to_thread(
            execute_trade_now, body.ticker, body.action, body.shares, None
        )
    finally:
        audit.current_user_id.reset(uid_token)
    if result.get("status") != "success":
        raise HTTPException(status_code=400, detail=result.get("message", "trade failed"))
    audit.log_event("gui_trade", user=user["sub"], **{k: result[k] for k in ("trade_id", "ticker", "action", "shares", "price")})
    return JSONResponse(result)


def _compute_portfolio() -> dict:
    """Replay this user's trade log into positions + KPIs, priced at market.

    Assumes ``current_user_id`` is already set in the calling context (the trade
    tools read it to scope to the owner).
    """
    positions = get_portfolio().get("positions", [])
    enriched, invested, mkt_value = [], 0.0, 0.0
    for p in positions:
        shares, basis = p["shares"], p["cost_basis"]
        avg_cost = basis / shares if shares else 0.0
        q = market_data.get_quote(p["ticker"])
        price = q.get("last") or avg_cost
        value = shares * price
        pl = value - basis
        invested += basis
        mkt_value += value
        enriched.append({
            "ticker": p["ticker"],
            "shares": shares,
            "avg_cost": round(avg_cost, 2),
            "market_price": round(price, 2),
            "value": round(value, 2),
            "pl": round(pl, 2),
            "pl_pct": round(pl / basis * 100, 2) if basis else 0.0,
        })

    # Cash = starting cash, net of every buy/sell notional this user made.
    cash = STARTING_CASH
    for t in _read_trades():
        cash += (-t["notional"] if t["action"] == "BUY" else t["notional"])

    total_pl = mkt_value - invested
    return {
        "positions": enriched,
        "kpis": {
            "portfolio_value": round(mkt_value, 2),
            "invested": round(invested, 2),
            "cash": round(cash, 2),
            "total_pl": round(total_pl, 2),
            "total_pl_pct": round(total_pl / invested * 100, 2) if invested else 0.0,
        },
    }


@app.get("/api/portfolio")
async def portfolio(user: dict = Depends(_require_auth)) -> JSONResponse:
    """This user's positions + account KPIs, priced at market."""
    uid_token = audit.current_user_id.set(user["sub"])
    try:
        data = await asyncio.to_thread(_compute_portfolio)
    finally:
        audit.current_user_id.reset(uid_token)
    return JSONResponse(data)


@app.get("/api/trades")
async def trades(limit: int = 20, user: dict = Depends(_require_auth)) -> JSONResponse:
    """This user's recent executed paper trades (newest first)."""
    uid_token = audit.current_user_id.set(user["sub"])
    try:
        data = await asyncio.to_thread(get_trade_history, limit)
    finally:
        audit.current_user_id.reset(uid_token)
    return JSONResponse(data)


@app.post("/api/chat/{session_id}")
async def chat(
    session_id: str, body: ChatIn, user: dict = Depends(_require_auth)
) -> StreamingResponse:
    """Stream the assistant's response to one user message as SSE."""
    user_id = user["sub"]

    async def generate():
        # Ensure the session exists (auto-create for now). Sessions are per-user.
        sess = await _session_service.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id
        )
        if sess is None:
            await _session_service.create_session(
                app_name=APP_NAME, user_id=user_id, session_id=session_id
            )

        # Record the turn for the sidebar + rehydration (user message now; the
        # assistant reply once it's fully streamed).
        session_store.touch_session(session_id, user_id, body.message)
        session_store.add_message(session_id, user_id, "user", body.message)

        # Per-request image sink: chart tools append base64 markdown here (via the
        # audit callback) as they fire; we drain it into `image` SSE events.
        images: list = []
        img_token = audit.current_images.set(images)
        emitted = 0
        # Per-request citation sink (10-K passages), emitted after the answer.
        citations: list = []
        cite_token = audit.current_citations.set(citations)
        # Per-request trade-signal sink + the session id (so trade tools can key
        # the pending-trade store to this conversation).
        signals: list = []
        sig_token = audit.current_signals.set(signals)
        sid_token = audit.current_session_id.set(session_id)
        uid_token = audit.current_user_id.set(user_id)
        disc_token = audit.current_disclaimer_required.set(False)
        sig_emitted = 0
        sent_text = ""  # accumulates streamed answer text (for the disclaimer guard)

        def _reset():
            audit.current_images.reset(img_token)
            audit.current_citations.reset(cite_token)
            audit.current_signals.reset(sig_token)
            audit.current_session_id.reset(sid_token)
            audit.current_user_id.reset(uid_token)
            audit.current_disclaimer_required.reset(disc_token)

        new_message = types.Content(role="user", parts=[types.Part(text=body.message)])
        streamed = False
        try:
            async for event in _runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=new_message,
                run_config=RunConfig(streaming_mode=StreamingMode.SSE),
            ):
                # Flush signal badge, then charts, before the text — so ordering
                # is signal → image → token.
                while sig_emitted < len(signals):
                    yield _sse({"type": "signal", **signals[sig_emitted]})
                    sig_emitted += 1
                while emitted < len(images):
                    yield _sse({"type": "image", "markdown": images[emitted]})
                    emitted += 1

                author = event.author or ""
                if author == "__progress__":
                    text = _event_text(event)
                    if text:
                        yield _sse({"type": "progress", "text": text})
                    continue
                if author == "intent_agent":
                    continue  # internal routing output, never shown

                text = _event_text(event)
                if not text:
                    continue
                if getattr(event, "partial", False):
                    streamed = True
                    sent_text += text
                    yield _sse({"type": "token", "text": text})
                else:
                    if not streamed:
                        sent_text += text
                        yield _sse({"type": "token", "text": text})
                    streamed = False  # reset for the next message in the pipeline
        except Exception as exc:  # noqa: BLE001 - surface a friendly error
            audit.incr("errors")
            audit.log_event("stream_error", error=str(exc)[:300])
            yield _sse({"type": "error", "text": _friendly_error(exc)})
            _reset()
            return

        # Drain anything captured after the last event.
        while sig_emitted < len(signals):
            yield _sse({"type": "signal", **signals[sig_emitted]})
            sig_emitted += 1
        while emitted < len(images):
            yield _sse({"type": "image", "markdown": images[emitted]})
            emitted += 1

        # Guardrail: on trade turns, guarantee the financial-advice disclaimer even
        # if the model forgot it (the prompt asks for it; we enforce it).
        if audit.current_disclaimer_required.get() and (
            guardrails.DISCLAIMER_MARKER not in sent_text.lower()
        ):
            disc = "\n\n" + guardrails.DISCLAIMER
            sent_text += disc
            yield _sse({"type": "token", "text": disc})

        # Persist the assistant reply for rehydration.
        session_store.add_message(session_id, user_id, "assistant", sent_text)

        title = (body.message or "New chat").strip()[:40]
        yield _sse({"type": "done", "title": title})

        # Emit deduplicated citations (if any) after the answer.
        if citations:
            seen, unique = set(), []
            for c in citations:
                key = (c["label"], c["detail"])
                if key not in seen:
                    seen.add(key)
                    unique.append(c)
            yield _sse({"type": "citations", "sources": unique})
        _reset()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
