"""Turns a user question into an AnalysisIntent using the LLM, with the rule parser as fallback."""
from __future__ import annotations

from core.config import PROMPT_DIR, semantic
from core.models import AnalysisIntent
from ai import rule_parser
from ai.llm_client import LLMUnavailable, llm_configured, structured_call


def _metrics_text() -> str:
    lines = []
    for name, m in semantic()["metrics"].items():
        lines.append(f"- {name}: {m['label']}. {m['description']}")
    return "\n".join(lines)


def build_system_prompt(catalog: dict[str, list[str]], as_of: str, data_start: str, last_complete: str) -> str:
    tpl = (PROMPT_DIR / "intent_system.md").read_text(encoding="utf-8")
    cat = "\n".join(f"- {k}: {', '.join(v[:40])}" for k, v in catalog.items() if k != "merchant")
    cat += "\n- merchant: merchant ids like M001 ... M100"
    return (tpl.replace("{{METRICS}}", _metrics_text()).replace("{{CATALOG}}", cat)
               .replace("{{AS_OF}}", as_of).replace("{{DATA_START}}", data_start)
               .replace("{{LAST_COMPLETE}}", last_complete).replace("{{YEAR}}", last_complete[:4]))


def parse_question(question: str, catalog: dict[str, list[str]], *, as_of: str, data_start: str,
                   last_complete: str, use_llm: bool) -> tuple[AnalysisIntent, str, list[str], dict]:
    notes: list[str] = []
    meta: dict = {}
    intent: AnalysisIntent | None = None
    parser = "rules"
    if use_llm and llm_configured():
        try:
            system = build_system_prompt(catalog, as_of, data_start, last_complete)
            intent, meta = structured_call(system, question, AnalysisIntent)
            parser = "llm"
            meta["system_prompt_chars"] = len(system)
        except LLMUnavailable as e:
            notes.append(f"AI interpretation unavailable ({e}); used the rule-based parser instead.")
    elif use_llm:
        notes.append("No OPENAI_API_KEY configured; used the rule-based parser.")
    if intent is None:
        intent = rule_parser.parse(question, catalog, year=int(last_complete[:4]))
    extra = [a for a in rule_parser.detect_sensitive(question) if a not in intent.requested_attributes]
    if extra:
        intent.requested_attributes = intent.requested_attributes + extra
        notes.append(f"Safety check added requested attribute(s): {', '.join(extra)}.")
    if intent.is_supported and intent.metric is None:
        # if the AI gave no metric, use success rate (same as the offline parser) so nothing breaks
        intent.metric = "payment_success_rate"
        intent.ambiguities = intent.ambiguities + ["No metric named; defaulted to Payment Success Rate."]
    known_attrs = set(semantic()["attributes"])
    intent.requested_attributes = [a for a in intent.requested_attributes if a in known_attrs]
    if intent.analysis_type == "trend" and "day" not in intent.dimensions:
        intent.dimensions = ["day"] + intent.dimensions[:1]
    return intent, parser, notes, meta
