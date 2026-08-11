# Enterprise AI Agent App — Readiness Checklist

> **App:** Stock Analysis / Investment Research Agent  
> **Date:** 2026-05-03  
> **Status key:** ✅ Done &nbsp; 🔶 Partial &nbsp; ❌ Missing

---

## 1. Identity & Access Management (IAM)

| # | Item | Status | Notes |
|---|------|--------|-------|
| 1.1 | Authentication on all API endpoints | ✅ | JWT Bearer auth on all `/api/*` routes; `POST /api/login` issues HS256 token (8h expiry); `_require_auth` FastAPI dependency guards every protected route |
| 1.2 | Role-based access control (RBAC) | ✅ | 3 roles (viewer/analyst/admin) declared in `stock_agent/roles.yaml`; enforced in orchestrator before pipeline runs; role badge + logout in UI |
| 1.3 | API key rotation / expiry policy | ❌ | Keys stored in `.env`, no rotation |
| 1.4 | Service-to-service auth (internal APIs) | ❌ | Not implemented |
| 1.5 | Audit log — who called what and when | ❌ | No audit trail |

---

## 2. Security

| # | Item | Status | Notes |
|---|------|--------|-------|
| 2.1 | Secrets in environment variables (not source) | 🔶 | `.env` used but not excluded from all paths |
| 2.2 | Input validation / prompt injection defence | ❌ | Raw user input passed to LLM |
| 2.3 | Output sanitisation (PII, sensitive data) | ❌ | No filtering on LLM responses |
| 2.4 | Dependency vulnerability scanning (pip-audit) | ❌ | Not in CI |
| 2.5 | HTTPS / TLS on all external endpoints | ❌ | No TLS config |
| 2.6 | Rate limiting on public endpoints | ❌ | No throttling |
| 2.7 | CORS policy configured | ❌ | Default permissive |

---

## 3. Reliability & Resilience

| # | Item | Status | Notes |
|---|------|--------|-------|
| 3.1 | Health-check endpoint (`/health`, `/ready`) | ✅ | `GET /health` (liveness) and `GET /ready` (readiness: Gemini key, ChromaDB, LightRAG dir, audit log) added to `web_server.py` |
| 3.2 | Circuit breaker on external API calls | ❌ | No tenacity/breaker pattern |
| 3.3 | Retry with exponential backoff on embeddings | ✅ | Implemented in `_gemini_embed` |
| 3.4 | Fallback / degraded-mode behaviour | ❌ | Hard failure on Gemini quota exceeded |
| 3.5 | Graceful shutdown handling | ❌ | No SIGTERM handler |
| 3.6 | Timeout on all external HTTP calls | 🔶 | Some calls have `timeout=30/60` |
| 3.7 | Dead-letter / retry queue for failed ingestion | ❌ | Failed jobs logged but not retried |

---

## 4. Scalability & Performance

| # | Item | Status | Notes |
|---|------|--------|-------|
| 4.1 | Async request handling | 🔶 | Core LightRAG calls async; web layer TBD |
| 4.2 | Connection pooling (DB, vector store) | ❌ | Not configured |
| 4.3 | Caching layer (Redis / in-memory) for repeated queries | ❌ | Every query hits LLM |
| 4.4 | Horizontal scaling / stateless design | ❌ | LightRAG state is local filesystem |
| 4.5 | Load testing baseline established | ❌ | No benchmarks |
| 4.6 | Token budget enforcement per request | ❌ | No max-token guard |

---

## 5. Observability & Monitoring

| # | Item | Status | Notes |
|---|------|--------|-------|
| 5.1 | Structured JSON logging | ❌ | Plain text `logging` only |
| 5.2 | Distributed tracing (OpenTelemetry) | ❌ | Not instrumented |
| 5.3 | Metrics endpoint (Prometheus / StatsD) | ❌ | No metrics exposed |
| 5.4 | Latency / throughput dashboards | ❌ | No Grafana / equivalent |
| 5.5 | Error rate alerting | ❌ | No alerting |
| 5.6 | LLM-specific metrics (token usage, cost/request) | ❌ | Not tracked |
| 5.7 | Eval pipeline results tracked over time | 🔶 | RAGAS eval exists; no trend dashboard |

