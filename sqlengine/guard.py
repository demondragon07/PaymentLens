"""Validates SQL with sqlglot and blocks anything unsafe, restricted or too expensive."""
from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from core.config import ALLOWED_TABLES

_FORBIDDEN_NODE_NAMES = [
    "Insert", "Update", "Delete", "Drop", "Create", "Alter", "Command", "Copy", "Pragma", "Attach",
    "Detach", "Install", "Export", "LoadData", "TruncateTable", "Merge", "Set", "Use", "Transaction",
    "Commit", "Rollback", "Grant", "Revoke",
]
FORBIDDEN_NODES = tuple(getattr(exp, n) for n in _FORBIDDEN_NODE_NAMES if hasattr(exp, n))

FORBIDDEN_FUNCTIONS = {
    "read_csv", "read_csv_auto", "read_parquet", "parquet_scan", "read_json", "read_json_auto",
    "read_ndjson", "read_text", "read_blob", "glob", "sniff_csv", "getenv", "current_setting",
    "query", "query_table", "load", "install", "system", "shell",
}
FORBIDDEN_FUNCTION_PREFIXES = ("duckdb_", "pragma_", "pg_", "sqlite_", "postgres_", "mysql_")
MAX_JOINS = 4


@dataclass
class GuardResult:
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    tree: exp.Expression | None = None


def _check(res: GuardResult, name: str, ok: bool, detail: str) -> bool:
    res.checks.append({"check": name, "passed": ok, "detail": detail})
    if not ok:
        res.allowed = False
        res.reasons.append(detail)
    return ok


def _func_name(node: exp.Func) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.name).lower()
    return node.sql_name().lower()


def validate_sql(sql: str, *, restricted_columns: set[str], schema_columns: set[str]) -> GuardResult:
    res = GuardResult(allowed=True)
    try:
        statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except ParseError as e:
        _check(res, "parse", False, f"SQL could not be parsed: {str(e).splitlines()[0][:160]}")
        return res
    _check(res, "parse", True, "Parsed with sqlglot (duckdb dialect)")
    if not _check(res, "single_statement", len(statements) == 1,
                  f"Exactly one statement required (found {len(statements)})"):
        return res
    tree = statements[0]
    res.tree = tree

    root_ok = isinstance(tree, (exp.Select, exp.SetOperation))
    if not _check(res, "read_only_statement", root_ok,
                  "Only SELECT queries are allowed" if not root_ok else "Statement is a SELECT"):
        return res

    bad_nodes = sorted({type(n).__name__.upper() for n in tree.walk() if isinstance(n, FORBIDDEN_NODES)})
    _check(res, "no_forbidden_commands", not bad_nodes,
           f"Forbidden command(s): {', '.join(bad_nodes)}" if bad_nodes else "No DDL/DML/COPY/ATTACH/PRAGMA/INSTALL")

    bad_funcs = sorted({_func_name(f) for f in tree.find_all(exp.Func)
                        if _func_name(f) in FORBIDDEN_FUNCTIONS or _func_name(f).startswith(FORBIDDEN_FUNCTION_PREFIXES)})
    _check(res, "no_forbidden_functions", not bad_funcs,
           f"Forbidden function(s): {', '.join(bad_funcs)}" if bad_funcs else "No file/system/settings functions")

    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    tables, bad_tables, qualified = set(), set(), set()
    for t in tree.find_all(exp.Table):
        if not isinstance(t.this, exp.Identifier):
            bad_tables.add(t.sql()[:40])
            continue
        name = t.name.lower()
        if t.db or t.catalog:
            qualified.add(t.sql())
        if name in ctes:
            continue
        tables.add(name)
        if name not in ALLOWED_TABLES:
            bad_tables.add(name)
    res.tables = sorted(tables)
    _check(res, "allowed_tables", not bad_tables,
           f"Table(s) not allowed: {', '.join(sorted(bad_tables))}" if bad_tables
           else f"Tables allowed: {', '.join(res.tables) or '(none)'}")
    _check(res, "no_qualified_names", not qualified,
           f"Schema/catalog-qualified names not allowed: {', '.join(sorted(qualified))}" if qualified
           else "No schema/catalog qualifiers")

    aliases = {a.alias.lower() for a in tree.find_all(exp.Alias) if a.alias}
    for ta in tree.find_all(exp.TableAlias):
        aliases.update(c.name.lower() for c in ta.columns)
    known = schema_columns | aliases | ctes
    cols = {c.name.lower() for c in tree.find_all(exp.Column) if c.name and c.name != "*"}
    unknown = sorted(cols - known)
    _check(res, "known_columns", not unknown,
           f"Unknown column(s): {', '.join(unknown)}" if unknown else "All columns exist in the allowed schema")

    restricted_hit = sorted(cols & {c.lower() for c in restricted_columns})
    _check(res, "restricted_columns", not restricted_hit,
           f"Access denied to restricted column(s) for your role: {', '.join(restricted_hit)}" if restricted_hit
           else "No restricted columns referenced")

    star = any(not isinstance(s.parent, exp.Count) for s in tree.find_all(exp.Star))  # COUNT(*) is fine
    star_bad = star and bool(restricted_columns) and "merchants" in tables
    _check(res, "no_star_on_sensitive_table", not star_bad,
           "SELECT * on merchants is not allowed for your role (it would expose restricted columns); list columns explicitly"
           if star_bad else "No wildcard over sensitive tables")

    joins = list(tree.find_all(exp.Join))
    cartesian = [j for j in joins if not j.args.get("on") and not j.args.get("using")]
    _check(res, "join_conditions", not cartesian,
           "Join without ON/USING condition (cartesian product) is blocked for cost reasons" if cartesian
           else "Every join has a condition")
    _check(res, "join_count", len(joins) <= MAX_JOINS,
           f"Too many joins ({len(joins)} > {MAX_JOINS})" if len(joins) > MAX_JOINS else f"{len(joins)} join(s)")
    return res
