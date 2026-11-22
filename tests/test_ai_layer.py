"""Tests for LLM fallback, sensitive-request detection and the number-grounding check."""
from core.models import AnalysisIntent, TimeSpec
from ai import intent_parser, narrator
from ai.llm_client import LLMUnavailable
from ai.narrator import LLMHypothesis, LLMNarrative, LLMObservation, grounding_check

CAT = {"bank": ["Metro Bank", "Nova Bank", "Zenith Bank"], "payment_method": ["UPI", "CARD"]}
KW = dict(as_of="2026-11-16 06:00:00", data_start="2026-10-19", last_complete="2026-11-15")


def test_fallback_when_no_key():
    intent, parser, notes, _ = intent_parser.parse_question("Why did success rate fall last week?", CAT, use_llm=True, **KW)
    assert parser == "rules" and intent.analysis_type == "root_cause"
    assert any("OPENAI_API_KEY" in n for n in notes)


def test_fallback_when_llm_errors(monkeypatch):
    monkeypatch.setattr(intent_parser, "llm_configured", lambda: True)

    def boom(*a, **k):
        raise LLMUnavailable("APIConnectionError: network down")
    monkeypatch.setattr(intent_parser, "structured_call", boom)
    intent, parser, notes, _ = intent_parser.parse_question("Why did success rate fall last week?", CAT, use_llm=True, **KW)
    assert parser == "rules" and "network down" in notes[0]


def test_sensitive_request_cannot_be_hidden_by_llm(monkeypatch):
    """Even if the AI misses a request for sensitive data, the rule check still catches it."""
    monkeypatch.setattr(intent_parser, "llm_configured", lambda: True)
    benign = AnalysisIntent(is_supported=True, unsupported_reason=None, metric="payment_success_rate", metric_explicit=False,
                            analysis_type="breakdown", current_period=TimeSpec(kind="last_full_week", n_days=None, start=None, end=None),
                            comparison="none", comparison_period=None, dimensions=["merchant"], filters=[], data_source="trusted",
                            requested_attributes=[], ambiguities=[])
    monkeypatch.setattr(intent_parser, "structured_call", lambda *a, **k: (benign, {}))
    intent, parser, notes, _ = intent_parser.parse_question(
        "List merchants with settlement account numbers", CAT, use_llm=True, **KW)
    assert parser == "llm" and "settlement_account" in intent.requested_attributes


def test_llm_missing_metric_gets_default(monkeypatch):
    """Bug fix check: the AI once returned no metric for 'Which bank contributed most to the decline last week?'."""
    monkeypatch.setattr(intent_parser, "llm_configured", lambda: True)
    no_metric = AnalysisIntent(is_supported=True, unsupported_reason=None, metric=None, metric_explicit=False,
                               analysis_type="root_cause", current_period=TimeSpec(kind="last_full_week", n_days=None, start=None, end=None),
                               comparison="previous_period", comparison_period=None, dimensions=["bank"], filters=[],
                               data_source="trusted", requested_attributes=[], ambiguities=[])
    monkeypatch.setattr(intent_parser, "structured_call", lambda *a, **k: (no_metric, {}))
    intent, parser, _, _ = intent_parser.parse_question("Which bank contributed most to the decline last week?", CAT, use_llm=True, **KW)
    assert intent.metric == "payment_success_rate" and any("No metric" in a for a in intent.ambiguities)


def _facts():
    from core.models import Fact, Narrative
    facts = [Fact("F1", "Rate moved from 90.38% to 87.35%: -3.03pp.", ["Q3"])]
    draft = Narrative(summary="Rate fell 3.03pp.", observed=[], hypotheses=[], recommendations=["Check logs."])
    return facts, draft


def test_grounding_accepts_faithful_text():
    facts, draft = _facts()
    out = LLMNarrative(summary="Success fell 3.03pp, from 90.38% to 87.35%.",
                       observed=[LLMObservation(text="Rate fell from 90.38% to 87.35%.", fact_ids=["F1"])],
                       hypotheses=[], recommendations=["Check logs."])
    assert grounding_check(out, facts, draft)["passed"]


def test_grounding_rejects_invented_number_and_bad_citation():
    facts, draft = _facts()
    out = LLMNarrative(summary="Success fell 4.1pp.",
                       observed=[LLMObservation(text="Rate fell to 86.9%.", fact_ids=["F9"])],
                       hypotheses=[LLMHypothesis(text="Outage", confidence="high", evidence_fact_ids=["F1"])],
                       recommendations=[])
    g = grounding_check(out, facts, draft)
    assert not g["passed"] and "4.1" in g["unmatched_numbers"] and "F9" in g["invalid_fact_ids"]


def test_narrator_falls_back_to_template_on_bad_llm_output(monkeypatch):
    facts, draft = _facts()
    bad = LLMNarrative(summary="Success fell 9.99pp.", observed=[], hypotheses=[], recommendations=[])
    monkeypatch.setattr(narrator, "llm_configured", lambda: True)
    monkeypatch.setattr(narrator, "structured_call", lambda *a, **k: (bad, {}))
    narr, notes = narrator.narrate(facts, draft, use_llm=True)
    assert narr.generated_by == "template" and "grounding" in notes[0]
