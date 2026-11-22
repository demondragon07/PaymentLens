"""The single path to the database: guard, role scoping, execution and audit for every query."""
from __future__ import annotations

import itertools

import pandas as pd

from core.models import QueryRecord
from security import audit
from security.policy import apply_row_scope, restricted_columns
from sqlengine.executor import Executor, QueryFailed, QueryTimeout
from sqlengine.guard import validate_sql


class QueryBlocked(Exception):
    def __init__(self, record: QueryRecord):
        super().__init__("; ".join(c["detail"] for c in record.checks if not c["passed"]))
        self.record = record


class QueryError(Exception):
    def __init__(self, record: QueryRecord):
        super().__init__(record.error)
        self.record = record


class QueryService:
    def __init__(self, executor: Executor, role: str, mode: str = "guided", question: str = ""):
        self.ex = executor
        self.role = role
        self.mode = mode
        self.question = question
        self.records: list[QueryRecord] = []
        self._ids = itertools.count(1)

    def run(self, sql: str, purpose: str, max_rows: int | None = None) -> tuple[pd.DataFrame, QueryRecord]:
        qid = f"Q{next(self._ids)}"
        g = validate_sql(sql, restricted_columns=restricted_columns(self.role), schema_columns=self.ex.schema_columns)
        rec = QueryRecord(id=qid, purpose=purpose, sql=sql, executed_sql="", status="BLOCKED",
                          tables=g.tables, checks=g.checks)
        if not g.allowed:
            self._finish(rec, "BLOCKED", "; ".join(g.reasons))
            raise QueryBlocked(rec)
        executed = apply_row_scope(g.tree, self.role, original_sql=sql)
        if max_rows:
            executed = f"SELECT * FROM (\n{executed}\n) AS q LIMIT {int(max_rows) + 1}"
        rec.executed_sql = executed
        try:
            df, ms, hit = self.ex.execute(executed)
        except QueryTimeout as e:
            rec.error = str(e)
            self._finish(rec, "TIMEOUT", str(e))
            raise QueryError(rec) from e
        except QueryFailed as e:
            rec.error = str(e)
            self._finish(rec, "ERROR", str(e))
            raise QueryError(rec) from e
        rec.rows, rec.elapsed_ms, rec.cache_hit = len(df), round(ms, 2), hit
        self._finish(rec, "OK", "")
        return df, rec

    def _finish(self, rec: QueryRecord, status: str, reason: str) -> None:
        rec.status = status
        self.records.append(rec)
        audit.log_event(role=self.role, mode=self.mode, question=self.question, query_id=rec.id,
                        purpose=rec.purpose, decision=status, reason=reason, rows=rec.rows,
                        elapsed_ms=rec.elapsed_ms, cache_hit=rec.cache_hit, tables=rec.tables,
                        sql=rec.executed_sql or rec.sql)
