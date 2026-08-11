"""FinanceAI evaluation harness.

Runs two suites and prints a scorecard:

  * intent classification accuracy (real ``classify_intent`` model calls)
  * routing-table correctness (deterministic, no model)

Usage:
    python eval/run_eval.py                 # scorecard only
    python eval/run_eval.py --gate          # exit non-zero if below thresholds
    python eval/run_eval.py --gate --seed-regression   # demo: force a failure
    python eval/run_eval.py --limit 6       # run only the first 6 intent cases

The ``--gate`` form is what CI would run to block a regression.
"""
from __future__ import annotations

import argparse
import os
import sys

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(_APP_DIR, ".env"))

from eval import metrics as M  # noqa: E402
from eval.cases import INTENT_CASES, ROUTE_CASES  # noqa: E402

GREEN, RED, DIM, BOLD, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


def _mark(ok: bool) -> str:
    return f"{GREEN}✓{RESET}" if ok else f"{RED}✗{RESET}"


def run_route_suite() -> tuple[float, list[tuple[str, str, str]]]:
    """Deterministically check agent._ROUTE_MAP against the expected pipelines."""
    from stock_agent.agent import _ROUTE_MAP

    results = []
    for intent, expected in ROUTE_CASES.items():
        got = _ROUTE_MAP.get(intent, [])
        results.append((intent, "→".join(expected), "→".join(got)))
    return M.accuracy(results), results


def run_intent_suite(limit: int | None) -> tuple[float, list[tuple[str, str, str]]]:
    """Classify each case with the real model and score against the expected intent."""
    from stock_agent.intent_agent import classify_intent

    cases = INTENT_CASES[:limit] if limit else INTENT_CASES
    results = []
    for question, expected in cases:
        try:
            got = classify_intent(question).get("intent", "UNKNOWN")
        except Exception as exc:  # noqa: BLE001 - a failed call is a failed case
            got = f"ERROR:{type(exc).__name__}"
        results.append((question, expected, got))
    return M.accuracy(results), results


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the FinanceAI eval suites.")
    ap.add_argument("--gate", action="store_true", help="exit non-zero if below thresholds")
    ap.add_argument("--limit", type=int, default=None, help="run only the first N intent cases")
    ap.add_argument("--seed-regression", action="store_true",
                    help="inject a guaranteed-wrong case to demonstrate the gate")
    args = ap.parse_args()

    print(f"\n{BOLD}FinanceAI — evaluation scorecard{RESET}")

    # --- routing (deterministic) ---
    route_acc, route_results = run_route_suite()
    print(f"\n{BOLD}Routing table{RESET} ({len(route_results)} intents)")
    for intent, exp, got in route_results:
        print(f"  {_mark(exp == got)} {intent:<20} {DIM}{got or '(none)'}{RESET}")

    # --- intent classification ---
    if args.seed_regression:
        # Simulate a regressed classifier (every other case wrong) so the gate
        # demonstrably fails — deterministic and with no model calls.
        print(f"\n{BOLD}Intent classification{RESET} {RED}[SIMULATED REGRESSION]{RESET}")
        cases = INTENT_CASES[: args.limit] if args.limit else INTENT_CASES
        intent_results = [
            (q, exp, exp if i % 2 == 0 else "UNKNOWN") for i, (q, exp) in enumerate(cases)
        ]
    else:
        print(f"\n{BOLD}Intent classification{RESET} (running model — this makes real calls)")
        _acc, intent_results = run_intent_suite(args.limit)
    intent_acc = M.accuracy(intent_results)

    for question, exp, got in intent_results:
        ok = exp == got
        extra = "" if ok else f"  {RED}expected {exp}, got {got}{RESET}"
        print(f"  {_mark(ok)} {question[:52]:<52}{extra}")

    # --- summary + gate ---
    scores = {"intent_accuracy": intent_acc, "route_accuracy": route_acc}
    thresholds = M.load_thresholds()
    print(f"\n{BOLD}Summary{RESET}")
    print(f"  intent_accuracy  {intent_acc:5.1%}   (threshold {thresholds.get('intent_accuracy', 0):.0%})")
    print(f"  route_accuracy   {route_acc:5.1%}   (threshold {thresholds.get('route_accuracy', 0):.0%})")

    failures = M.gate(scores, thresholds)
    if not args.gate:
        print(f"\n{DIM}(no --gate; not enforcing thresholds){RESET}\n")
        return 0
    if failures:
        print(f"\n{RED}{BOLD}GATE FAILED{RESET}")
        for metric, score, floor in failures:
            print(f"  {RED}✗ {metric}: {score:.1%} < {floor:.0%}{RESET}")
        print()
        return 1
    print(f"\n{GREEN}{BOLD}GATE PASSED{RESET}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
