"""The deterministic routing spine — the core engineering claim of the project.

These assertions guarantee the routing table stays internally consistent and in
sync with the eval suite, all without a single model call.
"""
from stock_agent.agent import _ROUTE_MAP, SPECIALISTS, _parse_decision
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
    for yes in ["yes", "Yes!", "y", "yeah", "confirm", "ok", "sure", "go ahead", "do it", "yes please"]:
        assert _parse_decision(yes) == "approve", yes
    for no in ["no", "cancel", "stop", "abort", "no thanks", "don't do it"]:
        assert _parse_decision(no) == "decline", no


def test_decision_parser_rejects_normal_queries():
    # Regression: these used to count as an approval because they contain
    # "buy"/"ok", which could execute a different pending trade.
    for q in [
        "should I buy NVDA?",
        "is AMD a buy?",
        "ok what is MSFT at",
        "sell",
        "what is the price of AAPL",
        "show me a chart of tesla and forecast it for two weeks",
        "yes no",
        "",
    ]:
        assert _parse_decision(q) is None, q


def test_no_llm_agent_can_execute_trades():
    # Human approval is enforced in code: execution happens only in the
    # orchestrator, so no model-facing toolset may include an execute tool.
    for agent in SPECIALISTS.values():
        names = {getattr(t, "__name__", getattr(t, "name", "")) for t in agent.tools}
        assert not names & {"execute_pending_trade", "execute_trade_now"}, agent.name
