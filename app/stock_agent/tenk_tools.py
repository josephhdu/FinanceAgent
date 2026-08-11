"""RAG tools over SEC 10-K filings — direct Python (not MCP).

Why direct Python and not an MCP subprocess: the sentence-transformer embedding
model takes 3–8s to load, which exceeds ADK's ~5s MCP subprocess startup timeout.
So we load it in a background daemon thread at import time; by the time the first
`search_10k` call arrives the model is usually ready, and if not, the call blocks
briefly on `_init_done.wait()`.

Index: a ChromaDB PersistentClient collection `sec_10k` at data/10k_chroma,
cosine distance, all-MiniLM-L6-v2 (384-dim). Populated offline by
scripts/download_10ks.py.
"""
from __future__ import annotations

import os
import threading

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "10k_chroma")
COLLECTION_NAME = "sec_10k"
EMBED_MODEL = "all-MiniLM-L6-v2"
MIN_RELEVANCE = 0.40  # per docs/accuracy.md — below this, passages are dropped

_init_done = threading.Event()
_collection = None


def _init_rag() -> None:
    global _collection
    try:
        import chromadb
        from chromadb.utils import embedding_functions

        client = chromadb.PersistentClient(path=_DATA_DIR)
        embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL)
        _collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=embed_fn,
            metadata={"hnsw:space": "cosine"},
        )
    except Exception as exc:  # noqa: BLE001 - surface at call time instead
        print(f"[tenk_tools] RAG init failed: {exc}")
    finally:
        _init_done.set()


# Warm the embedding model up in the background during startup.
threading.Thread(target=_init_rag, daemon=True).start()


def get_collection():
    """Block until the background init finishes, then return the collection."""
    _init_done.wait()
    return _collection


def search_10k(ticker: str, query: str, n_results: int = 3) -> dict:
    """Search a company's 10-K filing for passages relevant to a query.

    Args:
        ticker: canonical stock ticker (e.g. "SNOW").
        query: what to look for (e.g. "risk factors regulatory competition").
        n_results: how many passages to return (clamped to 1–20).

    Returns a dict with a ``results`` list of {chunk_index, form, section,
    relevance, text}. Passages below the relevance floor are dropped.
    """
    coll = get_collection()
    if coll is None:
        return {"status": "error", "message": "10-K index is unavailable"}
    n = max(1, min(int(n_results), 20))
    try:
        res = coll.query(
            query_texts=[query],
            n_results=n,
            where={"ticker": ticker.upper()},
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": f"search failed: {exc}"}

    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    out = []
    for doc, meta, dist in zip(docs, metas, dists):
        relevance = round(1 - dist, 3)
        if relevance < MIN_RELEVANCE:
            continue
        out.append(
            {
                "chunk_index": meta.get("chunk_index"),
                "form": meta.get("form", "10-K"),
                "section": meta.get("section", "10-K"),
                "relevance": relevance,
                "text": (doc or "")[:1200],
            }
        )
    result = {"status": "success", "ticker": ticker.upper(), "results": out}
    if not out:
        result["note"] = "No sufficiently relevant passages found (company may not be indexed)."
    return result


def rag_ready() -> bool:
    """True once the embedding model + Chroma collection have warmed up."""
    return _init_done.is_set()


def list_indexed_companies() -> dict:
    """List which companies have 10-K filings indexed, with chunk counts."""
    coll = get_collection()
    if coll is None:
        return {"status": "error", "message": "10-K index is unavailable"}
    try:
        got = coll.get(include=["metadatas"])
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": f"listing failed: {exc}"}
    counts: dict[str, int] = {}
    for meta in got.get("metadatas") or []:
        t = meta.get("ticker")
        if t:
            counts[t] = counts.get(t, 0) + 1
    companies = [{"ticker": t, "chunks": c} for t, c in sorted(counts.items())]
    return {"status": "success", "indexed_companies": companies}
