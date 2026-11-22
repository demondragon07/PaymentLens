"""End-to-end tests comparing pipeline answers with the generated ground truth."""
import pytest

R = "business_analyst"


def test_weekly_success_rate(pl, gt):
    r = pl.run("What was payment success rate in the week of Nov 9?", R, use_llm=False)
    assert r.status == "ANSWERED"
    assert r.analysis["overall"]["current"]["value"] == pytest.approx(gt["weekly_success_rate"]["W4"]["rate"], abs=1e-12)
    assert r.analysis["overall"]["current"]["den"] == gt["weekly_success_rate"]["W4"]["attempts"]


def test_root_cause_w4_vs_w3(pl, gt):
    r = pl.run("Why did payment success rate fall last week?", R, use_llm=False)
    g = gt["w4_vs_w3_bank_x_method"]
    d = r.analysis["decomposition"]
    assert r.status == "ANSWERED"
    assert r.resolved.current.pretty() == "09 Nov 2026 - 15 Nov 2026"
    for k in ("R0", "R1", "delta", "rate_effect", "mix_effect", "counterfactual_rate"):
        assert d[k] == pytest.approx(g[k], abs=1e-12), k
    assert d["reconciles"]
    assert r.analysis["drivers"]["rate"][0]["segment"] == g["top_negative_rate_segment"]      # Nova Bank | UPI
    assert r.analysis["dimension_views"]["bank"]["top_mix"]["segment"] == gt["w4_vs_w3_bank"]["top_negative_mix_segment"]
    assert r.analysis["drilldown"]["top_reason"] == gt["nova_upi"]["w4_top_decline_reason"]
    assert r.analysis["drilldown"]["bad_days"] == ["11 Nov", "12 Nov", "13 Nov", "14 Nov"]   # planted outage days
    assert not r.analysis["simpson"]["detected"]


def test_simpson_w2_vs_w1(pl, gt):
    r = pl.run("Why did success rate fall in the week of Oct 26 compared with the week before?", R, use_llm=False)
    g = gt["w2_vs_w1_bank"]
    assert r.analysis["overall"]["delta"] == pytest.approx(g["delta"], abs=1e-12)
    assert r.analysis["decomposition"]["rate_effect"] > 0 > r.analysis["decomposition"]["mix_effect"]
    assert r.analysis["simpson"]["detected"]
    assert all(gt["w2_bank_rates"][b] > gt["w1_bank_rates"][b] for b in gt["w1_bank_rates"])


def test_raw_vs_trusted_and_dq_counts(pl, gt):
    r = pl.run("What was success rate last week using raw data?", "admin", use_llm=False)
    assert r.analysis["overall"]["current"]["value"] == pytest.approx(gt["w4_raw_success_rate"]["rate"], abs=1e-12)
    checks = {c["check"]: c["count"] for c in r.dq["checks"]}
    assert checks["Duplicate txn_id"] == gt["data_quality"]["duplicate_extra_rows"]
    assert checks["Invalid status"] == gt["data_quality"]["invalid_status_rows"]
    assert checks["Future timestamps"] == gt["data_quality"]["future_timestamp_rows"]
    assert 0 < checks["Missing bank_id"] <= gt["data_quality"]["missing_bank_id_rows"]
    assert r.dq["freshness"]["is_partial"] and str(r.dq["freshness"]["last_complete_day"]) == "2026-11-15"


def test_order_conversion(pl, gt):
    r = pl.run("What was order conversion last week?", R, use_llm=False)
    assert r.intent.metric == "order_conversion_rate"
    # an order retried across two weeks may land in either week, so allow a tiny difference
    assert r.analysis["overall"]["current"]["value"] == pytest.approx(gt["weekly_order_conversion"]["W4"], abs=1e-3)


def test_reconciliation(pl, gt):
    r = pl.run("Reconcile last week's successful transactions with settlements", "admin", use_llm=False)
    rc = r.analysis["reconciliation"]
    assert rc["identity_holds"]
    assert rc["missing_settlement_txns"] == gt["planted"]["settlements"]["missing_settlement_records"]
    assert rc["successful_txns"] == gt["weekly_success_rate"]["W4"]["successes"]


def test_segment_filter(pl, gt):
    r = pl.run("What was success rate for Nova Bank UPI last week compared with the previous week?", R, use_llm=False)
    assert r.resolved.filters == {"bank": ["Nova Bank"], "payment_method": ["UPI"]}
    assert r.analysis["overall"]["current"]["value"] == pytest.approx(gt["nova_upi"]["W4"]["rate"], abs=1e-12)
    assert r.analysis["overall"]["previous"]["value"] == pytest.approx(gt["nova_upi"]["W3"]["rate"], abs=1e-12)


def test_access_denied_and_scope(pl):
    r = pl.run("Show individual merchants with their settlement bank account details", R, use_llm=False)
    assert r.status == "DENIED" and not any(q.purpose.startswith("Root") for q in r.queries)
    north = pl.run("What was payment success rate last week?", "regional_analyst_north", use_llm=False)
    admin = pl.run("What was payment success rate for North last week?", "admin", use_llm=False)
    assert north.resolved.filters == {"region": ["North"]}
    assert north.analysis["overall"]["current"]["value"] == pytest.approx(admin.analysis["overall"]["current"]["value"])


def test_root_cause_not_blocked_when_parser_lists_all_dimensions(pl, gt, monkeypatch):
    """Bug fix check: the AI once listed 4 dimensions for 'why' questions and the query limit blocked them."""
    import core.pipeline as pipeline_mod
    real = pipeline_mod.parse_question

    def llm_like(question, catalog, **kw):
        intent, parser, notes, meta = real(question, catalog, **kw)
        intent.dimensions = ["bank", "payment_method", "merchant_category", "region"]
        return intent, "llm", notes, meta
    monkeypatch.setattr(pipeline_mod, "parse_question", llm_like)
    r = pl.run("Why did payment success rate fall last week?", R, use_llm=False)
    assert r.status == "ANSWERED"
    assert r.analysis["decomposition"]["delta"] == pytest.approx(gt["w4_vs_w3_bank_x_method"]["delta"], abs=1e-12)
    assert r.analysis["grain"] == ["bank", "payment_method"]


def test_budget_and_unsupported(pl):
    assert pl.run("Show success rate for the last 120 days", "admin", use_llm=False).status == "BLOCKED"
    assert pl.run("Did Zenith Bank intentionally reject our transactions?", "admin", use_llm=False).status == "UNSUPPORTED"
    assert pl.run("Show success rate for Atlantis Bank last week", "admin", use_llm=False).status == "UNSUPPORTED"
