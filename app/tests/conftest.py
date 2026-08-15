"""Shared test configuration.

Disabling the RAG warm-up BEFORE any ``stock_agent`` module is imported keeps the
suite fast and dependency-light: importing the agent graph never spins up the
background thread that would pull in chromadb / sentence-transformers (torch) or
download the embedding model. pytest loads this conftest before the test modules,
so the flag is set in time.
"""
import os

os.environ.setdefault("FINANCEAI_DISABLE_WARMUP", "1")
