# Enterprise Improvement Plan — Stock Analysis AI Agent

> **Date:** 2026-05-03  
> **Scope:** Evolve the current research prototype into a production-grade enterprise AI agent  
> **Reference:** See `enterprise-checklist.md` for the full gap inventory

---

## Guiding Principles

1. **Ship working software first** — each phase ends with a deployable, tested milestone.
2. **Security and compliance are non-negotiable** — never deferred past Phase 2.
3. **Observability before optimisation** — measure, then improve.
4. **Incremental cost controls** — quota management before scaling up.

---

## Phase 1 — Production Baseline
**Timeline: 2–3 weeks | Priority: Critical**

Get the app from "works on my laptop" to "can be shared with a small team."

### 1.1 Authentication
- Add API key auth (FastAPI `HTTPBearer` or `X-API-Key` header) to all endpoints.
- Store valid keys in environment config; reject all unauthenticated requests with `401`.

### 1.2 Audit Logging
- Log every request to a structured JSONL file: `timestamp`, `user_id`, `endpoint`, `query_hash`, `response_latency_ms`, `status`.
- Do not log raw query text (PII risk); log a hash for traceability.

### 1.3 Containerisation
- Write a `Dockerfile` (multi-stage: build → runtime) and `docker-compose.yml`.
- Pin all Python dependencies in `requirements.txt` with exact versions.
- Ensure the app starts cleanly from `docker compose up` with no extra setup.

### 1.4 Health Endpoints
- Add `GET /health` → `{"status": "ok"}` (liveness).
- Add `GET /ready` → checks LightRAG storage and Gemini API reachability (readiness).

### 1.5 Financial Disclaimer Enforcement
- Middleware or response post-processor that appends a disclaimer to every agent response:  
  *"This is not financial advice. For investment decisions, consult a licensed financial advisor."*

### Checklist items addressed: 1.1, 2.1, 2.5, 3.1, 7.1, 11.1, 11.4

---

## Phase 2 — Reliability & Security Hardening
**Timeline: 2–3 weeks | Priority: High**

### 2.1 Input Validation & Prompt Injection Defence
- Validate and sanitise all user inputs before passing to the LLM.
- Block or escape known prompt injection patterns (`ignore previous instructions`, `system:`, etc.).
- Enforce a maximum query length (e.g., 2 000 characters).

### 2.2 Circuit Breaker on External API Calls
- Use `tenacity` (already in scope for retry logic) or `circuitbreaker` library.
- Wrap Gemini LLM and embedding calls; open circuit after 5 consecutive failures.
- Return a degraded response ("Service temporarily unavailable, try again shortly") rather than hard error.

### 2.3 Structured Logging
- Replace `logging.basicConfig` with `structlog` or Python's `logging` with a JSON formatter.
- Include fields: `trace_id`, `level`, `message`, `latency_ms`, `model`, `tokens_used`.

### 2.4 Rate Limiting
- Add per-API-key rate limiting (e.g., 60 requests/minute) using a token bucket in Redis or an in-process counter.

### 2.5 Dependency Vulnerability Scanning
- Add `pip-audit` to CI (or pre-commit hook).
- Block merges if high-severity CVEs are found.

### 2.6 CORS & TLS
- Configure explicit CORS allowlist (not `*`).
- Require HTTPS in production (reverse proxy: Nginx or Caddy).

### Checklist items addressed: 2.2, 2.3, 2.4, 2.6, 2.7, 3.2, 3.4, 5.1

---

## Phase 3 — Cost & Quota Control
**Timeline: 1–2 weeks | Priority: High**

Gemini API costs can spike unpredictably during heavy ingestion or high query volume.

### 3.1 Per-Request Token Tracking
- After every Gemini call, record `prompt_tokens` + `completion_tokens` from the response metadata.
- Persist to a local SQLite or append to a JSONL cost log.

### 3.2 Token Budget per Request
- Enforce `max_output_tokens` on every LLM call (e.g., 1 024 for tool calls, 2 048 for final answers).
- Reject queries that exceed a configurable prompt size limit.

### 3.3 Cost-Aware Model Routing
- Simple queries (single metric lookup) → `gemini-2.0-flash` (cheap).
- Complex multi-step analysis → `gemini-2.5-pro` (accurate but expensive).
- Route based on query complexity heuristic (token count + tool count).

### 3.4 Monthly Spend Alerts
- Use Google Cloud Budgets API or a cron job that reads the cost log and sends an email/Slack alert when spend crosses a threshold.

### 3.5 Embedding Cache
- Cache embedding vectors (keyed by content hash) in Redis or a local `diskcache`.
- Skip re-embedding documents that haven't changed.

### Checklist items addressed: 4.6, 12.1, 12.2, 12.3, 12.4

---

## Phase 4 — Compliance & Data Governance
**Timeline: 2–3 weeks | Priority: High**

### 4.1 PII Detection Before Graph Storage
- Run ingested text through a PII scanner (`presidio-analyzer`) before `ainsert()`.
- Redact or flag detected PII (names, addresses, account numbers) in the knowledge graph.

### 4.2 Data Lineage
- For every agent response, record which graph nodes and document chunks were used as sources.
- Expose a `/lineage/{response_id}` endpoint that returns the provenance chain.

