# Evaluation Framework (Three-Level)

## Overview

The evaluation framework measures system quality at three levels of abstraction:
- **Level 1** — Model quality: per-tool-call correctness, LLM output quality
- **Level 2** — Product effectiveness: per-interaction success and user experience
- **Level 3** — Business value: cost efficiency and analyst productivity impact

Each level uses different data sources. RAGAS scores semantic quality; the in-process tracing module measures operational efficiency; the eval harness captures tool call correctness and latency.

---

## Architecture

```
eval/run_eval.py
    │
    ├─ evaluate_intent_cases()     ← 33 intent accuracy tests (fast, no LLM pipeline)
    │     run_intent_extraction()  ← direct Gemini call, bypass ADK
    │     Check: intent, companies, format, thresholds, chart_type
    │
    └─ evaluate_e2e_cases()        ← 17 E2E quality tests (full pipeline)
          │
          ├─ run_query(root_agent, question)   ← eval_harness.py (ADK Runner)
          │     Captures: response, tool_calls_made, contexts, invocation_id, latency_ms
          │     Role: all eval runs execute as "analyst" to reach all pipeline intents
          │
          ├─ Keyword checks         ← expected_keywords ⊆ response
          ├─ Tool call checks        ← expected_tool_calls ⊆ tool_calls_made
          │
          ├─ RAGAS batch evaluation  ← Gemini 2.0-flash + embedding-001
          │     Metrics: AnswerRelevancy, Faithfulness, FactualCorrectness
          │
          └─ fetch_trace_metrics(invocation_id)   ← reads tracing._metrics
                Returns: tool_spans [{name, succeeded}], token_usage, cost_usd

          ↓
    compute_metrics(run_records, ragas_scores, trace_data, thresholds, baseline)
          ↓
    render_dashboard(l1, l2, l3)  →  ASCII box-drawing output
          ↓
    Save to eval/results/results_<timestamp>.{json,md}
```

---

## Level 1 — Model Quality

Measures how well the LLM selects and executes tools.

| Metric                  | Formula                                              | Source           | Threshold |
|-------------------------|------------------------------------------------------|------------------|-----------|
| Action Success Rate     | succeeded_spans / attempted_spans                    | tracing._metrics | ≥ 95%     |
| Tool Select Accuracy    | correct_tools_called / expected_tools                | eval harness     | ≥ 85%     |
| Hallucination Rate      | 1 − mean(faithfulness)                               | RAGAS            | ≤ 5%      |
| Context Utilization     | mean(answer_relevancy)                               | RAGAS            | ≥ 0.80    |
| Guardrail Violation Rate| false_positives / total (non-guardrail category)     | eval harness     | ≤ 2%      |

### Action Success Rate (ASR) — Definition

ASR is an **atomic, per-tool-call** metric, not a task-level metric. A "span" is one individual tool invocation:

```
• Tool call starts  → span recorded in tracing._metrics with succeeded=None
• Tool call returns → succeeded = True  (if result is not {"status":"error"})
                    → succeeded = False (if result is {"status":"error"} or None)

ASR = count(succeeded=True) / count(all spans excl. transfer_to_agent)
```

`transfer_to_agent` is excluded because it is internal ADK routing, not a data tool.

### Guardrail Violation Rate — Definition

A "violation" is a **false positive**: a legitimate query blocked by the guardrail system. Intentional guardrail test cases (category=`guardrail`) are excluded from this count to avoid double-counting expected behaviour.

---

## Level 2 — Product Metrics

Measures per-interaction effectiveness from the user's perspective.

| Metric               | Formula / Source                                              | Threshold |
|----------------------|---------------------------------------------------------------|-----------|
| Containment Rate     | contained / total                                             | ≥ 90%     |
| Task Complete Rate   | (keyword ∧ tool ∧ ragas_passed) / total                       | ≥ 80%     |
| User Confidence Score| mean(factual_correctness)                                     | ≥ 0.75    |
| Response Latency     | mean(latency_ms) — wall-clock time from query to final event  | ≤ 10 000 ms |
| Human Override Rate  | production data only — not computed in eval                   | —         |

### Containment — Definition

An interaction is **not contained** if any of the following patterns appear in the response (case-insensitive):

```
"our conversation has grown quite long"   ← token limit guardrail fired
"i'm not sure what you'd like to do"      ← routing failure / UNKNOWN intent
"i detected an attempt to override"       ← injection blocked
"outside my scope"                        ← scope rejection
```

Additionally: error in RunResult → not contained. Empty response → not contained.

### Task Complete — Definition

All three checks must pass:
1. All `expected_keywords` appear in the response
2. All `expected_tool_calls` were called during the run
3. RAGAS thresholds all passed (where defined)

---

## Level 3 — Business Metrics

| Metric              | Formula                                                              | Threshold |
|---------------------|----------------------------------------------------------------------|-----------|
| Cost per Task       | mean(cost_usd) for completed tasks only                              | ≤ $0.05   |
| Productivity Gains  | `max(baseline_min − actual_min, 0) × (hourly_rate / 60)`            | requires `--baseline-minutes` |
| Cost Savings %      | `(baseline_cost − agent_cost) / baseline_cost`                       | requires `--baseline-minutes` |

### Gemini 2.5-Flash Pricing

```
Input tokens:  $0.075 / 1M tokens
Output tokens: $0.300 / 1M tokens

cost_usd = (input_tokens × 0.075 + output_tokens × 0.300) / 1_000_000
```

