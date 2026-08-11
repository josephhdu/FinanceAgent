"""Download recent 10-K filings from SEC EDGAR and index them into ChromaDB.

One-time (offline) ingestion for the RAG pipeline. For each ticker it looks up
the CIK, finds the most recent 10-K, downloads the primary document, strips the
HTML to text, chunks it (~500 words), and upserts the chunks into the `sec_10k`
ChromaDB collection with metadata {ticker, form, chunk_index, section}.

SEC requires a descriptive User-Agent with contact info; set SEC_USER_AGENT in
your environment to override the default.

Usage:
  python scripts/download_10ks.py                      # default ticker set
  python scripts/download_10ks.py --tickers MSFT NVDA  # specific tickers
  python scripts/download_10ks.py --max-chunks 300
"""
from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
import time
import urllib.request

# macOS python.org interpreters ship without CA certs, so urllib HTTPS fails
# verification. Use certifi's bundle if available.
try:
    import certifi

    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:  # noqa: BLE001
    _SSL_CTX = ssl.create_default_context()

# Make `stock_agent` importable regardless of launch directory.
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from stock_agent.tenk_tools import COLLECTION_NAME, EMBED_MODEL  # noqa: E402

_DATA_DIR = os.path.join(_APP_DIR, "data", "10k_chroma")
_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"

DEFAULT_TICKERS = ["MSFT", "AAPL", "GOOGL", "NVDA", "SNOW", "CRM", "AMD", "ADBE"]
_UA = os.getenv("SEC_USER_AGENT", "FinanceAI research contact@example.com")


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept-Encoding": "gzip, deflate"})
    with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as resp:
        data = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            import gzip
            data = gzip.decompress(data)
    time.sleep(0.4)  # be polite to SEC (well under their 10 req/s limit)
    return data


def _ticker_to_cik() -> dict[str, int]:
    raw = json.loads(_get(_TICKER_MAP_URL))
    return {row["ticker"].upper(): int(row["cik_str"]) for row in raw.values()}


def _latest_10k(cik: int) -> tuple[str, str] | None:
    """Return (accession_no_nodashes, primary_document) for the most recent 10-K."""
    subs = json.loads(_get(_SUBMISSIONS_URL.format(cik=cik)))
    recent = subs["filings"]["recent"]
    for form, acc, doc in zip(recent["form"], recent["accessionNumber"], recent["primaryDocument"]):
        if form == "10-K":
            return acc.replace("-", ""), doc
    return None


def _html_to_text(html: bytes) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(" ")
    return re.sub(r"\s+", " ", text).strip()


def _chunk(text: str, words_per_chunk: int = 500) -> list[str]:
    words = text.split()
    return [" ".join(words[i : i + words_per_chunk]) for i in range(0, len(words), words_per_chunk)]


def _section_for(chunk: str) -> str:
    low = chunk.lower()
    if "risk factor" in low:
        return "Risk Factors"
    if "management's discussion" in low or "results of operations" in low:
        return "MD&A"
    if "quantitative and qualitative disclosures" in low:
        return "Market Risk"
    return "10-K Body"


def ingest(tickers: list[str], max_chunks: int) -> None:
    import chromadb
    from chromadb.utils import embedding_functions

    print("Loading embedding model (first run downloads ~90MB)…")
    embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL)
    client = chromadb.PersistentClient(path=_DATA_DIR)
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME, embedding_function=embed_fn, metadata={"hnsw:space": "cosine"}
    )

    print("Fetching SEC ticker→CIK map…")
    cik_map = _ticker_to_cik()

    for ticker in tickers:
        ticker = ticker.upper()
        cik = cik_map.get(ticker)
        if cik is None:
            print(f"  {ticker}: not found in SEC ticker map — skipping")
            continue
        found = _latest_10k(cik)
        if not found:
            print(f"  {ticker}: no 10-K found — skipping")
            continue
        acc, doc = found
        html = _get(_ARCHIVE_URL.format(cik=cik, acc=acc, doc=doc))
        text = _html_to_text(html)
        chunks = _chunk(text)[:max_chunks]
        if not chunks:
            print(f"  {ticker}: empty filing text — skipping")
            continue

        # Remove any prior chunks for this ticker, then add fresh ones (idempotent).
        try:
            collection.delete(where={"ticker": ticker})
        except Exception:  # noqa: BLE001
            pass
        collection.add(
            ids=[f"{ticker}-{i}" for i in range(len(chunks))],
            documents=chunks,
            metadatas=[
                {"ticker": ticker, "form": "10-K", "chunk_index": i, "section": _section_for(c)}
                for i, c in enumerate(chunks)
            ],
        )
        print(f"  {ticker}: indexed {len(chunks)} chunks (CIK {cik}, doc {doc})")

    total = collection.count()
    print(f"Done. Collection '{COLLECTION_NAME}' now holds {total} chunks at {_DATA_DIR}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest SEC 10-K filings into ChromaDB.")
    ap.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS, help="tickers to ingest")
    ap.add_argument("--max-chunks", type=int, default=400, help="max chunks per company")
    args = ap.parse_args()
    ingest(args.tickers, args.max_chunks)


if __name__ == "__main__":
    main()
