"""Data-quality checks (freshness, duplicates, missing and invalid rows) and their impact on the metric."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from core.config import VALID_STATUSES, limits, semantic
from core.models import Period
from sqlengine.compiler import compile_metric


def freshness(svc, as_of: str) -> dict:
    sql = f"""SELECT CAST(t.created_at AS DATE) AS day, COUNT(*) AS attempts
FROM transactions AS t
WHERE t.created_at <= TIMESTAMP '{as_of}'
GROUP BY 1
ORDER BY 1 DESC
LIMIT 8"""
    df, rec = svc.run(sql, "Data quality: freshness (daily volume of latest days)")
    df["day"] = pd.to_datetime(df["day"]).dt.date
    last_day = df.iloc[0]["day"]
    last_n = int(df.iloc[0]["attempts"])
    median_prev = float(df.iloc[1:]["attempts"].median())
    threshold = float(limits()["freshness_partial_threshold"])
    partial = last_n < threshold * median_prev
    min_sql = "SELECT CAST(MIN(t.created_at) AS DATE) AS first_day FROM transactions AS t"
    first_df, _ = svc.run(min_sql, "Data quality: first day of data")
    return {
        "last_day": last_day, "last_day_attempts": last_n, "trailing_median_attempts": median_prev,
        "is_partial": bool(partial),
        "last_complete_day": last_day - timedelta(days=1) if partial else last_day,
        "first_day": pd.to_datetime(first_df.iloc[0]["first_day"]).date(),
        "query_id": rec.id,
    }


def _window(periods: list[Period]) -> tuple[str, str]:
    start = min(p.start for p in periods)
    end = max(p.end for p in periods)
    return f"{start:%Y-%m-%d} 00:00:00", f"{end + timedelta(days=1):%Y-%m-%d} 00:00:00"


def run_checks(svc, periods: list[Period], as_of: str, metric: str, filters: dict[str, list[str]],
               fresh: dict) -> dict:
    a, b = _window(periods)
    win = f"t.created_at >= TIMESTAMP '{a}' AND t.created_at < TIMESTAMP '{b}'"
    checks: list[dict] = []

    if fresh["is_partial"]:
        checks.append({"check": "Freshness", "severity": "warning", "count": fresh["last_day_attempts"],
                       "detail": f"{fresh['last_day']:%d %b} has only {fresh['last_day_attempts']} attempts vs a trailing "
                                 f"median of {fresh['trailing_median_attempts']:.0f}/day - the day is still loading.",
                       "handling": f"Excluded: relative periods end on the last complete day ({fresh['last_complete_day']:%d %b}).",
                       "query_id": fresh["query_id"]})

    df, rec = svc.run(f"""SELECT COUNT(*) AS duplicate_ids, COALESCE(SUM(c - 1), 0) AS extra_rows
FROM (SELECT t.txn_id, COUNT(*) AS c FROM transactions_raw AS t WHERE {win} GROUP BY t.txn_id HAVING COUNT(*) > 1) AS d""",
                      "Data quality: duplicate transaction ids in raw data")
    extra = int(df.iloc[0]["extra_rows"])
    checks.append({"check": "Duplicate txn_id", "severity": "warning" if extra else "ok", "count": extra,
                   "detail": f"{int(df.iloc[0]['duplicate_ids'])} transaction ids appear more than once ({extra} extra rows) in the analysis window.",
                   "handling": "Trusted view keeps the first ingested copy of each txn_id.", "query_id": rec.id})

    df, rec = svc.run(f"SELECT COUNT(*) AS n FROM transactions AS t WHERE t.bank_id IS NULL AND {win}",
                      "Data quality: missing bank_id")
    miss = int(df.iloc[0]["n"])
    checks.append({"check": "Missing bank_id", "severity": "warning" if miss else "ok", "count": miss,
                   "detail": f"{miss} trusted transactions in the window have no bank_id.",
                   "handling": "Kept in totals; shown as bank 'UNKNOWN' in breakdowns.", "query_id": rec.id})

    df, rec = svc.run(f"""SELECT COUNT(*) AS n FROM transactions AS t LEFT JOIN banks AS b ON t.bank_id = b.bank_id
WHERE t.bank_id IS NOT NULL AND b.bank_id IS NULL AND {win}""", "Data quality: bank_id with no matching bank")
    orphan = int(df.iloc[0]["n"])
    checks.append({"check": "Orphan bank_id", "severity": "warning" if orphan else "ok", "count": orphan,
                   "detail": f"{orphan} transactions reference a bank_id missing from the banks table.",
                   "handling": "Shown as 'UNKNOWN' bank.", "query_id": rec.id})

    valid = ", ".join(f"'{s}'" for s in VALID_STATUSES)
    df, rec = svc.run(f"""SELECT t.status AS status, COUNT(*) AS n FROM transactions_raw AS t
WHERE t.status NOT IN ({valid}) GROUP BY 1 ORDER BY 2 DESC""", "Data quality: invalid status values")
    inv = int(df["n"].sum()) if len(df) else 0
    checks.append({"check": "Invalid status", "severity": "info" if inv else "ok", "count": inv,
                   "detail": (f"{inv} raw rows have invalid statuses: " + ", ".join(f"'{s}'={n}" for s, n in zip(df.status, df.n))) if inv else "None",
                   "handling": "Excluded by the trusted view.", "query_id": rec.id})

    df, rec = svc.run(f"SELECT COUNT(*) AS n FROM transactions_raw AS t WHERE t.created_at > TIMESTAMP '{as_of}'",
                      "Data quality: timestamps after data as-of time")
    fut = int(df.iloc[0]["n"])
    checks.append({"check": "Future timestamps", "severity": "info" if fut else "ok", "count": fut,
                   "detail": f"{fut} raw rows are timestamped after the data as-of time ({as_of}).",
                   "handling": "Excluded by the trusted view.", "query_id": rec.id})

    impact = None
    spec = semantic()["metrics"][metric]
    cur = [p for p in periods if p.label == "current"]
    if spec["kind"] == "ratio" and cur:
        rates = {}
        for src in ("transactions_raw", "transactions"):
            q = compile_metric(metric, purpose=f"Data quality: {spec['label']} on {src} (current period)",
                               source=src, periods=cur, dims=[], filters=filters)
            d, r = svc.run(q.sql, q.purpose)
            rates[src] = (float(d.numerator.sum()) / float(d.denominator.sum()), int(d.denominator.sum()), r.id)
        raw, trusted = rates["transactions_raw"], rates["transactions"]
        impact = {"raw_rate": raw[0], "raw_denominator": raw[1], "trusted_rate": trusted[0],
                  "trusted_denominator": trusted[1], "difference_pp": (raw[0] - trusted[0]) * 100,
                  "query_ids": [raw[2], trusted[2]]}

    n_warn = sum(1 for c in checks if c["severity"] == "warning")
    return {"checks": checks, "raw_vs_trusted": impact, "warnings": n_warn, "freshness": fresh}
