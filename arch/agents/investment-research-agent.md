# Investment Research Agent

## Purpose

Performs multimodal, cross-section analysis of quarterly (10-Q) and annual (10-K) PDF reports. Unlike the `tenk_agent` — which answers single-section questions via vector similarity over plain text — this agent reasons across multiple content types within the same filing simultaneously: prose paragraphs, structured tables, and chart/image captions are all first-class nodes in a knowledge graph.

**Canonical use case:**
> "Compare Company A's revenue growth table in Q3 with the executive summary, and highlight any mentioned risks in the accompanying chart."

This requires linking three document regions — a table, a prose section, and a figure — across entities they share. Pure vector search cannot do this because each region is a separate chunk with no explicit relationship.

---

## Configuration

| Field | Value |
|---|---|
| Name | `investment_research_agent` |
| Model | `MODEL_VERSION` (from `model_config.py`) |
| Runs in pipeline | `INVESTMENT_RESEARCH` |
| Direct Python tools | `list_indexed_reports`, `query_investment_research`, `ingest_report_pdf` |
| MCP tools | None |
| Storage backend | LightRAG (NetworkX graph + nano-vectordb), `lightrag_storage/` |
| Ingestion backend | RAG-Anything (MinerU PDF parser + vision LLM for charts) |

---

## LightRAG — What It Is and How It Works

LightRAG (from HKUDS) is a **GraphRAG** framework that augments vector search with a knowledge graph built from the ingested documents. Where a traditional RAG system splits documents into flat text chunks and retrieves by embedding similarity, LightRAG additionally extracts **entities** (companies, people, metrics, risks) and **relationships** between them, and stores those as a property graph. At query time it combines graph traversal with vector search, enabling multi-hop reasoning that flat retrieval cannot do.

### From chunks to a graph — the ingestion pass

Every chunk of ingested text goes through two steps:

```
Text chunk (from any source — prose, table, chart caption)
    │
    ├─ Step 1: Embed  →  vector stored in nano-vectordb
    │                    (enables similarity search across all chunks)
    │
    └─ Step 2: LLM entity/relation extraction
                  prompt: "Extract entities and their relationships from this text"
                  │
                  ├─ Entities:      Company("Microsoft"), Metric("Azure revenue"),
                  │                 Risk("FX headwind"), Executive("Satya Nadella")
                  └─ Relationships: [Azure revenue] --reported_in--> [Q3 2025 10-Q]
                                    [Satya Nadella] --mentioned--> [AI strategy risk]
                                    [Azure revenue] --derived_from--> [Intelligent Cloud segment]

                  Stored in: graph_chunk_entity_relation.graphml  (NetworkX)
                             vdb_entities.json, vdb_relationships.json  (nano-vectordb)
```

The LLM extraction pass is what makes ingestion slow (one LLM call per chunk) and what makes multi-hop queries possible at retrieval time.

### Query modes — how graph and vector combine

LightRAG exposes five retrieval strategies. Each balances thoroughness against speed:

```
Query: "Compare revenue table with executive summary and chart risks"

  naive  ─────────────────────────────────► vector similarity only
                                             Returns chunks most similar to query text.
                                             Fast (0.5–2 s). Misses cross-section links.

  local  ──► find entity "Microsoft"         Traverses the local neighbourhood of matched
             → retrieve adjacent nodes        entities in the graph.
             → re-rank + summarise           Good for: specific company / metric questions.

  global ──► cluster the full graph          Builds community summaries across all entities.
             into topic communities          Good for: sector-wide or cross-company themes.
             → retrieve community summary

  hybrid ──► local + global combined         Default for cross-section analysis.
                                             Captures both specific entity links
                                             and broader document-level context.

  mix    ──► full graph traversal            Most thorough. Slow (6–15 s).
             + vector re-rank
```

### What the graph enables that vector search cannot

