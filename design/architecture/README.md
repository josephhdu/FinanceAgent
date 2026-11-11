# Architecture Documentation

Design documents for the stock analysis multi-agent system.

## Documents

| File | Contents |
|------|----------|
| [01-orchestration-and-workflows.md](01-orchestration-and-workflows.md) | Root agent, route map, pipeline execution, callback architecture |
| [02-intent-extraction.md](02-intent-extraction.md) | Intent agent, 12 intent types, JSON schema, classification rules |
| [03-mcp-integration.md](03-mcp-integration.md) | Finance MCP server, tools, direct Python vs MCP decision |
| [04-a2a-integration.md](04-a2a-integration.md) | A2A protocol, financial_report_server, agent cards (pdf_agent now uses direct MCP tools) |
| **agents/** | Per-agent design documents |
| [agents/price-agent.md](agents/price-agent.md) | Price lookup, resolve_ticker + get-ticker-info workflow |
| [agents/prediction-agent.md](agents/prediction-agent.md) | OLS regression forecast, fetch_and_forecast tool |
| [agents/alert-agent.md](agents/alert-agent.md) | Drop alert detection, threshold classification |
| [agents/financial-report-agent.md](agents/financial-report-agent.md) | Financial report sections, A2A dual-use pattern |
| [agents/visualization-agent.md](agents/visualization-agent.md) | Four chart types, base64 context isolation |
| [agents/pdf-agent.md](agents/pdf-agent.md) | PDF compilation, direct MCP tool calls (resolve_ticker, get-ticker-info, ticker-earning) |
| [agents/tenk-agent.md](agents/tenk-agent.md) | 10-K RAG, ChromaDB search, multi-query strategy |
| [agents/comparison-pipeline.md](agents/comparison-pipeline.md) | Two-agent comparison pipeline (trend + insights) |
| [agents/investment-research-agent.md](agents/investment-research-agent.md) | LightRAG GraphRAG, RAG-Anything multimodal ingestion, cross-section analysis |
| [agents/trading-agent.md](agents/trading-agent.md) | Trading agent: two-turn approval flow, signal scoring, mock execution, trade tools |
| [agents/market-alert-agent.md](agents/market-alert-agent.md) | Market alert agent: chat alert_agent + background monitor — tools, condition logic, SSE delivery, integration points, message flows |
| [agents/market-alert-monitor.md](agents/market-alert-monitor.md) | Market alert monitor: system architecture, component diagram, sequence diagrams, data model |
| [05-guardrails.md](05-guardrails.md) | 6 guardrail checks, PII tokenisation, injection detection, token limit |
| [06-evaluation.md](06-evaluation.md) | Three-level metrics framework, formulas, dashboard, CLI, `--gate` flag |
| [07-rag.md](07-rag.md) | ChromaDB setup, embedding model, ingestion, search internals |
| [08-ragas-test-cases.md](08-ragas-test-cases.md) | Test case structure, 33 intent + 17 E2E cases, RAGAS metrics |
| [09-langfuse-integration.md](09-langfuse-integration.md) | Trace hierarchy, in-process metrics, token cost formula |
| [Architecture.md](Architecture.md) | System overview, component rationale, sequence diagrams, cost tracking, prompt versioning |
| [10-web-ui.md](10-web-ui.md) | FastAPI server, SSE protocol, image capture, session model, frontend design |

## Quick Links

- **Adding a new pipeline** → [01-orchestration-and-workflows.md#adding-a-new-pipeline](01-orchestration-and-workflows.md)
- **Adding test cases** → [08-ragas-test-cases.md#adding-new-test-cases](08-ragas-test-cases.md)
- **Running eval** → [06-evaluation.md#running-the-eval](06-evaluation.md)
- **Eval gate (before saving prompt changes)** → [06-evaluation.md#regression-gate](06-evaluation.md)
- **Iterating on a prompt** → [Architecture.md#514-model--prompt-versioning--practice-13](Architecture.md)
- **Viewing cost spend** → `python -m stock_agent.cost_report --all --by-agent`
- **RAG data ingestion** → [07-rag.md#data-ingestion](07-rag.md)
- **A2A reference design** → [04-a2a-integration.md](04-a2a-integration.md)
