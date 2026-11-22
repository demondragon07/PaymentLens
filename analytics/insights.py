"""Builds facts, hypotheses, recommendations and the confidence score from the analysis."""
from __future__ import annotations

from core.models import AnalysisResult, Fact, Hypothesis, Narrative


def pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def pp(x: float) -> str:
    return f"{x * 100:+.2f}pp"


def _p(p: float) -> str:
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}"


class _Facts:
    def __init__(self):
        self.items: list[Fact] = []

    def add(self, text: str, qids: list[str]) -> str:
        fid = f"F{len(self.items) + 1}"
        self.items.append(Fact(fid, text, [q for q in qids if q]))
        return fid


def build_facts(res: AnalysisResult) -> tuple[list[Fact], dict]:
    a, rq, F = res.analysis, res.resolved, _Facts()
    refs: dict[str, str] = {}
    label = a.get("metric_label", "")
    ov = a.get("overall")
    main_q = a.get("main_query_id")
    if ov and ov.get("previous") and ov.get("current") and a.get("kind") == "ratio":
        p, c = ov["previous"], ov["current"]
        refs["overall"] = F.add(
            f"{label} moved from {pct(p['value'])} ({rq.previous.pretty()}, n={p['den']:,}) to {pct(c['value'])} "
            f"({rq.current.pretty()}, n={c['den']:,}): {pp(ov['delta'])} ({_p(ov['p_value'])}).", [main_q])
    elif ov and ov.get("current"):
        c = ov["current"]
        val = pct(c["value"]) if a.get("kind") == "ratio" else f"{c['value']:,.2f}"
        extra = f" (95% CI {pct(c['ci'][0])} - {pct(c['ci'][1])}, n={c['den']:,})" if a.get("kind") == "ratio" else ""
        refs["overall"] = F.add(f"{label} for {rq.current.pretty()}: {val}{extra}.", [main_q])
        if ov.get("previous"):
            pv = ov["previous"]
            pval = pct(pv["value"]) if a.get("kind") == "ratio" else f"{pv['value']:,.2f}"
            refs["prev"] = F.add(f"Previous period ({rq.previous.pretty()}): {pval}.", [main_q])

    d = a.get("decomposition")
    if d:
        refs["decomp"] = F.add(
            f"Decomposition at {' x '.join(d['keys'])} level: within-segment rate effect {pp(d['rate_effect'])}, "
            f"traffic-mix effect {pp(d['mix_effect'])}; sum {pp(d['rate_effect'] + d['mix_effect'])} equals the observed change "
            f"(residual {d['residual']:.1e}).", [main_q])
        refs["cf"] = F.add(
            f"Counterfactual (previous traffic mix, current segment rates): {pct(d['counterfactual_rate'])} vs {pct(d['R1'])} actual. "
            f"Measured this way, performance accounts for {pp(d['cf_rate_effect'])} and mix for {pp(d['cf_mix_effect'])}; the "
            f"symmetric split differs only because it shares the interaction term ({pp(d['interaction'])}) equally.", [main_q])

    bank = a.get("dimension_views", {}).get("bank")
    if bank and bank.get("top_mix"):
        t = bank["top_mix"]
        refs["mix_driver"] = F.add(
            f"{t['segment']}: traffic share {pct(t['w0'])} -> {pct(t['w1'])}, success rate {pct(t['r0'])} -> {pct(t['r1'])} "
            f"(below the {pct(bank['rbar'])} average); mix contribution {pp(t['mix_effect'])}.", [main_q])
    for i, t in enumerate(a.get("drivers", {}).get("rate", [])[:2]):
        if not t["significant"]:
            continue
        refs[f"rate_driver{i}"] = F.add(
            f"{t['segment']}: success rate {pct(t['r0'])} -> {pct(t['r1'])} ({pp(t['rate_change'])}, {_p(t['p_value'])}) on "
            f"{pct(t['w1'])} of current traffic; rate contribution {pp(t['rate_effect'])}.", [main_q])

    dd = a.get("drilldown")
    if dd and dd.get("top_reason"):
        refs["drill_reason"] = F.add(
            f"{dd['segment']} failures with reason {dd['top_reason']}: {dd['reason_prev']:,} -> {dd['reason_cur']:,} "
            f"({pct(dd['reason_share_prev'])} -> {pct(dd['reason_share_cur'])} of the segment's failures).", [dd.get("reason_query_id")])
        if dd.get("bad_days"):
            refs["drill_days"] = F.add(
                f"{dd['segment']} daily success was well below its previous-period level ({pct(dd['baseline'])}) on "
                f"{', '.join(dd['bad_days'])}.", [dd.get("daily_query_id")])

    sim = a.get("simpson")
    if sim and sim.get("detected"):
        refs["simpson"] = F.add(sim["message"], [main_q])

    for t in a.get("breakdown_top", []):
        refs.setdefault("breakdown", F.add(t, [main_q]))

    rc = a.get("reconciliation")
    if rc:
        refs["recon"] = F.add(
            f"Successful transactions {rc['period']}: {rc['successful_txns']:,.0f} worth INR {rc['successful_amount']:,.2f}; "
            f"settled gross INR {rc['settled_gross_amount']:,.2f} - a gap of INR {rc['gap_amount']:,.2f} ({rc['gap_pct']:.2f}%).",
            [rc["query_id"]])
        refs["recon_parts"] = F.add(
            f"Gap explained: pending settlement INR {rc['pending_amount']:,.2f} ({rc['pending_txns']:.0f} txns), missing settlement "
            f"records INR {rc['missing_settlement_amount']:,.2f} ({rc['missing_settlement_txns']:.0f} txns), amount mismatches "
            f"INR {rc['amount_mismatch_value']:,.2f} ({rc['amount_mismatch_txns']:.0f} txns). Identity holds: {rc['identity_holds']}.",
            [rc["query_id"]])

    tr = a.get("trend_summary")
    if tr:
        refs["trend"] = F.add(tr, [a.get("trend_query_id")])

    imp = (res.dq or {}).get("raw_vs_trusted")
    dup = next((c for c in (res.dq or {}).get("checks", []) if c["check"] == "Duplicate txn_id"), None)
    if imp and abs(imp["difference_pp"]) >= 0.01:
        refs["dq_impact"] = F.add(
            f"Raw data gives {pct(imp['raw_rate'])} (n={imp['raw_denominator']:,}) vs {pct(imp['trusted_rate'])} "
            f"(n={imp['trusted_denominator']:,}) on the trusted view for the current period ({imp['difference_pp']:+.2f}pp); "
            f"{dup['count'] if dup else 0} duplicate rows were excluded.", imp["query_ids"])
    fr = (res.dq or {}).get("freshness")
    if fr and fr.get("is_partial"):
        refs["fresh"] = F.add(
            f"{fr['last_day']:%d %b} is partially loaded ({fr['last_day_attempts']} attempts vs ~{fr['trailing_median_attempts']:.0f}/day) "
            f"and was excluded from relative periods.", [fr["query_id"]])
    return F.items, refs


