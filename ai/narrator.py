"""Writes the answer text with the LLM and rejects it if it uses numbers not in the facts."""
from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel

from core.config import PROMPT_DIR
from core.models import Fact, Hypothesis, Narrative
from ai.llm_client import LLMUnavailable, llm_configured, structured_call

NUM = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


class LLMObservation(BaseModel):
    text: str
    fact_ids: list[str]


class LLMHypothesis(BaseModel):
    text: str
    confidence: Literal["low", "medium", "high"]
    evidence_fact_ids: list[str]


class LLMNarrative(BaseModel):
    summary: str
    observed: list[LLMObservation]
    hypotheses: list[LLMHypothesis]
    recommendations: list[str]


def _numbers(text: str) -> set[str]:
    out = set()
    for n in NUM.findall(text):
        n = n.replace(",", "").lstrip("+-")
        if "." in n:
            n = n.rstrip("0").rstrip(".")
        out.add(n)
    return out


def grounding_check(narr: LLMNarrative, facts: list[Fact], draft: Narrative) -> dict:
    allowed_text = " ".join(f.text for f in facts) + " " + draft.model_dump_json()
    allowed = _numbers(allowed_text) | {str(i) for i in range(0, 11)}
    ids = {f.id for f in facts}
    texts = [narr.summary] + [o.text for o in narr.observed] + [h.text for h in narr.hypotheses] + narr.recommendations
    unmatched = sorted({n for t in texts for n in _numbers(t)} - allowed)
    bad_ids = sorted({i for o in narr.observed for i in o.fact_ids} | {i for h in narr.hypotheses for i in h.evidence_fact_ids})
    bad_ids = [i for i in bad_ids if i not in ids]
    uncited = [o.text[:60] for o in narr.observed if not o.fact_ids]
    return {"passed": not unmatched and not bad_ids and not uncited, "unmatched_numbers": unmatched,
            "invalid_fact_ids": bad_ids, "uncited_observations": uncited}


def narrate(facts: list[Fact], draft: Narrative, use_llm: bool) -> tuple[Narrative, list[str]]:
    notes: list[str] = []
    if not (use_llm and llm_configured()) or not facts:
        draft.grounding = {"passed": True, "note": "Template narrative (built directly from computed facts)."}
        return draft, notes
    payload = {
        "FACTS": [{"id": f.id, "text": f.text} for f in facts],
        "DRAFT": {"summary": draft.summary, "hypotheses": [h.model_dump() for h in draft.hypotheses],
                  "recommendations": draft.recommendations},
    }
    system = (PROMPT_DIR / "narrator_system.md").read_text(encoding="utf-8")
    try:
        out, meta = structured_call(system, json.dumps(payload, indent=1), LLMNarrative)
    except LLMUnavailable as e:
        notes.append(f"AI narrative unavailable ({e}); showing the template narrative.")
        draft.grounding = {"passed": True, "note": "Template narrative (LLM unavailable)."}
        return draft, notes
    g = grounding_check(out, facts, draft)
    g["llm"] = meta
    if not g["passed"]:
        notes.append("AI narrative rejected by the grounding check (it contained numbers or citations not in the "
                     f"computed facts: {g['unmatched_numbers'] or g['invalid_fact_ids'] or g['uncited_observations']}); "
                     "showing the template narrative.")
        draft.grounding = g
        return draft, notes
    narr = Narrative(
        summary=out.summary,
        observed=[f"[{', '.join(o.fact_ids)}] {o.text}" for o in out.observed],
        hypotheses=[Hypothesis(text=h.text, confidence=h.confidence, evidence=h.evidence_fact_ids) for h in out.hypotheses],
        recommendations=out.recommendations, generated_by="llm", grounding=g)
    return narr, notes
