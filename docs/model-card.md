# Model Card — Stock Analysis Agent

**Version:** 1.0  
**Date:** 2026-05-03  
**Maintainer:** Stock Analysis Agent project

This card documents the four models used in the Stock Analysis Agent system, their properties, known limitations, and how the system constrains each one.

---

## Models at a Glance

| Model | Provider | Role in system | Deployment |
|-------|----------|----------------|------------|
| `gemini-2.5-flash` | Google DeepMind | Agent inference — all intents; thinking enabled for complex/reasoning, disabled (`thinking_budget=0`) for simple intents; LightRAG entity extraction + image captioning | Google AI API |
| `gemini-embedding-001` | Google DeepMind | LightRAG dense document embeddings | Google AI API |
| `all-MiniLM-L6-v2` | Microsoft / Hugging Face | ChromaDB 10-K chunk embeddings | Local (on-device) |

---

## 1. Gemini 2.5 Flash

**Pinned in:** `stock_agent/model_config.py`

### Model details

| Property | Value |
|----------|-------|
| Provider | Google DeepMind |
| Architecture | Transformer-based multimodal LLM |
| Modalities | Text, images, audio, video (this system uses text only) |
| Context window | 1,000,000 tokens |
| Output token limit | Varies by agent — 256 to 3,000 (enforced in code) |
| Knowledge cutoff | Early 2025 |
| Parameter count | Not publicly disclosed |
| Pricing model | Per input/output token (Google AI API) |

### Training data

Google has not published the full training corpus. Gemini models are trained on a broad mixture of web text, books, code, and structured data. Financial domain coverage is general — the model has knowledge of publicly reported financial figures but is not fine-tuned on financial corpora.

### Capabilities relied on in this system

- Instruction following with structured output (JSON routing from intent agent)
- Tool / function calling for all 12 sub-agents
- Financial text summarisation (10-K MD&A, analyst reports)
- Multi-turn dialogue (trading approval flow)
- Chart caption generation

### Known limitations

- **Hallucination on financial figures** — the model may confabulate specific revenue or EPS numbers not retrieved by tools. Mitigated by requiring all financial figures to come from `yfinance` or SEC tools, not from LLM memory.
- **Knowledge cutoff** — company events after early 2025 are unknown to the model. Real-time data must come through tools.
- **US large-cap bias** — training data likely over-represents large US tech companies. Coverage of smaller or non-US software companies is less reliable.
- **No guaranteed disclaimer** — without enforcement, the model may omit investment disclaimers. The audit callback detects and flags `disclaimer_missing`.

### How the system constrains this model

| Constraint | Mechanism |
|------------|-----------|
| Per-agent output cap | `before_model_callback` enforces `MAX_OUTPUT_TOKENS` from `model_config.py` |
| Circuit breaker | Opens after 5 consecutive API failures; 30 s cooldown before retry |
| Disclaimer enforcement | `after_model_callback` checks trading agent responses for required disclaimer text |
| Version pinning | Model string hardcoded in `model_config.py`; not resolved dynamically |

---

## 2. Gemini 2.0 Flash

**Pinned in:** `stock_agent/lightrag_config.py` as `_ENTITY_EXTRACT_MODEL` and `_VISION_MODEL`

### Model details

| Property | Value |
|----------|-------|
| Provider | Google DeepMind |
| Architecture | Transformer-based multimodal LLM (predecessor generation to 2.5) |
| Modalities | Text, images (both used in this system) |
| Context window | 1,000,000 tokens |
| Knowledge cutoff | Early 2025 |
| Parameter count | Not publicly disclosed |

### Training data

Same general training regime as Gemini 2.5 Flash; earlier generation with lower reasoning depth. Used here for structured extraction tasks rather than open-ended generation.

### Capabilities relied on in this system

- **Entity and relationship extraction** — identifies companies, financial metrics, products, and risks from 10-K text during LightRAG ingestion
- **Image captioning** — interprets embedded charts and figures in SEC filing PDFs (RAG-Anything pipeline)

### Known limitations

