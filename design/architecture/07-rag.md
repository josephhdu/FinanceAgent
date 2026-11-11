# RAG — 10-K Filing Retrieval

## Overview

The RAG (Retrieval-Augmented Generation) system enables the `tenk_agent` and `comparison_insights_agent` to answer questions about SEC 10-K annual filings. Filings are chunked, embedded with a sentence transformer, and stored in ChromaDB. At query time, semantic similarity search retrieves the most relevant passages, which are fed to the LLM for synthesis.

---

## Architecture

```
                  Offline (data ingestion)
                  ────────────────────────
                  scripts/download_10ks.py
                       │
                       ├─ Download 10-K/20-F filings (SEC EDGAR)
                       ├─ Parse text (strip HTML/XBRL boilerplate)
                       ├─ Chunk into passages (~500 tokens each)
                       └─ Embed + upsert into ChromaDB
                              │
                              ▼
                       /data/10k_chroma/   (persistent ChromaDB)
                       Collection: "sec_10k"


                  Online (query time)
                  ───────────────────
tenk_agent / comparison_insights_agent
    │
    ├─ list_indexed_companies()
    │    ChromaDB metadata query → list of tickers with chunk counts
    │
    └─ search_10k(ticker, query, n_results=3)
         │
         ├─ Embed query: all-MiniLM-L6-v2
         ├─ ChromaDB cosine similarity search
         │    Filter: where(ticker=ticker)
         ├─ Return top-N passages with relevance scores
         └─ LLM synthesises answer with citations
```

---

## ChromaDB Configuration

| Parameter        | Value                                          |
|------------------|------------------------------------------------|
| Collection name  | `sec_10k`                                      |
| Embedding model  | `all-MiniLM-L6-v2` (SentenceTransformer)       |
| Storage path     | `/data/10k_chroma` (persistent client)         |
| Distance metric  | Cosine (ChromaDB default)                      |
| Relevance score  | `1 - cosine_distance` (0–1 scale)              |

---

## Data Ingestion

`scripts/download_10ks.py` handles offline data preparation:

1. **Download**: Fetches 10-K filings from SEC EDGAR for indexed companies (by CIK or ticker lookup)
2. **Parse**: Strips HTML tags, XBRL metadata, and boilerplate legal language
3. **Chunk**: Splits parsed text into passages (~500 tokens, with sentence-boundary awareness)
4. **Metadata**: Each chunk tagged with `ticker`, `form` (10-K or 20-F), `chunk_index`, `section` (Risk Factors, MD&A, Business, etc.)
5. **Embed + upsert**: Uses `SentenceTransformerEmbeddingFunction` to embed each chunk and store in ChromaDB

---

## tenk_tools.py — Core Functions

### Initialisation

The embedding model is loaded in a **daemon thread** at module import time, before any agent requests arrive:

```python
_init_done = threading.Event()

def _init_rag():
    global _collection
    client = chromadb.PersistentClient(path="/data/10k_chroma")
    embed_fn = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
    _collection = client.get_collection("sec_10k", embedding_function=embed_fn)
    _init_done.set()

threading.Thread(target=_init_rag, daemon=True).start()
```

The first call to `search_10k` blocks until `_init_done` is set (typically 3–8 seconds). Subsequent calls are instant.

### `list_indexed_companies()`

```python
def list_indexed_companies() -> dict:
    _init_done.wait()
    metadata = _collection.get(include=["metadatas"])["metadatas"]
    # Count chunks per ticker
    ticker_counts = {}
    for m in metadata:
        t = m.get("ticker", "UNKNOWN")
        ticker_counts[t] = ticker_counts.get(t, 0) + 1
    return {
        "indexed_companies": [
            {"ticker": t, "chunks": n} for t, n in sorted(ticker_counts.items())
        ]
    }
```

### `search_10k(ticker, query, n_results=3)`

```python
def search_10k(ticker: str, query: str, n_results: int = 3) -> dict:
    _init_done.wait()
    n_results = max(1, min(n_results, 20))   # clamp to 1–20

    results = _collection.query(
        query_texts=[query],
        n_results=n_results,
        where={"ticker": ticker},             # filter by company
        include=["documents", "metadatas", "distances"],
    )

    passages = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        passages.append({
            "chunk_index": meta.get("chunk_index"),
            "form":        meta.get("form", "10-K"),
            "relevance":   round(1 - dist, 3),
            "text":        doc,
        })

    return {"status": "success", "ticker": ticker, "results": passages}
```

---

## Passage Schema

```json
{
  "chunk_index": 47,
  "form": "10-K",
  "relevance": 0.847,
  "text": "Snowflake's product revenue grew 38% year-over-year to $3.2 billion,
           driven by increased consumption by existing customers and new customer
           additions across enterprise verticals..."
}
```

---

## Message Flow: RAG Query

**Query**: "What does Snowflake say about their competitive moat in the annual report?"

```
tenk_agent
    │
    ├─ list_indexed_companies()
    │     _init_done.wait() — model already warm
    │     ChromaDB metadata scan
    │     → confirms SNOW is indexed (142 chunks)
    │
    ├─ resolve_ticker("Snowflake") → "SNOW"
    │
    ├─ search_10k("SNOW", "competitive moat advantages differentiation", n_results=3)
    │
    │     Embed query: all-MiniLM-L6-v2
    │       "competitive moat advantages differentiation"
    │       → 384-dimensional embedding vector
    │
    │     ChromaDB cosine similarity search:
    │       where={ticker: "SNOW"}
    │       → top 8 passages ranked by relevance
    │
    │     Returns:
    │       [
    │         { chunk_index: 31, form: "10-K", relevance: 0.889,
    │           text: "Our Data Cloud platform creates powerful network effects..."},
    │         { chunk_index: 47, form: "10-K", relevance: 0.863,
    │           text: "Snowflake's differentiation lies in its multi-cloud
    │                  architecture and seamless data sharing capabilities..."},
    │         ...
    │       ]
    │
    └─ LLM synthesises:
         "According to Snowflake's 10-K annual report, their competitive
          advantages include:

          **Network Effects** (Business section):
          'Our Data Cloud platform creates powerful network effects as more
          customers join and contribute data products...'

          **Multi-Cloud Architecture** (Business section):
          'Snowflake's differentiation lies in its multi-cloud architecture
          allowing customers to run on AWS, Azure, and GCP simultaneously...'

          Source: Snowflake Inc. Form 10-K, FY2025.
          This is informational and not investment advice."
```

---

## Why Direct Python (Not MCP)

The `rag_mcp_server.py` exists but is not used in production agents:

```
Problem: all-MiniLM-L6-v2 load time = 3–8 seconds
ADK MCP subprocess timeout = ~5 seconds
Result: first tool call fails before model is ready

Solution: direct Python import + daemon thread pre-warm
  → model loads in background during ADK startup
  → first search_10k call blocks ≤1 second (usually already done)
  → all subsequent calls instant
```

---

## Indexed Companies

The collection currently includes 10-K (and 20-F for international filers) for:

```
MSFT  GOOGL  AAPL  NVDA  META  CRM  ADBE  NOW  SNOW  CRWD  SAP  ...
```

To add a new company, run:
```bash
python scripts/download_10ks.py --ticker NEW_TICKER
```
