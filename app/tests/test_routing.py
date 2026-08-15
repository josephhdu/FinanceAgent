"""The deterministic routing spine — the core engineering claim of the project.

These assertions guarantee the routing table stays internally consistent and in
sync with the eval suite, all without a single model call.
"""
from stock_agent.agent import _ROUTE_MAP, SPECIALISTS, _looks_like_decision
from eval.cases import INTENT_CASES, ROUTE_CASES


def test_every_route_target_is_a_registered_specialist():
    for intent, pipeline in _ROUTE_MAP.items():
        for name in pipeline:
            assert name in SPECIALISTS, f"{intent} routes to unknown specialist '{name}'"


def test_route_map_mirrors_eval_cases():
    # The eval harness scores routing against ROUTE_CASES; it must equal the live
    # table, so a drifting edit to either side is caught here for free.
    assert _ROUTE_MAP == ROUTE_CASES


def test_every_non_unknown_intent_has_a_route():
    intents = {intent for _, intent in INTENT_CASES if intent != "UNKNOWN"}
    for intent in intents:
        assert intent in _ROUTE_MAP, f"intent '{intent}' is classified but not routed"


def test_decision_parser_accepts_approvals_and_rejections():
    for yes in ["yes", "y", "yeah", "confirm", "ok", "sure", "go ahead", "do it"]:
        assert _looks_like_decision(yes), yes
    for no in ["no", "cancel", "stop", "abort"]:
        assert _looks_like_decision(no), no


def test_decision_parser_rejects_normal_queries():
    for q in [
        "what is the price of AAPL",
        "show me a chart of tesla and forecast it for two weeks",
        "should i be worried about nvda earnings",
    ]:
        assert not _looks_like_decision(q), q