```
VECTOR SEARCH (ChromaDB / naive mode):
  "revenue growth" → returns top-N chunks by cosine similarity
  Each chunk is independent. The system has no knowledge that the
  revenue number in the table and the CFO quote in the prose
  both refer to the same entity for the same period.

GRAPH SEARCH (LightRAG local/hybrid):
  "Azure revenue Q3 2025"
      │
      └─ entity: [Azure Revenue Q3 2025: $28.9B]
           │── reported_in ──► [Q3 2025 10-Q, Table 2, row 3]
           │── mentioned   ──► [Executive Summary, para 1: "Azure AI adoption"]
           │── shown_in    ──► [Chart caption: "Azure Q1–Q3 sequential bar chart"]
           └── risk_noted  ──► [Risk Factors: "FX headwind ~1pp"]

  All four document regions are linked to the same entity.
  A single query retrieves evidence from all four simultaneously.
```

---

## RAG-Anything — What It Is and How It Works

RAG-Anything (also from HKUDS) is a **multimodal document ingestion** layer that sits in front of LightRAG. Its job is to parse complex PDF documents — which contain not just prose but also tables, charts, images, and equations — and convert every content type into a text representation that LightRAG can process and index.

Without RAG-Anything, ingesting a PDF would mean extracting raw text only. Tables would lose their structure (rows become a jumble of numbers), charts would be silently skipped, and equations would be garbled. RAG-Anything solves this by treating each content type differently.

### The MinerU parsing pipeline

RAG-Anything uses **MinerU** as its PDF layout analyser. MinerU performs document understanding — it identifies the bounding boxes and types of every element on every page before any text is extracted.

```
PDF page
    │
    ▼  MinerU layout model (reads page pixels)
    │
    ├─ Region type: TEXT
    │    → extract prose text
    │    → pass to LightRAG as a plain chunk
    │
    ├─ Region type: TABLE
    │    → extract cell values and structure
    │    → convert to markdown table
    │    │
    │    │  | Segment          | Q3 Revenue | YoY Change |
    │    │  |------------------|------------|------------|
    │    │  | Intelligent Cloud| $28.9B     | +22%       |
    │    │  | Productivity     | $19.8B     | +13%       |
    │    │
    │    → pass to LightRAG as a structured chunk
    │      (LLM extracts: Metric("Intelligent Cloud revenue"), Value("$28.9B"), Period("Q3 2025"))
    │
    ├─ Region type: FIGURE / CHART
    │    → extract image bytes (PNG)
    │    → send to vision LLM (_gemini_vision) with prompt:
    │       "Describe this chart. Include axis labels, values, trends, and any annotations."
    │    → vision LLM returns caption:
    │       "Bar chart showing Azure revenue for Q1–Q3 FY2025:
    │        Q1 $26.7B (+21% YoY), Q2 $28.5B (+19%), Q3 $28.9B (+18%).
    │        Annotation: 'FX headwind ~1pp'. Trend: sequential deceleration."
    │    → pass caption to LightRAG as a chunk
    │      (LLM extracts: Metric("Azure revenue"), Trend("deceleration"), Risk("FX headwind"))
    │
    └─ Region type: EQUATION
         → extract LaTeX representation
         → convert to plain English description
         → pass to LightRAG as a chunk
```

### Why this matters for investment research

Financial PDFs are dense with structured content that plain text extraction destroys:

```
What a naive PDF text extractor sees:
  "Revenue 65,585 58,285 Intelligent Cloud 28,919 24,093 ..."
  (table rows collapsed into a stream of numbers with no labels)

What RAG-Anything + MinerU preserves:
  | Segment            | Q3 FY2025 | Q3 FY2024 | Change |
  |--------------------|-----------|-----------|--------|
  | Total Revenue      | $65,585M  | $58,285M  | +12.5% |
  | Intelligent Cloud  | $28,919M  | $24,093M  | +20.0% |

  And separately, for the bar chart on page 8:
  "Sequential Azure growth Q1–Q3 FY2025: 21% → 19% → 18%.
   Management annotation: FX headwind approximately 1 percentage point."
```