Token counts are collected in-process via `tracing.on_llm_response()` which reads `usage_metadata` from every `LlmResponse`.

### Baseline Parameters

```bash
# Run with productivity/cost-savings enabled:
python -m eval.run_eval --category price --e2e-only \
    --baseline-minutes 15 \
    --analyst-hourly-rate 80
```

`--baseline-minutes 15` = analyst previously spent 15 minutes per price lookup task.

---

## Dashboard Output

```
╔══════════════════════════════════════════════════════════════╗
║  LEVEL 1 — MODEL QUALITY                                     ║
╠════════════════════════════╦═════════╦═════════╦═════════════╣
║  Metric                    ║  Score  ║ Target  ║             ║
╠════════════════════════════╬═════════╬═════════╬═════════════╣
║  Action Success Rate       ║  97.3%  ║  ≥95%   ║      ✓      ║
║  Tool Select Accuracy      ║  91.7%  ║  ≥85%   ║      ✓      ║
║  Hallucination Rate        ║   2.1%  ║   ≤5%   ║      ✓      ║
║  Context Utilization       ║  0.843  ║ ≥0.800  ║      ✓      ║
║  Guardrail Violation Rate  ║   0.0%  ║   ≤2%   ║      ✓      ║
╚════════════════════════════╩═════════╩═════════╩═════════════╝

╔══════════════════════════════════════════════════════════════╗
║  LEVEL 2 — PRODUCT METRICS                                   ║
╠════════════════════════════╦═════════╦═════════╦═════════════╣
║  Containment Rate          ║ 100.0%  ║  ≥90%   ║      ✓      ║
║  Task Complete Rate        ║  85.7%  ║  ≥80%   ║      ✓      ║
║  User Confidence Score     ║  0.812  ║ ≥0.750  ║      ✓      ║
║  Response Latency          ║ 8 240ms ║  ≤10s   ║      ✓      ║
║  Human Override Rate       ║   N/A   ║    —    ║      —      ║
╚════════════════════════════╩═════════╩═════════╩═════════════╝

╔══════════════════════════════════════════════════════════════╗
║  LEVEL 3 — BUSINESS METRICS                                  ║
╠════════════════════════════╦═════════╦═════════╦═════════════╣
║  Cost per Completed Task   ║ $0.0124 ║ ≤$0.05  ║      ✓      ║
║  Productivity Gains        ║ $19.67  ║    —    ║      —      ║
║  Cost Savings              ║  99.9%  ║    —    ║      —      ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Running the Eval

```bash
# Fast: intent accuracy only (no LLM pipeline, ~1 min)
python -m eval.run_eval --intent-only

# Full: all 17 E2E cases
python -m eval.run_eval --e2e-only

# Single category
python -m eval.run_eval --category price --e2e-only

# Single test case
python -m eval.run_eval --case e2e_price_msft

# With business metrics
python -m eval.run_eval --e2e-only --baseline-minutes 15 --analyst-hourly-rate 80

# Custom thresholds
python -m eval.run_eval --e2e-only --thresholds path/to/custom_thresholds.yaml
```

Results are saved to `eval/results/results_<timestamp>.{json,md}`.

---

## Regression Gate

Add `--gate` to any eval run to enforce thresholds and exit `1` on regression. Use this before saving prompt changes.

```bash
# Fast gate — intent only, no live agent calls (~60 seconds)
python eval/run_eval.py --intent-only --gate

# Full gate — all metrics including RAGAS and three-level
python eval/run_eval.py --gate

# Gate on a single category
python eval/run_eval.py --category annual --gate
```

The gate checks all metrics defined in `thresholds.yaml` (including `intent_accuracy`) and prints a clear pass/fail summary:

```
═══════════════════════════════════════════════════════
  EVAL GATE — FAILED
═══════════════════════════════════════════════════════
  Regressions:
  ✗  tool_select_accuracy           0.8000  ≥ 0.85
  Passing:
  ✓  intent_accuracy                0.8065  ≥ 0.80
  ...
  9 passed   1 failed
═══════════════════════════════════════════════════════
```

Exit code `0` = all thresholds met. Exit code `1` = regression detected.

---

## Threshold Configuration

`eval/thresholds.yaml` controls all pass/fail boundaries. `direction: min` means the metric must be ≥ threshold; `direction: max` means ≤ threshold.

```yaml
intent:
  intent_accuracy:          {threshold: 0.80,   direction: min}

level1:
  action_success_rate:      {threshold: 0.95,   direction: min}
  tool_select_accuracy:     {threshold: 0.85,   direction: min}
  hallucination_rate:       {threshold: 0.05,   direction: max}
  context_utilization:      {threshold: 0.80,   direction: min}
  guardrail_violation_rate: {threshold: 0.02,   direction: max}

level2:
  containment_rate:         {threshold: 0.90,   direction: min}
  task_complete_rate:       {threshold: 0.80,   direction: min}
  user_confidence_score:    {threshold: 0.75,   direction: min}
  response_latency_ms:      {threshold: 10000,  direction: max}
  human_override_rate:      null   # production data only

level3:
  cost_per_task_usd:        {threshold: 0.05,   direction: max}
  productivity_gains:       null   # requires --baseline-minutes
  cost_savings:             null   # requires --baseline-minutes
```
