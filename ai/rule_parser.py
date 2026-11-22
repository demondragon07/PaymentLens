"""Offline keyword and date-rule parser that builds the same AnalysisIntent as the LLM."""
from __future__ import annotations

import re
from datetime import date, timedelta

from core.models import AnalysisIntent, Filter, TimeSpec

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"

UNSUPPORTED = {
    "intentionally": "The data records payment outcomes and decline codes, not a bank's intent or decision logic, so intent cannot be established.",
    "deliberately": "The data records payment outcomes and decline codes, not a bank's intent or decision logic, so intent cannot be established.",
    "on purpose": "The data records payment outcomes and decline codes, not a bank's intent or decision logic, so intent cannot be established.",
    "refund": "Refund data is not available in the supplied datasets.",
    "chargeback": "Chargeback/dispute data is not available in the supplied datasets.",
    "dispute": "Chargeback/dispute data is not available in the supplied datasets.",
    "forecast": "Forecasting is not supported; PaymentLens analyses historical data only.",
    "predict": "Prediction is not supported; PaymentLens analyses historical data only.",
    "next week": "Forecasting is not supported; PaymentLens analyses historical data only.",
    "profit": "Profit and cost data are not available in the supplied datasets.",
    "customer age": "Customer demographic data is not available.",
    "gender": "Customer demographic data is not available.",
}

SENSITIVE = [
    (r"account number|bank account|settlement account|account detail|bank details|ifsc", "settlement_account"),
    (r"e-?mail|contact detail|phone", "contact_email"),
    (r"merchant name", "merchant_name"),
]

DIM_WORDS = {
    "bank": r"banks?|issuers?",
    "payment_method": r"payment methods?|methods?|instruments?|channels?",
    "merchant_category": r"categor(?:y|ies)|verticals?|segments? of merchants",
    "region": r"regions?|geograph(?:y|ies)|zones?",
    "decline_reason": r"decline reasons?|failure reasons?|error codes?|reasons? for failure",
    "merchant": r"merchants?",
    "day": r"days?|daily",
}


def detect_sensitive(q: str) -> list[str]:
    q = q.lower()
    return [attr for pat, attr in SENSITIVE if re.search(pat, q)]


def _mkdate(mon: str, day: str, year: int) -> date:
    return date(year, MONTHS[mon[:3]], int(day))


def _parse_time(q: str, year: int) -> tuple[TimeSpec, str, TimeSpec | None, list[str]]:
    amb: list[str] = []
    none = dict(n_days=None, start=None, end=None)
    comparison = "none"
    comp_phrase = re.search(r"(compared? (with|to)|vs\.?|versus|than) (the )?(previous|prior|last|preceding) (week|period)|"
                            r"week[- ]over[- ]week|\bwow\b|(the )?week before", q)
    if comp_phrase:
        comparison = "previous_period"

    iso = re.findall(r"(\d{4}-\d{2}-\d{2})", q)
    m_week = re.search(r"week (of|starting|beginning) " + _MON + r"\s+(\d{1,2})|week (of|starting|beginning) (\d{1,2})\s+" + _MON, q)
    m_range = re.search(_MON + r"\s+(\d{1,2})\s*(?:-|to|and|until|through)\s*(?:" + _MON + r"\s+)?(\d{1,2})", q)
    if m_week:
        if m_week.group(2):
            start = _mkdate(m_week.group(2), m_week.group(3), year)
        else:
            start = _mkdate(m_week.group(6), m_week.group(5), year)
        return TimeSpec(kind="explicit", n_days=None, start=str(start), end=str(start + timedelta(days=6))), comparison, None, amb
    if len(iso) >= 2:
        return TimeSpec(kind="explicit", n_days=None, start=iso[0], end=iso[1]), comparison, None, amb
    if m_range:
        start = _mkdate(m_range.group(1), m_range.group(2), year)
        end_mon = m_range.group(3) or m_range.group(1)
        end = _mkdate(end_mon, m_range.group(4), year)
        return TimeSpec(kind="explicit", n_days=None, start=str(start), end=str(end)), comparison, None, amb
    m_on = re.search(r"\bon " + _MON + r"\s+(\d{1,2})", q) or (re.search(r"\bon (\d{4}-\d{2}-\d{2})", q))
    if m_on and m_on.lastindex and m_on.lastindex >= 2:
        d = _mkdate(m_on.group(1), m_on.group(2), year)
        return TimeSpec(kind="explicit", n_days=None, start=str(d), end=str(d)), comparison, None, amb
    if len(iso) == 1:
        return TimeSpec(kind="explicit", n_days=None, start=iso[0], end=iso[0]), comparison, None, amb

    m_n = re.search(r"(last|past|previous) (\d{1,3}) days", q)
    if m_n:
        return TimeSpec(kind="last_n_days", n_days=int(m_n.group(2)), start=None, end=None), comparison, None, amb
    if "yesterday" in q:
        return TimeSpec(kind="yesterday", **none), comparison, None, amb
    if "this week" in q:
        return TimeSpec(kind="this_week", **none), comparison, None, amb
    if re.search(r"\b(last|past) week\b", q):
        amb.append("'Last week' could mean the last calendar week (Mon-Sun) or the last 7 days.")
        return TimeSpec(kind="last_full_week", **none), comparison, None, amb
    if comp_phrase:
        amb.append("Only a comparison ('previous week') was given; current period taken as the last full week.")
        return TimeSpec(kind="last_full_week", **none), comparison, None, amb
    amb.append("No time period stated.")
    return TimeSpec(kind="unspecified", **none), comparison, None, amb