The structured table and the chart caption both flow into LightRAG as separate chunks with their own entity nodes, but they share entities (`Azure revenue`, `Q3 FY2025`) so the graph connects them automatically.

### How RAG-Anything relates to LightRAG in this codebase

```
get_raganything()
    │
    ├─ lightrag=get_lightrag()       ← same singleton used by query tools
    │                                   ingestion and queries share one graph
    ├─ llm_model_func=_gemini_complete   ← entity/relation extraction
    ├─ vision_model_func=_gemini_vision  ← chart captioning
    ├─ embedding_func=_gemini_embed      ← vector index population
    └─ config=RAGAnythingConfig(
           working_dir=LIGHTRAG_WORKSPACE,
           enable_image_processing=True,    ← charts and figures
           enable_table_processing=True,    ← structured tables
           enable_equation_processing=True  ← LaTeX / math
       )
```

The `lightrag=get_lightrag()` argument is the critical link: by passing the pre-built LightRAG instance, RAG-Anything writes its parsed content directly into the same graph that `query_investment_research` reads from. The two are not separate stores.

---

## Why LightRAG Instead of ChromaDB

| Dimension | ChromaDB (`tenk_agent`) | LightRAG (`investment_research_agent`) |
|---|---|---|
| Retrieval model | Vector cosine similarity | Graph traversal + vector |
| Data structure | Flat text chunks | Entity–relationship knowledge graph |
| Multi-hop queries | ✗ | ✅ |
| Cross-section linking | ✗ (separate chunks, no edges) | ✅ (entities shared across table/chart/prose nodes) |
| Multimodal content | Text only | Text + tables + chart captions + equations |
| Ingestion cost | Fast (split + embed) | Higher (LLM entity/relation extraction per chunk) |
| Query latency | ~0.5 s | 2–8 s (graph traversal) |
| Best for | Single-section factual lookup | Cross-section comparative analysis |

The two pipelines coexist and serve different intent types. The `tenk_agent` is unchanged.

---

## Knowledge Graph Architecture

LightRAG builds a property graph from the ingested documents. Each content element becomes one or more nodes; LightRAG's entity extraction LLM identifies entities and relationships between them.

```
PDF document (10-Q / 10-K)
        │
        ▼  RAG-Anything (MinerU)
┌───────────────────────────────────────┐
│  Document parser output               │
│                                       │
│  ┌─────────────┐  ┌────────────────┐  │
│  │ Text chunks │  │ Table rows     │  │
│  │ (prose)     │  │ (structured    │  │
│  └──────┬──────┘  │  markdown)     │  │
│         │         └───────┬────────┘  │
│  ┌──────▼──────┐  ┌───────▼────────┐  │
│  │ Equations   │  │ Chart/Image    │  │
│  │ (LaTeX)     │  │ captions       │  │
│  └─────────────┘  │ (vision LLM)   │  │
│                   └────────────────┘  │
└───────────────────────────────────────┘
        │  all content types → text representation
        ▼
LightRAG entity extraction (Gemini)
        │
        ├─ Entities: Company, Executive, Metric, Risk, Product, Quarter
        ├─ Relationships: reported_in, mentions, derived_from, contradicts
        └─ Stores:
             ┌──────────────────┐  ┌─────────────────────┐
             │  NetworkX graph  │  │  nano-vectordb       │
             │  (entities +     │  │  (chunk embeddings   │
             │   relations)     │  │   for hybrid search) │
             └──────────────────┘  └─────────────────────┘
                       lightrag_storage/
```

### Content types captured per filing

| Content type | Parser | Stored as | Example node |
|---|---|---|---|
| Prose paragraphs | MinerU text extractor | LightRAG text chunk | MD&A section, Risk Factors paragraph |
| Tables | MinerU table extractor | Structured markdown → LightRAG chunk | Revenue table: Q3 $12.4B, +18% YoY |
| Charts & figures | MinerU image extractor → vision LLM caption | Caption text → LightRAG chunk | "Bar chart: cloud revenue $8.2B in Q3, up from $6.9B Q2" |
| Equations | MinerU equation parser | LaTeX + plain text → LightRAG chunk | Operating margin = Operating income / Revenue |

