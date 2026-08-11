"""Scoring + gating helpers for the eval harness."""
from __future__ import annotations

import os

import yaml


def accuracy(results: list[tuple[str, str, str]]) -> float:
    """Fraction of (case, expected, got) rows where expected == got."""
    if not results:
        return 0.0
    correct = sum(1 for _case, exp, got in results if exp == got)
    return correct / len(results)


def load_thresholds(path: str | None = None) -> dict:
    path = path or os.path.join(os.path.dirname(__file__), "thresholds.yaml")
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def gate(scores: dict[str, float], thresholds: dict[str, float]) -> list[tuple[str, float, float]]:
    """Return the list of (metric, score, threshold) that fell below threshold.

    An empty list means every gated metric passed.
    """
    failures = []
    for metric, floor in thresholds.items():
        score = scores.get(metric)
        if score is None:
            continue
        if score < floor:
            failures.append((metric, score, floor))
    return failures