- **Entity conflation in dense filings** — complex legal entities or subsidiary structures in 10-K text may be merged or misattributed during extraction
- **Image caption accuracy** — chart captions depend on visual clarity; low-resolution or heavily annotated figures may produce inaccurate descriptions
- **Older generation** — 2.0 Flash has lower reasoning depth than 2.5 Flash; complex multi-hop relationships in SEC text may be missed

### How the system constrains this model

| Constraint | Mechanism |
|------------|-----------|
| Used only at ingestion time | Not called during user query handling; only during `download_10ks.py` pipeline |
| Version pinning | Hardcoded string in `lightrag_config.py` |
| Structured output prompt | Extraction prompt constrains output to a defined JSON schema |

---

## 3. Gemini Embedding 001

**Pinned in:** `stock_agent/lightrag_config.py` as `_EMBED_MODEL`

### Model details

| Property | Value |
|----------|-------|
| Provider | Google DeepMind |
| Architecture | Dense bi-encoder (text embedding) |
| Output dimensions | 768 (default) |
| Max input tokens | 2,048 |
| Supported task types | `RETRIEVAL_DOCUMENT`, `RETRIEVAL_QUERY`, `SEMANTIC_SIMILARITY` |
| Language | Primarily English |

### Training data

Trained on a large multilingual text corpus with contrastive learning objectives optimised for semantic retrieval. Financial domain is not a primary training focus.

### Capabilities relied on in this system

- Embedding 10-K document chunks into LightRAG's vector store during ingestion
- Embedding user queries at retrieval time to find semantically relevant filing sections

### Known limitations

- **English-centric** — performance degrades for non-English filings (e.g. foreign private issuers filing 20-F in translated English)
- **Generic domain training** — embeddings for specialised financial terminology (EBITDA, goodwill impairment, deferred revenue) may be less precise than a finance-specific embedding model
- **2,048 token input limit** — 10-K chunks exceeding this limit are truncated before embedding, potentially losing tail content

### How the system constrains this model

| Constraint | Mechanism |
|------------|-----------|
| Batch size limited | `embedding_batch_num=4` in `lightrag_config.py` — reduces concurrent API calls |
| Used only at ingestion + retrieval | Not involved in generation; no output token risk |
| Version pinning | Hardcoded in `lightrag_config.py` |

---

## 4. all-MiniLM-L6-v2

**Pinned in:** `scripts/download_10ks.py`, `stock_agent/tenk_tools.py`, `stock_agent/rag_mcp_server.py`

### Model details

| Property | Value |
|----------|-------|
| Provider | Microsoft Research / Hugging Face `sentence-transformers` |
| Architecture | 6-layer MiniLM (distilled from BERT) |
| Parameters | ~22 million |
| Output dimensions | 384 |
| Max input tokens | 256 (sequences are truncated beyond this) |
| Deployment | Local — runs on CPU/GPU, no external API call |
| License | Apache 2.0 |

### Training data

Trained on over 1 billion sentence pairs using contrastive learning (multiple negatives ranking loss). Sources include MS-MARCO, SNLI, NLI datasets, Reddit comment pairs, and web-crawled parallel sentences. No dedicated financial corpus.

### Capabilities relied on in this system

- Embedding 10-K text chunks into ChromaDB for semantic search
- Powering the `tenk_agent` retrieval path — finds relevant filing sections for user questions about risk factors, MD&A, strategy, and compensation

### Known limitations

- **256-token hard truncation** — 10-K paragraphs longer than ~180 words are silently truncated before embedding. Long tables or multi-sentence risk disclosures may be partially indexed.
- **384-dimension bottleneck** — lower-dimensional space than `gemini-embedding-001` (768d); may miss fine-grained semantic distinctions in financial prose
- **Outdated financial vocabulary** — trained primarily pre-2022; newer financial instruments or regulatory terms may embed poorly
- **No cross-lingual support** — English only; foreign-language content produces near-random embeddings
- **Generic retrieval optimisation** — MiniLM was tuned for general semantic similarity, not domain-specific financial retrieval precision

### How the system constrains this model

| Constraint | Mechanism |
|------------|-----------|
| Runs locally | No network dependency; no circuit breaker needed |
| Deterministic | Embedding function is frozen; no prompt injection risk |
| Read-only at query time | Model only produces embeddings; it generates no text output |
| Version pinning | Model name hardcoded in three files; not resolved from config |