---

## Retrieval Modes

LightRAG supports five query modes. The agent selects the mode based on question type:

| Mode | Graph strategy | Best for | Typical latency |
|---|---|---|---|
| `local` | Entity-centric neighbourhood traversal | Questions about one specific company, executive, or metric | 2–4 s |
| `global` | Community-level summary across the whole graph | Sector-wide patterns, cross-company themes | 3–6 s |
| `hybrid` | Local + global combined | Cross-section comparison within one or more reports **(default)** | 4–8 s |
| `naive` | Vector similarity only (no graph) | Simple keyword retrieval, speed critical | 0.5–2 s |
| `mix` | Full graph traversal + vector re-rank | Most thorough analysis | 6–15 s |

---

## Tools

### `list_indexed_reports() -> dict`

Reads the manifest file (`lightrag_storage/ingested_reports.jsonl`) and returns metadata for every ingested document. Always called first to confirm the relevant reports are available.

```
Output:
{
  "status": "success",
  "count": 3,
  "reports": [
    { "file": "MSFT_10Q_Q3_2025.pdf", "ticker": "MSFT",
      "report_type": "10-Q", "filing_period": "Q3 2025",
      "ingested_at": "2026-05-03T09:12:00+00:00" },
    { "file": "MSFT_10Q_Q2_2025.pdf", "ticker": "MSFT",
      "report_type": "10-Q", "filing_period": "Q2 2025",
      "ingested_at": "2026-05-03T09:08:00+00:00" },
    { "file": "AAPL_10K_FY2025.pdf",  "ticker": "AAPL",
      "report_type": "10-K", "filing_period": "FY2025",
      "ingested_at": "2026-05-03T09:30:00+00:00" }
  ]
}
```

### `query_investment_research(query: str, mode: str = "hybrid") -> dict`

Queries the LightRAG knowledge graph using the specified mode. The graph was built from all ingested reports and spans all content types (text, tables, chart captions).

```
Input:
{
  "query": "Compare MSFT's revenue growth table in Q3 with the executive summary
            and highlight any risks mentioned in charts",
  "mode":  "hybrid"
}

Output:
{
  "status": "success",
  "mode":   "hybrid",
  "mode_description": "local + global — best for comparative cross-section analysis",
  "answer": "In Q3 2025, Microsoft's revenue table showed total revenue of $65.6B
             (+16% YoY), with Intelligent Cloud at $28.9B (+22%). The executive
             summary attributed growth to Azure AI services adoption. A bar chart
             on page 8 captioned 'Azure revenue Q1–Q3 FY2025' shows a sequential
             deceleration in Q2 (19% → 18% growth) that the text does not explicitly
             discuss. The chart also annotates: 'FX headwind ~1pp'. Risk disclosures
             in the same filing cite 'intensifying competition from AWS and GCP' and
             'macroeconomic pressure on enterprise IT spend'."
}
```

### `ingest_report_pdf(file_path, ticker, report_type, filing_period) -> dict`

On-demand ingestion of a single PDF. Runs RAG-Anything's full multimodal pipeline: MinerU parses the PDF, the vision LLM captions charts and images, and LightRAG builds graph nodes for all content. Records the file in the manifest.

```
Input:
{
  "file_path":     "/reports/MSFT_10Q_Q3_2025.pdf",
  "ticker":        "MSFT",
  "report_type":   "10-Q",
  "filing_period": "Q3 2025"
}

Output (success):
{
  "status":        "success",
  "file":          "MSFT_10Q_Q3_2025.pdf",
  "ticker":        "MSFT",
  "report_type":   "10-Q",
  "filing_period": "Q3 2025",
  "output_dir":    "/reports/MSFT_10Q_Q3_2025_parsed"
}
```