def _metric(q: str) -> tuple[str | None, bool, list[str]]:
    if re.search(r"conversion|order[- ]level|\borders?\b.*(succe|convert)|net of retr", q):
        return "order_conversion_rate", True, []
    if re.search(r"attempt[- ]level|per attempt|gross success", q):
        return "payment_success_rate", True, []
    if re.search(r"\bgmv\b|\btpv\b|revenue|amount processed|value processed|payment value", q):
        return "successful_gmv", True, []
    if re.search(r"succe|approv|fail|declin|authori[sz]", q):
        return "payment_success_rate", False, [
            "'Success rate' could be attempt-level (each retry counted) or order-level (net of retries); "
            "used attempt-level Payment Success Rate."]
    if re.search(r"how many|number of (transactions|payments|attempts)|transaction count|traffic|volume", q):
        return "transaction_count", True, []
    return None, False, []


def _analysis(q: str) -> str:
    if re.search(r"reconcil|settle(d|ment)?s?\b(?! account)", q) and not re.search(r"settlement account", q):
        return "reconciliation"
    if re.search(r"\bwhy\b|root cause|caus(e|ed)|what (drove|happened)|driv(er|ing)|explain|contribut|reason for|due to|"
                 r"\bmix\b", q):
        return "root_cause"
    if re.search(r"trend|over time|daily|day by day|each day|per day|by day", q):
        return "trend"
    if re.search(r"\bby\b|breakdown|break down|split|\bper\b|which|across|each|top \d*|worst|best|rank", q):
        return "breakdown"
    return "summary"


def _dimensions(q: str, analysis: str) -> list[str]:
    dims = []
    for dim, words in DIM_WORDS.items():
        if dim == "day":
            continue
        if re.search(rf"\b(by|per|which|each|across|every|top \d* ?|worst|best|compare)\s+(the\s+)?({words})\b", q) or \
           re.search(rf"\b({words})\s+(breakdown|split|wise)\b", q):
            dims.append(dim)
    if analysis == "breakdown" and not dims:
        for dim, words in DIM_WORDS.items():
            if dim != "day" and re.search(rf"\b({words})\b", q):
                dims.append(dim)
                break
    return dims[:3]


def _filters(question: str, catalog: dict[str, list[str]]) -> list[Filter]:
    q = question.lower()
    out: list[Filter] = []
    for dim, values in catalog.items():
        hits = []
        for v in values:
            vl = v.lower()
            short = vl.replace(" bank", "") if dim == "bank" else vl
            pat = rf"\b{re.escape(vl)}\b" if dim != "bank" else rf"\b({re.escape(vl)}|{re.escape(short)})\b"
            if dim == "decline_reason":
                pat = rf"\b{re.escape(vl.replace('_', ' '))}\b|\b{re.escape(vl)}\b"
            if dim == "merchant":
                pat = rf"\b{re.escape(vl)}\b"
            if re.search(pat, q):
                hits.append(v)
        if dim == "bank":
            # if the user names a bank we don't have, keep it so we can tell them it is unknown
            known = {v.lower() for v in values}
            for m in re.finditer(r"\b([A-Za-z]+) bank\b", question, flags=re.I):
                name = f"{m.group(1).title()} Bank"
                if name.lower() not in known and m.group(1).lower() not in ("the", "a", "each", "every", "which", "per", "by", "any", "one", "settlement", "merchant", "issuing", "partner", "their", "our"):
                    hits.append(name)
        if hits:
            out.append(Filter(dimension=dim, values=hits))
    return out


def parse(question: str, catalog: dict[str, list[str]], year: int = 2026) -> AnalysisIntent:
    q = " ".join(question.lower().split())
    for kw, reason in UNSUPPORTED.items():
        if kw in q:
            return AnalysisIntent(
                is_supported=False, unsupported_reason=reason, metric=None, metric_explicit=False,
                analysis_type="summary", current_period=TimeSpec(kind="unspecified", n_days=None, start=None, end=None),
                comparison="none", comparison_period=None, dimensions=[], filters=[], data_source="trusted",
                requested_attributes=detect_sensitive(q), ambiguities=[])
    analysis = _analysis(q)
    metric, explicit, amb_m = _metric(q)
    attrs = detect_sensitive(q)
    amb = [] if analysis == "reconciliation" else list(amb_m)
    if metric is None:
        metric = "payment_success_rate"
        if not attrs and analysis != "reconciliation":
            amb.append("No metric named; defaulted to Payment Success Rate.")
    spec, comparison, comp_spec, amb_t = _parse_time(q, year)
    amb += amb_t
    if comparison == "none" and re.search(r"\bcompare|change[sd]?\b|\bvs\b|versus|previous|before|worsen|improv|than|"
                                          r"fall|fell|drop|declin|decreas|increas|rise|rose|went (up|down)", q):
        comparison = "previous_period"
    dims = _dimensions(q, analysis)
    if analysis == "trend":
        dims = ["day"] + [d for d in dims if d != "day"][:1]
    filters = _filters(question, {k: v for k, v in catalog.items() if k != "merchant" or re.search(r"\bm\d{3}\b", q)})
    return AnalysisIntent(
        is_supported=True, unsupported_reason=None, metric=metric, metric_explicit=explicit,
        analysis_type=analysis, current_period=spec, comparison=comparison, comparison_period=comp_spec,
        dimensions=dims, filters=filters, data_source="raw" if re.search(r"\braw\b|unfiltered|uncleaned", q) else "trusted",
        requested_attributes=attrs, ambiguities=amb)
