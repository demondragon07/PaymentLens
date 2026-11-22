"""Reconciles successful transactions against settlement records."""
from __future__ import annotations

from core.models import Period
from sqlengine.compiler import compile_reconciliation


def reconcile(svc, period: Period) -> dict:
    q = compile_reconciliation(period)
    df, rec = svc.run(q.sql, q.purpose)
    r = {k: (float(v) if v is not None else 0.0) for k, v in df.iloc[0].to_dict().items()}
    explained = r["settled_gross_amount"] + r["amount_mismatch_value"] + r["pending_amount"] + r["missing_settlement_amount"]
    gap = r["successful_amount"] - r["settled_gross_amount"]
    r.update({
        "period": period.pretty(),
        "gap_amount": round(gap, 2),
        "gap_pct": gap / r["successful_amount"] * 100 if r["successful_amount"] else 0.0,
        "identity_holds": abs(explained - r["successful_amount"]) < 0.05,
        "query_id": rec.id,
        "components": [
            {"component": "Settled (gross)", "txns": r["settled_txns"], "amount": r["settled_gross_amount"],
             "meaning": "Matched settlement records with status SETTLED"},
            {"component": "Amount mismatch on settled", "txns": r["amount_mismatch_txns"], "amount": r["amount_mismatch_value"],
             "meaning": "Settled but settlement gross amount differs from transaction amount (break)"},
            {"component": "Pending settlement", "txns": r["pending_txns"], "amount": r["pending_amount"],
             "meaning": "Settlement record exists but not yet settled (timing difference, expected)"},
            {"component": "Missing settlement record", "txns": r["missing_settlement_txns"], "amount": r["missing_settlement_amount"],
             "meaning": "Successful transaction with no settlement record (break, investigate)"},
        ],
    })
    return r