Ingestion is slow (1–10 minutes per 100-page PDF) because LightRAG makes an LLM call for every chunk to extract entities and relationships. Prefer the batch CLI script (`ingestion/ingest_reports.py`) for pre-ingesting reports before a session.

---

## Ingestion Pipeline

```
PDF file  (10-Q / 10-K)
    │
    ▼  MinerU (RAG-Anything)
    │
    ├─ text blocks  ──────────────────────────────────────────┐
    ├─ table blocks → structured markdown                     │
    ├─ image blocks → Gemini vision LLM → caption text        │ all as text
    └─ equation blocks → LaTeX + plain description            │
                                                              ▼
                                                   LightRAG ainsert()
                                                        │
                                                        ├─ chunk text
                                                        ├─ Gemini: extract entities
                                                        │   [Company, Executive, Metric, Risk...]
                                                        ├─ Gemini: extract relationships
                                                        │   [reported_in, mentions, derived_from...]
                                                        └─ Write to:
                                                             graph_chunk_entity_relation.graphml
                                                             vdb_entities.json
                                                             vdb_relationships.json
                                                             vdb_chunks.json
                                                             kv_store_*.json
```

### Batch ingestion CLI

```bash
# Single file
python ingestion/ingest_reports.py reports/MSFT_10Q_Q3_2025.pdf \
    --ticker MSFT --type 10-Q --period "Q3 2025"

# Directory of PDFs (same ticker/type/period)
python ingestion/ingest_reports.py reports/MSFT/ \
    --ticker MSFT --type 10-Q --period "Q3 2025"

# Multiple tickers from CSV manifest
python ingestion/ingest_reports.py --manifest reports/manifest.csv

# List what is indexed
python ingestion/ingest_reports.py --list

# Re-ingest an already-indexed file
python ingestion/ingest_reports.py reports/MSFT_10Q_Q3_2025.pdf \
    --ticker MSFT --type 10-Q --period "Q3 2025" --force
```

Manifest CSV format:
```
file_path,ticker,report_type,filing_period
reports/MSFT_Q3_2025.pdf,MSFT,10-Q,Q3 2025
reports/AAPL_FY2025.pdf,AAPL,10-K,FY2025
reports/NVDA_Q3_2025.pdf,NVDA,10-Q,Q3 2025
```

---

## Agent Workflow

```
investment_research_agent
    │
    ├─ Step 1: list_indexed_reports()
    │     If count = 0 → tell user, explain ingestion, stop.
    │     If relevant ticker/period missing → offer ingest_report_pdf.
    │
    ├─ Step 2: Select retrieval mode
    │     "Compare table with summary and chart"  → hybrid
    │     "What did the CFO say about risk?"      → local
    │     "Which companies mention AI in Q3?"     → global
    │
    ├─ Step 3: query_investment_research(query, mode)
    │     For multi-part questions: one focused sub-query per part
    │     Maximum 3 calls (token budget constraint)
    │
    └─ Step 4: Synthesise and present
          Lead with direct answer
          Quote table values, chart captions, prose excerpts
          Label each evidence piece: (table) / (chart) / (prose)
          Never fabricate. Never give investment advice.
```

---

## Message Flow — Cross-Section Analysis

**Query:** "Compare MSFT's revenue growth table in Q3 2025 with the executive summary, and highlight any risks mentioned in the accompanying charts."

