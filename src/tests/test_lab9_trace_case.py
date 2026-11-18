"""Regression test from docs/trace_case.md: seeded_regression C-013@11 (FM-05 pre_deducted).

The agent deducts the 35.000đ already refunded on O-505 itself (event 5 `proposal` 0) and denies
without calling the host. Ledger and status still match the label, so the outcome graders pass it;
only the step check QuoteKept sees the rewritten number. Runs the shape on a temp store (MockLLM).
"""
import pytest

pytestmark = pytest.mark.student


def _grade(shape: str, claim: str, seed: int):
    from pydantic_evals.evaluators import EvaluatorContext

    from lab9 import graders
    from lab9.trace_case import investigate

    case = investigate(shape, claim, seed)
    ctx = EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=case["label"],
                           output=case["trial"], duration=0.0, _span_tree=None, attributes={}, metrics={})
    return case["trial"], {name: g().evaluate(ctx).value for name, g in graders.GRADERS.items()}


def test_lab9_trace_case_c013_pre_deducted_is_caught():
    trial, got = _grade("seeded_regression", "C-013", 11)
    kinds = [e.get("kind") for e in trial["events"]]
    assert kinds[4] == "proposal" and trial["events"][4]["payload"]["amount_vnd"] == 0
    assert got["refund_amount_correct"] is True      # outcome graders alone miss it
    assert got["quote_kept"] is False                # the step check catches it
    assert got["pass_rate"] is False                 # Lab 8: proposal_mismatch


def test_lab9_trace_case_c013_fixed_passes():
    _, got = _grade("fixed", "C-013", 11)
    assert got["quote_kept"] is True and got["refund_amount_correct"] is True and got["pass_rate"] is True
