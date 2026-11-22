"""Builds SQL from the metric and dimension definitions in config/metrics.yaml."""
from __future__ import annotations

from dataclasses import dataclass

from core.config import semantic
from core.models import Period


@dataclass
class CompiledQuery:
    purpose: str
    sql: str


def lit(value: str) -> str:
    """Turns a value into a safe SQL text value (escapes single quotes)."""
    return "'" + str(value).replace("'", "''") + "'"


def _ts_range(col: str, p: Period) -> str:
    return f"{col} >= TIMESTAMP '{p.start_ts}' AND {col} < TIMESTAMP '{p.end_ts_exclusive}'"


def _period_case(periods: list[Period], col: str) -> str:
    if len(periods) == 1:
        return f"'{periods[0].label}'"
    whens = " ".join(f"WHEN {_ts_range(col, p)} THEN '{p.label}'" for p in periods)
    return f"CASE {whens} END"


def _period_where(periods: list[Period], col: str) -> str:
    return "(" + " OR ".join(f"({_ts_range(col, p)})" for p in periods) + ")"


def _joins(names: list[str]) -> list[str]:
    sem = semantic()
    needed: list[str] = []
    for d in names:
        j = sem["dimensions"][d].get("join")
        if j and j not in needed:
            needed.append(j)
    return [sem["joins"][j] for j in needed]


def _filters(filters: dict[str, list[str]]) -> list[str]:
    sem = semantic()
    return [f"{sem['dimensions'][d]['sql']} IN ({', '.join(lit(v) for v in vals)})" for d, vals in filters.items()]


def compile_aggregate(*, purpose: str, source: str, periods: list[Period], dims: list[str],
                      filters: dict[str, list[str]], row_filter: str,
                      aggregates: list[tuple[str, str]]) -> CompiledQuery:
    sem = semantic()
    select = [f"{_period_case(periods, 't.created_at')} AS period"]
    select += [f"{sem['dimensions'][d]['sql']} AS {d}" for d in dims]
    select += [f"{expr} AS {alias}" for expr, alias in aggregates]
    where = [row_filter, _period_where(periods, "t.created_at"), *_filters(filters)]
    group = ", ".join(str(i) for i in range(1, len(dims) + 2))
    sql = ("SELECT\n    " + ",\n    ".join(select)
           + f"\nFROM {source} AS t\n"
           + "".join(j + "\n" for j in _joins(list(dims) + list(filters)))
           + "WHERE " + "\n  AND ".join(where)
           + f"\nGROUP BY {group}\nORDER BY {group}")
    return CompiledQuery(purpose, sql)


def _compile_order_grain(purpose: str, source: str, spec: dict, periods: list[Period], dims: list[str],
                         filters: dict[str, list[str]]) -> CompiledQuery:
    sem = semantic()
    inner = ["t.order_id", "MIN(t.created_at) AS first_attempt_at"]
    inner += [f"arg_min({sem['dimensions'][d]['sql']}, t.created_at) AS {d}" for d in dims]
    inner += ["MAX(CASE WHEN t.status = 'SUCCESS' THEN 1 ELSE 0 END) AS succeeded"]
    where = [spec["row_filter"], _period_where(periods, "t.created_at"), *_filters(filters)]
    outer = [f"{_period_case(periods, 'o.first_attempt_at')} AS period"]
    outer += [f"o.{d} AS {d}" for d in dims]
    outer += ["SUM(o.succeeded) AS numerator", "COUNT(*) AS denominator"]
    group = ", ".join(str(i) for i in range(1, len(dims) + 2))
    sql = ("WITH orders AS (\n  SELECT\n      " + ",\n      ".join(inner)
           + f"\n  FROM {source} AS t\n"
           + "".join("  " + j + "\n" for j in _joins(list(dims) + list(filters)))
           + "  WHERE " + "\n    AND ".join(where) + "\n  GROUP BY t.order_id\n)\n"
           + "SELECT\n    " + ",\n    ".join(outer)
           + "\nFROM orders AS o\nWHERE " + _period_where(periods, "o.first_attempt_at")
           + f"\nGROUP BY {group}\nORDER BY {group}")
    return CompiledQuery(purpose, sql)


def compile_metric(metric: str, *, purpose: str, source: str, periods: list[Period], dims: list[str],
                   filters: dict[str, list[str]]) -> CompiledQuery:
    spec = semantic()["metrics"][metric]
    if spec["kind"] == "ratio" and spec["grain"] == "order":
        return _compile_order_grain(purpose, source, spec, periods, dims, filters)
    if spec["kind"] == "ratio":
        aggs = [(spec["numerator_sql"], "numerator"), (spec["denominator_sql"], "denominator")]
    else:
        aggs = [(spec["value_sql"], "value")]
    return compile_aggregate(purpose=purpose, source=source, periods=periods, dims=dims, filters=filters,
                             row_filter=spec["row_filter"], aggregates=aggs)


def compile_decline_reasons(*, source: str, periods: list[Period], filters: dict[str, list[str]]) -> CompiledQuery:
    return compile_aggregate(purpose="Drill-down: failed attempts by decline reason", source=source,
                             periods=periods, dims=["decline_reason"], filters=filters,
                             row_filter="t.status = 'FAILED'", aggregates=[("COUNT(*)", "failures")])


def compile_reconciliation(period: Period) -> CompiledQuery:
    sql = f"""SELECT
    COUNT(*) AS successful_txns,
    ROUND(SUM(t.amount), 2) AS successful_amount,
    SUM(CASE WHEN s.settlement_status = 'SETTLED' THEN 1 ELSE 0 END) AS settled_txns,
    ROUND(SUM(CASE WHEN s.settlement_status = 'SETTLED' THEN s.gross_amount ELSE 0 END), 2) AS settled_gross_amount,
    SUM(CASE WHEN s.settlement_status = 'SETTLED' AND ABS(s.gross_amount - t.amount) > 0.01 THEN 1 ELSE 0 END) AS amount_mismatch_txns,
    ROUND(SUM(CASE WHEN s.settlement_status = 'SETTLED' THEN t.amount - s.gross_amount ELSE 0 END), 2) AS amount_mismatch_value,
    SUM(CASE WHEN s.settlement_status = 'PENDING' THEN 1 ELSE 0 END) AS pending_txns,
    ROUND(SUM(CASE WHEN s.settlement_status = 'PENDING' THEN t.amount ELSE 0 END), 2) AS pending_amount,
    SUM(CASE WHEN s.txn_id IS NULL THEN 1 ELSE 0 END) AS missing_settlement_txns,
    ROUND(SUM(CASE WHEN s.txn_id IS NULL THEN t.amount ELSE 0 END), 2) AS missing_settlement_amount
FROM transactions AS t
LEFT JOIN settlements AS s ON t.txn_id = s.txn_id
WHERE t.status = 'SUCCESS'
  AND {_ts_range('t.created_at', period)}"""
    return CompiledQuery("Reconciliation: successful transactions vs settlements", sql)


def compile_distinct_values() -> CompiledQuery:
    sql = """SELECT 'bank' AS dimension, bank_name AS value FROM banks
UNION ALL SELECT DISTINCT 'payment_method', payment_method FROM transactions
UNION ALL SELECT DISTINCT 'merchant_category', category FROM merchants
UNION ALL SELECT DISTINCT 'region', region FROM transactions
UNION ALL SELECT DISTINCT 'decline_reason', decline_reason FROM transactions WHERE decline_reason IS NOT NULL
UNION ALL SELECT DISTINCT 'merchant', merchant_id FROM merchants"""
    return CompiledQuery("Catalog: valid filter values", sql)