```
stock_orchestrator
    ├─► intent_agent → {
    │     "intent": "INVESTMENT_RESEARCH",
    │     "companies": ["MSFT"],
    │     "time_horizon": "Q3 2025"
    │   }
    │
    └─► investment_research_agent
          │
          ├─► list_indexed_reports()
          │     → count: 2, reports: [MSFT 10-Q Q3 2025, MSFT 10-Q Q2 2025]
          │     Confirms MSFT Q3 2025 is indexed ✓
          │
          ├─► query_investment_research(
          │     "Compare the revenue growth table in MSFT Q3 2025 with the
          │      executive summary and highlight risks mentioned in charts",
          │     mode="hybrid"
          │   )
          │
          │   LightRAG hybrid traversal:
          │   ┌─ local graph: entity "MSFT" → adjacent nodes →
          │   │    [Revenue Table Q3: $65.6B +16% YoY]
          │   │    [Intelligent Cloud: $28.9B +22%]
          │   │    [Executive Summary: "Azure AI services adoption"]
          │   │    [Chart caption: "Azure revenue Q1–Q3, FX headwind ~1pp"]
          │   │    [Risk Factors: "competition from AWS/GCP"]
          │   └─ global graph: community "MSFT filings" → cross-quarter theme
          │        [Q2→Q3 growth deceleration noted in chart not discussed in prose]
          │
          │   → answer with cross-section evidence
          │
          └─► LLM synthesises:
                ## Revenue Table vs Executive Summary

                **Table (Q3 2025):**
                | Segment | Revenue | YoY Change |
                |---|---|---|
                | Total | $65.6B | +16% |
                | Intelligent Cloud | $28.9B | +22% |
                | Productivity & Business | $19.8B | +13% |
                | More Personal Computing | $16.9B | +11% |

                **Executive Summary:**
                Management attributed the +22% Intelligent Cloud growth to
                "strong Azure AI services adoption and increased enterprise
                commitments" (page 3).

                ## Risks from Charts

                A bar chart on page 8 ("Azure revenue Q1–Q3 FY2025") shows
                sequential deceleration: Q1 +21% → Q2 +19% → Q3 +18%.
                The chart annotates "FX headwind ~1pp" — a risk not called
                out explicitly in the executive summary prose.

                The accompanying Risk Factors section states: "We face
                intensifying competition from Amazon Web Services and Google
                Cloud Platform, and macroeconomic pressure may reduce enterprise
                IT spend" — consistent with the decelerating chart trend.

                *Not investment advice.*
```

---

## Message Flow — Multi-Quarter Period Comparison

**Query:** "How did MSFT's operating margin evolve from Q2 to Q3 2025, and what explanation does management give?"

```
investment_research_agent
    │
    ├─► list_indexed_reports()
    │     → [MSFT Q3 2025, MSFT Q2 2025] ✓
    │
    ├─► query_investment_research(
    │     "MSFT operating margin Q2 2025 table and management explanation",
    │     mode="local"
    │   )
    │   → Q2: operating margin 44.6%, CFO commentary: "Copilot integration costs"
    │
    ├─► query_investment_research(
    │     "MSFT operating margin Q3 2025 table and management explanation",
    │     mode="local"
    │   )
    │   → Q3: operating margin 45.9%, CFO commentary: "leverage from AI workload pricing"
    │
    └─► LLM synthesises:
          Q2 2025: 44.6% — CFO noted elevated Copilot integration costs
          Q3 2025: 45.9% (+130 bps) — management attributed improvement to
                   "better pricing leverage on AI inference workloads"
          The graph links both quarters' table rows to the same "Operating Margin"
          entity, making the trend directly traceable across filings.
```

---

## Message Flow — On-Demand Ingestion

**Query:** "Analyse Apple's FY2025 10-K. Here is the file: /reports/AAPL_10K_FY2025.pdf"

```
investment_research_agent
    │
    ├─► list_indexed_reports()
    │     → count: 2 (MSFT only) — AAPL not indexed
    │
    ├─► ingest_report_pdf(
    │     file_path="/reports/AAPL_10K_FY2025.pdf",
    │     ticker="AAPL",
    │     report_type="10-K",
    │     filing_period="FY2025"
    │   )
    │
    │   RAG-Anything pipeline (1–10 min):
    │   ┌─ MinerU parses PDF → text, tables, charts, equations
    │   ├─ Vision LLM captions each chart image
    │   ├─ LightRAG ainsert() → entity extraction per chunk (LLM)
    │   └─ Graph written to lightrag_storage/
    │
    │   → { status: "success", file: "AAPL_10K_FY2025.pdf" }
    │   Tells user: ingestion complete (~3 min for 180-page PDF)
    │
    └─► query_investment_research(
          "AAPL FY2025 10-K key themes: revenue, risk, charts",
          mode="hybrid"
        )
```

