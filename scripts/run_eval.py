"""Runs the known-answer questions and scores the answers against ground truth."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import GROUND_TRUTH_PATH  # noqa: E402
from core.pipeline import PaymentLens  # noqa: E402

CASES = ROOT / "tests" / "eval_questions.json"
REPORT_DIR = ROOT / "reports"


def gt_value(ref, gt):
    if not (isinstance(ref, str) and ref.startswith("gt:")):
        return ref
    cur = gt
    for part in ref[3:].split("."):
        cur = cur[part]
    return cur


def evaluate_case(case: dict, res, gt: dict) -> dict:
    e, a = case["expect"], res.analysis
    tol = e.get("tolerance", 1e-9)
    checks: dict[str, bool] = {"status": res.status == e["status"]}
    if res.intent and "metric" in e:
        checks["metric"] = res.intent.metric == e["metric"]
    if res.intent and "analysis_type" in e:
        checks["analysis_type"] = res.intent.analysis_type == e["analysis_type"]
    if "dimensions_include" in e:
        checks["dimensions"] = bool(res.intent) and e["dimensions_include"] in res.intent.dimensions
    if "grain" in e:
        checks["grain"] = a.get("grain") == e["grain"]
    if "value" in e:
        v = (a.get("overall") or {}).get("current", {}).get("value")
        checks["value"] = v is not None and abs(v - gt_value(e["value"], gt)) <= tol
    if "previous_value" in e:
        v = (a.get("overall") or {}).get("previous", {}).get("value")
        checks["previous_value"] = v is not None and abs(v - gt_value(e["previous_value"], gt)) <= tol
    if "delta" in e:
        v = (a.get("overall") or {}).get("delta")
        checks["delta"] = v is not None and abs(v - gt_value(e["delta"], gt)) <= tol
    if "mix_effect" in e:
        v = (a.get("decomposition") or {}).get("mix_effect")
        checks["mix_effect"] = v is not None and abs(v - gt_value(e["mix_effect"], gt)) <= 1e-9
    if "top_rate_segment" in e:
        r = (a.get("drivers") or {}).get("rate") or [{}]
        checks["top_rate_segment"] = r[0].get("segment") == gt_value(e["top_rate_segment"], gt)
    if "top_mix_bank" in e:
        v = ((a.get("dimension_views") or {}).get("bank") or {}).get("top_mix", {}).get("segment")
        checks["top_mix_bank"] = v == gt_value(e["top_mix_bank"], gt)
    if "top_contribution_segment" in e:
        seg = res.tables.get("segments")
        checks["top_contribution"] = seg is not None and seg.sort_values("contribution").iloc[0]["segment"] == gt_value(e["top_contribution_segment"], gt)
    if "simpson" in e:
        checks["simpson"] = bool((a.get("simpson") or {}).get("detected")) == e["simpson"]
    if "missing_settlements" in e:
        checks["missing_settlements"] = (a.get("reconciliation") or {}).get("missing_settlement_txns") == gt_value(e["missing_settlements"], gt)
    if "filter_payment_method" in e:
        checks["filter"] = bool(res.resolved) and res.resolved.filters.get("payment_method") == [e["filter_payment_method"]]
    if "scoped_region" in e:
        checks["scope"] = bool(res.resolved) and res.resolved.filters.get("region") == [e["scoped_region"]]
    return checks


def run(use_llm: bool) -> dict:
    gt = json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    pl = PaymentLens()
    rows = []
    for c in cases:
        res = pl.run(c["question"], c["role"], use_llm=use_llm)
        checks = evaluate_case(c, res, gt)
        rows.append({"id": c["id"], "question": c["question"], "role": c["role"], "status": res.status,
                     "parser": res.parser_used, "passed": all(checks.values()), "checks": checks,
                     "queries": len(res.queries), "message": res.message[:160]})
    def rate(keys):
        vals = [r["checks"][k] for r in rows for k in keys if k in r["checks"]]
        return {"passed": sum(vals), "total": len(vals)}
    summary = {
        "mode": "llm" if use_llm else "rules",
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "cases_passed": sum(r["passed"] for r in rows), "cases_total": len(rows),
        "intent_accuracy": rate(["metric", "analysis_type", "dimensions", "grain", "filter"]),
        "status_accuracy": rate(["status"]),
        "numerical_correctness": rate(["value", "previous_value", "delta", "mix_effect", "missing_settlements"]),
        "driver_identification": rate(["top_rate_segment", "top_mix_bank", "top_contribution", "simpson"]),
        "policy_enforcement": {"passed": sum(r["checks"]["status"] for r in rows if r["status"] in ("DENIED", "BLOCKED") or
                                             any(k == "scope" for k in r["checks"])),
                               "total": sum(1 for c in cases if c["expect"]["status"] in ("DENIED", "BLOCKED") or "scoped_region" in c["expect"])},
    }
    return {"summary": summary, "cases": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="use the OpenAI parser/narrator")
    args = ap.parse_args()
    out = run(args.llm)
    REPORT_DIR.mkdir(exist_ok=True)
    path = REPORT_DIR / f"eval_report_{out['summary']['mode']}.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    s = out["summary"]
    print(f"Mode: {s['mode']}   Cases passed: {s['cases_passed']}/{s['cases_total']}")
    for k in ("intent_accuracy", "status_accuracy", "numerical_correctness", "driver_identification", "policy_enforcement"):
        print(f"  {k:24s} {s[k]['passed']}/{s[k]['total']}")
    for r in out["cases"]:
        mark = "PASS" if r["passed"] else "FAIL"
        failed = [k for k, v in r["checks"].items() if not v]
        print(f"  [{mark}] {r['id']} {r['status']:11s} {r['question'][:70]}" + (f"  failed: {failed}" if failed else ""))
    print(f"Report: {path}")


if __name__ == "__main__":
    main()
