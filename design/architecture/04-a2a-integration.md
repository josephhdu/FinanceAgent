# A2A Integration

## Overview

The system uses Google ADK's **Agent-to-Agent (A2A)** protocol to allow the `pdf_agent` to delegate financial narrative generation to the `financial_report_agent` running as a separate HTTP service. This decouples the two agents so the financial report service can be scaled, replaced, or reused independently.

> **Status update**: As of May 2026, `pdf_agent` no longer uses A2A. It was decoupled from `financial_report_agent` and now fetches financial data directly via MCP tools (`get-ticker-info`, `ticker-earning`). The `financial_report_server.py` sidecar and `RemoteA2aAgent` are no longer required for PDF report generation.
>
> The A2A infrastructure (agent cards, `to_a2a()` server wrapper, `RemoteA2aAgent` client) remains in the codebase and the documentation below is preserved as the reference design for any future agent that needs cross-process A2A delegation.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│           ADK Runtime  (stock_orchestrator)             │
│                                                         │
│   pdf_agent  (LlmAgent)                                 │
│     │                                                   │
│     ├─ Tool: financial_report_remote  (RemoteA2aAgent)  │
│     │         HTTP POST to localhost:8001               │
│     │                                                   │
│     └─ Tool: compile_pdf_report  (direct Python)        │
└─────────────────────────────────────────────────────────┘
                    │  HTTP / A2A protocol
                    │
┌───────────────────▼─────────────────────────────────────┐
│        financial_report_server.py  (separate process)   │
│                                                         │
│   Uvicorn ASGI server                                   │
│   Port: 8001                                            │
│   Path: /a2a/financial_report_agent                     │
│                                                         │
│   financial_report_agent  (LlmAgent)                   │
│     Tools: get-ticker-info, ticker-earning (MCP)        │
│     Tools: resolve_ticker (direct Python)               │
└─────────────────────────────────────────────────────────┘
```

---

## Agent Cards

Agent cards follow the A2A specification and describe each agent's capabilities to clients and other agents.

### stock_orchestrator card (`agent_cards/stock_orchestrator.json`)

```json
{
  "name": "stock_orchestrator",
  "protocolVersion": "0.2.0",
  "url": "http://localhost:8080/a2a/stock_orchestrator",
  "capabilities": {
    "streaming": false,
    "pushNotifications": false
  },
  "skills": [
    { "id": "intent_extraction",   "name": "Intent Extraction",   "tags": ["routing","NLP"] },
    { "id": "price_lookup",        "name": "Price Lookup",        "tags": ["price","market-cap"] },
    { "id": "price_prediction",    "name": "Price Prediction",    "tags": ["forecast","OLS"] },
    { "id": "drop_alert",          "name": "Drop Alert",          "tags": ["alert","threshold"] },
    { "id": "financial_report",    "name": "Financial Report",    "tags": ["revenue","margins"] },
    { "id": "visualization",       "name": "Visualization",       "tags": ["chart","matplotlib"] },
    { "id": "pdf_report",          "name": "PDF Report",          "tags": ["pdf","export"] }
  ]
}
```

### financial_report_agent card (`agent_cards/financial_report_agent.json`)

```json
{
  "name": "financial_report_agent",
  "protocolVersion": "0.2.0",
  "url": "http://localhost:8001/a2a/financial_report_agent",
  "skills": [
    { "id": "income_statement_summary"     },
    { "id": "balance_sheet_summary"        },
    { "id": "cash_flow_summary"            },
    { "id": "valuation_ratios"             },
    { "id": "financial_health_assessment"  }
  ]
}
```

---

## financial_report_server.py

The server is a thin wrapper using ADK's `to_a2a()` helper:

```python
from google.adk.a2a import to_a2a
from stock_agent.financial_report_agent import financial_report_agent

app = to_a2a(financial_report_agent)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="localhost", port=8001)
```

**Run command**:
```bash
python financial_report_server.py
```

The server must be running before any `pdf_agent` invocation. The orchestrator does not start it automatically.

---

## pdf_agent's A2A Client

Inside `pdf_agent.py`, the remote agent is declared as a sub-agent using `RemoteA2aAgent`:

```python
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent

financial_report_remote = RemoteA2aAgent(
    name="financial_report_remote",
    agent_card_url="http://localhost:8001/a2a/financial_report_agent/.well-known/agent-card.json",
)

pdf_agent = LlmAgent(
    name="pdf_agent",
    model="gemini-2.5-flash",
    sub_agents=[financial_report_remote],
    tools=[compile_pdf_report],
    ...
)
```

When the LLM inside `pdf_agent` decides to delegate to `financial_report_remote`, ADK internally calls `transfer_to_agent("financial_report_remote")`. ADK then forwards the message to the remote service via HTTP.

---

## Message Flow: PDF Report Generation

**Query**: "Generate a PDF report for Microsoft"

```
User ──► stock_orchestrator
          │
          ├─► intent_agent → { "intent": "PDF_REPORT", "companies": ["MSFT"] }
          │
          └─► pdf_agent
                │
                │  Step 1: Delegate to financial_report_remote
                ├─► transfer_to_agent("financial_report_remote")
                │     │
                │     │  A2A HTTP POST
                │     │  POST http://localhost:8001/a2a/financial_report_agent
                │     │  Body: { "message": { "role": "user",
                │     │           "parts": [{"text": "Provide a financial report for MSFT"}] }}
                │     │
                │     ▼
                │   financial_report_agent  (separate process)
                │     Tool: resolve_ticker("MSFT") → "MSFT"
                │     Tool: get-ticker-info("MSFT")  [MCP → yfinance]
                │     Tool: ticker-earning("MSFT")   [MCP → yfinance]
                │     LLM: formats full narrative (income, balance sheet, cash flow, valuation)
                │     ──► HTTP response: financial narrative text (Markdown)
                │
                │  Step 2: Compile PDF with narrative
                └─► compile_pdf_report(
                        ticker_or_name="MSFT",
                        financial_summary="<narrative from financial_report_agent>",
                        include_prediction=True,
                        include_financials=True,
                        include_alerts=True,
                        alert_threshold_percent=5.0
                    )
                    │
                    ├─ Internally calls: fetch price history, run forecast, evaluate alerts
                    ├─ Renders charts (price history, forecast, financial metrics)
                    ├─ ReportLab builds PDF → /output/MSFT_report_20260502_114237.pdf
                    └─ Returns: { "message": "PDF saved", "file_path": "/output/..." }

Final response to user: "Your Microsoft PDF report has been generated at /output/MSFT_report_20260502_114237.pdf"
```

---

## Deployment Topology

For development and evaluation, both processes run on localhost:

```
Terminal 1:
  python financial_report_server.py
  # Starts on http://localhost:8001

Terminal 2:
  adk web --port 8080
  # Starts orchestrator on http://localhost:8080

Terminal 3:
  python -m eval.run_eval --category pdf --e2e-only
  # Eval runs; pdf_agent cases require Terminal 1 to be up
```

The orchestrator at 8080 and the financial report service at 8001 are independent; the financial report service can be deployed separately on a different host by updating `agent_card_url` in `pdf_agent.py`.

---

## A2A vs Direct Sub-Agent

The `financial_report_agent` runs in-process as a direct sub-agent of the orchestrator for the `ANNUAL_FINANCIAL` pipeline. The A2A path (`financial_report_remote`) was previously used by `pdf_agent` but has been removed in favour of direct MCP tool calls. The A2A design remains available as a reference for any future pipeline that needs cross-process delegation or independent scaling of a sub-agent.