---

## Separation from `tenk_agent`

Both agents ingest 10-K/10-Q content but serve distinct use cases and must not be confused:

```
User asks: "What are SNOW's risk factors?"
    → ANNUAL_REPORT intent → tenk_agent → ChromaDB vector search
    → Fast single-section answer with filing citations

User asks: "Compare the risk table in SNOW's Q3 report with what the CEO
            said in the earnings call transcript and the revenue chart"
    → INVESTMENT_RESEARCH intent → investment_research_agent → LightRAG
    → Cross-section, multi-hop answer linking table + prose + chart nodes

Two separate stores — no shared index, no shared state:
    ChromaDB     → data/chroma/          (tenk_agent)
    LightRAG     → lightrag_storage/     (investment_research_agent)
```

---

## Dependencies

| Package | Version | Role |
|---|---|---|
| `lightrag-hku` | ≥ 1.3.0 | Knowledge graph storage, entity extraction, query engine |
| `raganything` | ≥ 0.1.0 | Multimodal PDF parsing orchestration |
| `mineru` | (pulled by raganything) | PDF layout analysis, table/image/equation extraction |
| `google-genai` | ≥ 1.0.0 (already installed) | LLM for entity extraction and vision captioning |

MinerU downloads its model weights on the first `process_document_complete` call (~2 GB, cached in `~/.cache/mineru/`). Subsequent calls use the cache.

---

## Gemini Model Assignments

| Task | Model | Rationale |
|---|---|---|
| Entity/relationship extraction (LightRAG) | `gemini-2.5-flash` | High-volume (one call per chunk during ingestion); same model as agent tier |
| Chart/image captioning (RAG-Anything) | `gemini-2.5-flash` | Vision multimodal; unified with entity extraction model |
| Answer synthesis (ADK agent) | `MODEL_VERSION` (`gemini-2.5-flash`) | Best reasoning quality for final cross-section synthesis |
| Embeddings | `text-embedding-004` | 768-dim, async-wrapped via `asyncio.to_thread` |

---

## Known Limitations

| Limitation | Impact | Mitigation |
|---|---|---|
| Ingestion is LLM-intensive | 1–10 min per report; API cost proportional to PDF length | Batch ingest offline via CLI before user sessions |
| MinerU requires model download (~2 GB) | First-time setup overhead | Download on server startup; cached thereafter |
| Graph is append-only | Re-ingesting same file adds duplicate nodes | Use `--force` flag only when content has changed |
| No per-ticker workspace isolation | All companies share one LightRAG graph | Use `workspace` parameter in future for multi-tenant isolation |
| Query latency 2–15 s | Noticeable in interactive sessions | Show a "Searching knowledge graph…" status; `naive` mode for speed |

---

## See Also

| Document | Topic |
|---|---|
| [`arch/07-rag.md`](../07-rag.md) | ChromaDB RAG setup used by `tenk_agent` |
| [`arch/agents/tenk-agent.md`](tenk-agent.md) | ChromaDB-backed general 10-K Q&A agent |
| [`stock_agent/lightrag_config.py`](../../stock_agent/lightrag_config.py) | LightRAG + RAGAnything singleton setup |
| [`stock_agent/investment_research_tools.py`](../../stock_agent/investment_research_tools.py) | Tool implementations |
| [`ingestion/ingest_reports.py`](../../ingestion/ingest_reports.py) | Batch ingestion CLI |
| [`skills/investment-research/SKILL.md`](../../skills/investment-research/SKILL.md) | Agent system prompt and mode-selection rules |
