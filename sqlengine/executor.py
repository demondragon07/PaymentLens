"""Runs SQL on a read-only DuckDB connection with a timeout and a result cache."""
from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path

import duckdb
import pandas as pd

from core.config import ALLOWED_TABLES, DB_PATH, limits


class QueryTimeout(Exception):
    pass


class QueryFailed(Exception):
    pass


class Executor:
    def __init__(self, db_path: Path = DB_PATH, timeout_s: float | None = None):
        if not Path(db_path).exists():
            raise FileNotFoundError(f"Database not found at {db_path}. Run: python data/generate_data.py")
        self.con = duckdb.connect(str(db_path), read_only=True)
        # extra safety: block file and network access, and lock it so it can't be turned back on
        self.con.execute("SET enable_external_access = false")
        self.con.execute("SET lock_configuration = true")
        self.timeout_s = timeout_s or float(limits()["query_timeout_seconds"])
        self._lock = threading.Lock()
        self._cache: dict[str, pd.DataFrame] = {}
        meta = dict(self.con.execute("SELECT key, value FROM meta").fetchall())
        self.data_version = meta.get("data_version", "unknown")
        self.data_as_of = meta.get("data_as_of")
        self.schema: dict[str, list[str]] = {}
        for t in sorted(ALLOWED_TABLES):
            self.schema[t] = [r[0] for r in self.con.execute(f"DESCRIBE {t}").fetchall()]

    @property
    def schema_columns(self) -> set[str]:
        return {c.lower() for cols in self.schema.values() for c in cols}

    def cache_key(self, sql: str) -> str:
        return hashlib.sha256(f"{self.data_version}\n{sql}".encode()).hexdigest()

    def execute(self, sql: str, use_cache: bool = True) -> tuple[pd.DataFrame, float, bool]:
        key = self.cache_key(sql)
        if use_cache and key in self._cache:
            return self._cache[key].copy(), 0.0, True
        with self._lock:
            timer = threading.Timer(self.timeout_s, self.con.interrupt)
            t0 = time.perf_counter()
            timer.start()
            try:
                df = self.con.execute(sql).df()
            except Exception as e:  # DuckDB can raise different error types
                if "interrupt" in str(e).lower():
                    raise QueryTimeout(f"Query exceeded {self.timeout_s:.0f}s timeout and was cancelled") from e
                raise QueryFailed(str(e).splitlines()[0][:300]) from e
            finally:
                timer.cancel()
            elapsed = (time.perf_counter() - t0) * 1000
        if use_cache:
            self._cache[key] = df.copy()
        return df, elapsed, False

    def clear_cache(self) -> None:
        self._cache.clear()
