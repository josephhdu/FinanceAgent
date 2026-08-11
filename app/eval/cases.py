"""Evaluation cases for the FinanceAI agent.

Two kinds:

* ``INTENT_CASES`` — natural-language question → expected intent. Scored by
  running the real ``classify_intent`` model call (measures classification
  accuracy, the metric that most affects routing correctness).

* ``ROUTE_CASES`` — intent → expected specialist pipeline. Scored deterministically
  against ``_ROUTE_MAP`` (no model), so a bad edit to the routing table is caught
  for free.

Keep these representative of real usage; they double as regression coverage.
"""
from __future__ import annotations

# (question, expected_intent)
INTENT_CASES: list[tuple[str, str]] = [
    # PRICE
    ("What's MSFT trading at?", "PRICE"),
    ("Apple market cap", "PRICE"),
    ("How much is NVDA right now?", "PRICE"),
    ("Give me Tesla's current stats", "PRICE"),
    # PREDICTION
    ("Where will NVDA be in two weeks?", "PREDICTION"),
    ("Forecast AAPL", "PREDICTION"),
    ("Predict Microsoft's price trend", "PREDICTION"),
    # VISUALIZATION
    ("Show me a chart of TSLA", "VISUALIZATION"),
    ("Plot AMD", "VISUALIZATION"),
    ("Graph Microsoft's price history", "VISUALIZATION"),
    # PRICE_PREDICTION
    ("What's MSFT at and where's it headed?", "PRICE_PREDICTION"),
    ("Give me Apple's price and a 2-week forecast", "PRICE_PREDICTION"),
    # PRICE_PREDICT_CHART
    ("MSFT price, 2-week forecast, with a chart", "PRICE_PREDICT_CHART"),
    ("Show NVDA's price, a forecast, and a chart", "PRICE_PREDICT_CHART"),
    # ANNUAL_REPORT
    ("What are Snowflake's risk factors?", "ANNUAL_REPORT"),
    ("Summarize NVDA's annual report risks", "ANNUAL_REPORT"),
    ("What does Microsoft's 10-K say about competition?", "ANNUAL_REPORT"),
    # TRADE_ANALYSIS
    ("Should I buy NVDA?", "TRADE_ANALYSIS"),
    ("Is MSFT a buy?", "TRADE_ANALYSIS"),
    ("Give me a trade signal for AMD", "TRADE_ANALYSIS"),
    ("Show my portfolio", "TRADE_ANALYSIS"),
    # UNKNOWN
    ("What's the weather today?", "UNKNOWN"),
    ("Tell me a joke", "UNKNOWN"),
]

# intent -> expected ordered specialist pipeline (mirrors agent._ROUTE_MAP).
ROUTE_CASES: dict[str, list[str]] = {
    "PRICE": ["price_agent"],
    "PREDICTION": ["prediction_agent"],
    "VISUALIZATION": ["visualization_agent"],
    "PRICE_PREDICTION": ["price_agent", "prediction_agent"],
    "PRICE_PREDICT_CHART": ["price_agent", "prediction_agent", "visualization_agent"],
    "ANNUAL_REPORT": ["tenk_agent"],
    "TRADE_ANALYSIS": ["trading_agent"],
}