def template_narrative(res: AnalysisResult, facts: list[Fact], refs: dict) -> Narrative:
    a = res.analysis
    by_id = {f.id: f.text for f in facts}
    observed = [f"[{f.id}] {f.text}" for f in facts]
    hyps: list[Hypothesis] = []
    recs: list[str] = []

    dd = a.get("drilldown")
    if dd and dd.get("top_reason") and dd["reason_cur"] > dd["reason_prev"]:
        reason = dd["top_reason"]
        days = f" concentrated on {', '.join(dd['bad_days'])}" if dd.get("bad_days") else ""
        ev = [refs[k] for k in ("rate_driver0", "drill_reason", "drill_days") if k in refs]
        if reason in ("ISSUER_UNAVAILABLE", "TIMEOUT"):
            text = (f"The deterioration in {dd['segment']} is consistent with an issuer or network availability problem "
                    f"({reason} failures rose{days}).")
            rec = (f"Check {dd['segment']} issuer/switch availability and error logs for {', '.join(dd.get('bad_days') or ['the current period'])}; "
                   f"consider failover routing for this segment while it is degraded.")
        elif reason == "AUTHENTICATION_FAILED":
            text = f"The deterioration in {dd['segment']} may reflect an authentication (OTP/3-D Secure) flow problem{days}."
            rec = f"Review authentication success and OTP delivery for {dd['segment']}."
        else:
            text = f"The deterioration in {dd['segment']} is driven by more {reason} declines{days}, which suggests a customer- or risk-rule-side change."
            rec = f"Review recent risk-rule or customer-mix changes affecting {dd['segment']}."
        conf = "medium" if dd.get("bad_days") else "low"
        hyps.append(Hypothesis(text=text + " Infrastructure telemetry is not available in this dataset to confirm it.",
                               confidence=conf, evidence=ev))
        recs.append(rec)

    d = a.get("decomposition")
    bank = a.get("dimension_views", {}).get("bank")
    if d and bank and bank.get("top_mix") and d["delta"] != 0 and abs(d["mix_effect"]) >= 0.25 * abs(d["delta"]):
        t = bank["top_mix"]
        hyps.append(Hypothesis(
            text=(f"Part of the change comes from traffic moving toward {t['segment']} (share {pct(t['w0'])} -> {pct(t['w1'])}), "
                  f"whose success rate is structurally lower but did not itself deteriorate much ({pct(t['r0'])} -> {pct(t['r1'])}). "
                  f"A routing change, campaign or merchant onboarding could explain the shift; the data shows the shift, not its cause."),
            confidence="medium", evidence=[refs[k] for k in ("decomp", "cf", "mix_driver", "simpson") if k in refs]))
        recs.append(f"Review routing rules, campaigns or merchant onboarding that moved traffic to {t['segment']} and "
                    f"quantify the success-rate cost before keeping the change.")

    rc = a.get("reconciliation")
    if rc and rc["missing_settlement_txns"] > 0:
        hyps.append(Hypothesis(
            text="Pending amounts are a normal timing difference; missing settlement records and amount mismatches are genuine breaks.",
            confidence="high", evidence=[refs["recon_parts"]]))
        recs.append(f"Raise the {rc['missing_settlement_txns']:.0f} missing settlement records and {rc['amount_mismatch_txns']:.0f} "
                    f"amount mismatches with the settlement operations team.")

    if "dq_impact" in refs:
        recs.append("Fix the ingestion replay that creates duplicate transaction rows; report only from the trusted view until then.")
    if not recs:
        recs.append("No anomaly requiring action was detected for this question; continue routine monitoring.")

    ov = a.get("overall") or {}
    if refs.get("overall") and ov.get("delta") is not None and a.get("kind") == "ratio" and res.resolved.previous:
        direction = "fell" if ov["delta"] < 0 else "rose"
        summary = f"{a['metric_label']} {direction} {abs(ov['delta']) * 100:.2f}pp ({pct(ov['previous']['value'])} -> {pct(ov['current']['value'])})."
        if d:
            summary += f" Segment performance explains {pp(d['rate_effect'])} and traffic mix {pp(d['mix_effect'])}."
    elif refs.get("overall"):
        summary = by_id[refs["overall"]]
    elif rc:
        summary = by_id[refs["recon"]]
    else:
        summary = "Analysis completed."
    return Narrative(summary=summary, observed=observed, hypotheses=hyps, recommendations=recs, generated_by="template")