---

## 6. Data Management & Governance

| # | Item | Status | Notes |
|---|------|--------|-------|
| 6.1 | Data lineage — source traced to response | ❌ | No provenance chain |
| 6.2 | Knowledge graph versioning / snapshots | ❌ | LightRAG workspace is overwritten |
| 6.3 | Conversation / session persistence | ✅ | `sessions.db` (ADK `SqliteSessionService`) + `sessions_meta.db` (display metadata); both survive restart |
| 6.4 | Data retention & deletion policy | ❌ | Not defined |
| 6.5 | PII detection before storing to graph | ❌ | No PII scanner |
| 6.6 | Backup of vector store and graph DB | ❌ | No backup strategy |
| 6.7 | Manifest of ingested documents | ✅ | `ingested_reports.jsonl` exists |

---

## 7. Compliance & Regulatory

| # | Item | Status | Notes |
|---|------|--------|-------|
| 7.1 | Financial advice disclaimer on all responses | ❌ | No disclaimer enforced |
| 7.2 | GDPR / CCPA data subject rights handling | ❌ | Not implemented |
| 7.3 | SEC / FINRA disclosure awareness | ❌ | Agent may produce regulated content |
| 7.4 | Model output audit trail for compliance | ❌ | No immutable log |
| 7.5 | Data residency / sovereignty controls | ❌ | Gemini API — region not pinned |
| 7.6 | Terms of service for data sources (EDGAR) | ✅ | Public data, rate-limited |

---

## 8. Model Governance

| # | Item | Status | Notes |
|---|------|--------|-------|
| 8.1 | Prompt versioning (prompts in version control) | 🔶 | Prompts in code but not versioned separately |
| 8.2 | Model version pinned (not `latest`) | ✅ | `gemini-2.5-flash` pinned for all agents |
| 8.3 | Eval gate blocks deployment on regression | ❌ | Eval exists but not wired to CI/CD |
| 8.4 | Bias / fairness testing on financial outputs | ❌ | Not assessed |
| 8.5 | Model card / intended use documented | ✅ | `docs/model-card.md` — model-centric: architecture, training data, limitations, and system constraints for all 4 models |
| 8.6 | Shadow mode / canary deployment support | ❌ | No staged rollout |

---

## 9. Human-in-the-Loop (HITL)

| # | Item | Status | Notes |
|---|------|--------|-------|
| 9.1 | Confidence score surfaces uncertainty to user | 🔶 | Confidence score computed; not shown in UI |
| 9.2 | Low-confidence responses flagged / escalated | ❌ | No escalation path |
| 9.3 | User feedback collection (thumbs up/down) | ❌ | No feedback mechanism |
| 9.4 | Human review queue for edge cases | ❌ | No queue |
| 9.5 | Override mechanism for agent decisions | ❌ | Not implemented |

---

## 10. Multi-Agent Coordination

| # | Item | Status | Notes |
|---|------|--------|-------|
| 10.1 | Agent registry / discovery | ❌ | Agents hardcoded |
| 10.2 | Orchestrator error handling (sub-agent failure) | ❌ | Failures bubble up uncaught |
| 10.3 | Shared context / memory across agents | ✅ | LightRAG graph (domain knowledge) + `ChromaMemoryService` (cross-session conversational memory): turn pairs embedded with `gemini-embedding-001`, stored in `memory_db/`, searched semantically at start of every invocation, injected as `<PAST_CONVERSATIONS>` system instruction |
| 10.4 | Idempotency of agent tool calls | 🔶 | Ingestion deduplicates; queries do not |
| 10.5 | Agent output validation before chaining | ✅ | `_validate_step_output` runs between pipeline steps: content check + 9 error-phrase markers; yields `_abort_event` and halts pipeline on failure |

---

## 11. DevOps & Deployment