### 4.3 Conversation Persistence
- Store conversation history in SQLite or PostgreSQL (not in-memory).
- Enable session resumption across restarts.

### 4.4 Knowledge Graph Versioning
- Before each ingestion run, snapshot the LightRAG workspace (zip + timestamp).
- Retain last 5 snapshots; older ones archived or deleted per retention policy.

### 4.5 Data Retention Policy
- Define and document: how long conversation history is retained, how long graph snapshots are kept.
- Implement automated deletion jobs.

### Checklist items addressed: 6.1, 6.2, 6.3, 6.4, 6.5, 7.2, 7.4

---

## Phase 5 — Model Governance
**Timeline: 1–2 weeks | Priority: Medium**

### 5.1 Prompt Versioning
- Extract all system prompts and few-shot examples to versioned YAML/JSON files under `prompts/`.
- Reference prompts by version ID in code; changes require PR review.

### 5.2 Eval Gate in CI
- Add a GitHub Actions workflow that runs the RAGAS eval suite on every PR.
- Block merge if any eval metric drops below threshold (answer relevancy, faithfulness, factual correctness).

### 5.3 CODEOWNERS for Sensitive Files
- Add `.github/CODEOWNERS` requiring review from a designated owner for: `prompts/`, `eval/`, `stock_agent/lightrag_config.py`.

### 5.4 Model Card
- Document in `docs/model-card.md`: intended use, known limitations, evaluation results, out-of-scope uses.

### Checklist items addressed: 8.1, 8.3, 8.5

---

## Phase 6 — Human-in-the-Loop (HITL)
**Timeline: 2–3 weeks | Priority: Medium**

### 6.1 Confidence Score in API Response
- The eval framework already computes a User Confidence Score.
- Expose it in every API response: `{"answer": "...", "confidence": 0.82, "sources": [...]}`.

### 6.2 Low-Confidence Escalation
- If `confidence < 0.60`, append a disclaimer: *"This response has low confidence. Please verify with a primary source."*
- Optionally route to a human review queue (see 6.3).

### 6.3 Feedback Collection
- Add `POST /feedback` endpoint: `{"response_id": "...", "rating": 1|-1, "comment": "..."}`.
- Store feedback in SQLite; surface it in a simple admin dashboard.

### 6.4 Human Review Queue
- For responses below confidence threshold or with negative feedback, push to a review queue (can start as a simple email or Slack notification).
- Reviewed responses feed back into the eval golden dataset.

### Checklist items addressed: 9.1, 9.2, 9.3, 9.4

---

## Phase 7 — Observability Uplift
**Timeline: 2–3 weeks | Priority: Medium**

### 7.1 Prometheus Metrics
- Instrument the FastAPI app with `prometheus-fastapi-instrumentator`.
- Expose: `http_request_duration_seconds`, `llm_token_count_total`, `agent_error_total`, `knowledge_graph_query_latency_seconds`.

### 7.2 Grafana Dashboard
- Deploy Grafana (Docker Compose service).
- Build dashboards for: request volume, p50/p95/p99 latency, error rates, token spend per day.

### 7.3 SLO Alerting
- Define SLOs: p95 latency < 5 s, error rate < 1%, eval pass rate > 90%.
- Configure Grafana alerts that fire when SLOs are breached.

### 7.4 Distributed Tracing
- Add OpenTelemetry instrumentation to the agent orchestration loop.
- Send traces to a local Jaeger instance (Docker Compose) or cloud tracing backend.

### Checklist items addressed: 5.2, 5.3, 5.4, 5.5, 5.6

---

## Roadmap Summary

```
Phase 1  ████████░░░░░░░░░░░░░░░░░░░░  2–3 wks   Production Baseline
Phase 2  ████████░░░░░░░░░░░░░░░░░░░░  2–3 wks   Reliability & Security
Phase 3  ████░░░░░░░░░░░░░░░░░░░░░░░░  1–2 wks   Cost & Quota Control
Phase 4  ████████░░░░░░░░░░░░░░░░░░░░  2–3 wks   Compliance & Governance
Phase 5  ████░░░░░░░░░░░░░░░░░░░░░░░░  1–2 wks   Model Governance
Phase 6  ████████░░░░░░░░░░░░░░░░░░░░  2–3 wks   Human-in-the-Loop
Phase 7  ████████░░░░░░░░░░░░░░░░░░░░  2–3 wks   Observability Uplift

Total estimated effort: 12–19 weeks (3–5 months)
```

---

## Quick Wins (do this week, < 1 day each)

| Item | Why | How |
|------|-----|-----|
| Add `X-API-Key` auth | Blocks unauthenticated access immediately | 20 lines of FastAPI middleware |
| Add `/health` endpoint | Enables load balancer and monitoring | 5 lines |
| Add financial disclaimer middleware | Regulatory risk reduction | 10 lines |
| Set `max_output_tokens` on all Gemini calls | Prevents runaway costs | Config change |
| Add `pip-audit` to pre-commit | Catches known CVEs | `pip install pip-audit && pip-audit` |
| Move secrets to a `.env.example` template | Documents required vars | 5 minutes |

---

*This document is a living plan. Update status in `enterprise-checklist.md` as items are completed.*