def confidence(res: AnalysisResult) -> dict:
    score, reasons = 100, []
    if res.parser_used != "llm":
        score -= 5
        reasons.append("Question interpreted by the rule-based parser (LLM not used).")
    if res.intent and res.intent.ambiguities:
        score -= min(15, 5 * len(res.intent.ambiguities))
        reasons.append(f"{len(res.intent.ambiguities)} ambiguity(ies) resolved with stated assumptions.")
    warns = (res.dq or {}).get("warnings", 0)
    if warns:
        score -= min(20, 5 * warns)
        reasons.append(f"{warns} data-quality warning(s); affected rows were handled as shown.")
    ov = res.analysis.get("overall") or {}
    if ov.get("p_value") is not None and ov.get("p_value") >= 0.05:
        score -= 30
        reasons.append(f"The overall change is not statistically significant ({_p(ov['p_value'])}); it may be noise.")
    if ov.get("current") and res.analysis.get("kind") == "ratio" and ov["current"]["den"] < 1000:
        score -= 15
        reasons.append(f"Small sample (n={ov['current']['den']:,}).")
    if res.analysis.get("decomposition") and not res.analysis["decomposition"]["reconciles"]:
        score -= 40
        reasons.append("Decomposition did not reconcile with the observed change.")
    if not reasons:
        reasons.append("Large samples, significant change, no data-quality warnings.")
    level = "High" if score >= 75 else "Medium" if score >= 50 else "Low"
    reasons.append("Driver attribution is statistical contribution accounting, not proof of cause.")
    return {"level": level, "score": max(score, 0), "reasons": reasons}
