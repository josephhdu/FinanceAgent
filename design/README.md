# Design blueprint

> **Read this first:** these documents describe the *planned* system, not the code
> in [`app/`](../app/). The app implements a scoped-down v1. Several things described
> here were **never built**.

| Folder | Contents |
|---|---|
| [`architecture/`](architecture/) | Architecture docs: orchestration, intent extraction, MCP, guardrails, RAG, evaluation, per-agent designs |
| [`prd/`](prd/) | Product requirements document and the epic/story breakdown |

## Built in v1

Deterministic orchestrator and intent routing · price, prediction, visualization,
10-K (RAG) and trading agents · finance MCP server · guardrails (injection, PII
masking, token ceiling, disclaimer) · JWT auth · audit logging and metrics ·
intent/routing eval harness · React dashboard.

## Designed here but not built

- Agent-to-agent (A2A) protocol and the financial-report server
- PDF report agent and downloads
- Alert agent and the background market-alert monitor
- Comparison pipeline and GraphRAG investment-research agent (LightRAG / RAG-Anything)
- Role-based access control
- LangFuse tracing and RAGAS end-to-end evaluation
- Encrypted PII store

The version history and dates in the PRD are from the planning phase; they don't
describe releases of this code.