| # | Item | Status | Notes |
|---|------|--------|-------|
| 11.1 | Containerised (Docker / OCI image) | ❌ | Local Python environment only |
| 11.2 | CI pipeline (lint, test, eval on PR) | ❌ | No CI configured |
| 11.3 | CD pipeline (automated deploy on merge) | ❌ | Manual deployment |
| 11.4 | Infrastructure as Code (Terraform / Pulumi) | ❌ | Not provisioned |
| 11.5 | Environment parity (dev / staging / prod) | ❌ | Single environment |
| 11.6 | Secret management (Vault / AWS SM) | ❌ | `.env` file |
| 11.7 | Rollback mechanism | ❌ | Not implemented |

---

## 12. Cost Management

| # | Item | Status | Notes |
|---|------|--------|-------|
| 12.1 | Per-request token cost tracking | ❌ | Not tracked |
| 12.2 | Monthly budget alerts on AI APIs | ❌ | No spend alerts |
| 12.3 | Cost-aware model routing (cheap for simple queries) | ✅ | `_CHEAP_INTENTS` (PRICE, ALERT, VISUALIZATION, PDF_REPORT) run `gemini-2.5-flash` with `thinking_budget=0` via `before_model_token_guardrail`; complex intents enable thinking |
| 12.4 | Embedding cache to avoid re-embedding duplicates | ❌ | Not implemented |
| 12.5 | Ingestion cost controls (batch size tuned) | ✅ | `embedding_batch_num=4`, `llm_model_max_async=1` |

---

## 13. Testing Strategy

| # | Item | Status | Notes |
|---|------|--------|-------|
| 13.1 | Unit tests for core business logic | ❌ | No unit tests |
| 13.2 | Integration tests for API endpoints | ❌ | No integration tests |
| 13.3 | LLM output evaluation (RAGAS) | ✅ | RAGAS eval framework implemented |
| 13.4 | Adversarial / red-team prompt testing | ❌ | Not performed |
| 13.5 | Load / stress tests | ❌ | Not performed |
| 13.6 | Data pipeline tests (ingestion correctness) | ❌ | No tests for ingestion |

---

## 14. User Experience & Product

| # | Item | Status | Notes |
|---|------|--------|-------|
| 14.1 | Error messages are user-friendly | ✅ | `_friendly_error()` classifies exceptions into 5 safe categories; global exception handler returns clean 500; raw exceptions never reach the browser |
| 14.2 | Response latency within acceptable SLA | ❌ | No SLA defined or measured |
| 14.3 | Streaming responses for long outputs | ❌ | Blocking responses only |
| 14.4 | Source citations in responses | ✅ | Tool-level citation capture via `after_tool_callback` ContextVar; `{"type":"citations"}` SSE event; collapsible "📎 Sources" row in UI; persisted in `sessions_meta.db` |
| 14.5 | Onboarding / help documentation | ❌ | No user-facing docs |
| 14.6 | Accessibility (WCAG 2.1 AA) | ❌ | Not assessed |

---

## Summary Scorecard

| Category | Done | Partial | Missing | Total |
|----------|------|---------|---------|-------|
| IAM | 2 | 0 | 3 | 5 |
| Security | 1 | 1 | 5 | 7 |
| Reliability | 2 | 1 | 4 | 7 |
| Scalability | 0 | 1 | 5 | 6 |
| Observability | 0 | 1 | 6 | 7 |
| Data Governance | 2 | 0 | 5 | 7 |
| Compliance | 1 | 0 | 5 | 6 |
| Model Governance | 2 | 1 | 3 | 6 |
| HITL | 0 | 1 | 4 | 5 |
| Multi-Agent | 2 | 1 | 2 | 5 |
| DevOps | 0 | 0 | 7 | 7 |
| Cost Management | 2 | 0 | 3 | 5 |
| Testing | 1 | 0 | 5 | 6 |
| UX & Product | 2 | 0 | 4 | 6 |
| **Total** | **17** | **8** | **60** | **85** |

**Overall readiness: 17/85 fully done (20%) — research prototype stage.**
