"""Tests that unsafe and restricted SQL is blocked and role scoping works."""
import pytest

from sqlengine.service import QueryBlocked, QueryService

MALICIOUS = [
    "DROP TABLE transactions",
    "DELETE FROM banks",
    "UPDATE banks SET bank_name = 'x'",
    "INSERT INTO banks VALUES ('B9','x','y')",
    "CREATE TABLE x AS SELECT 1",
    "SELECT 1; DELETE FROM banks",
    "COPY banks TO 'out.csv'",
    "ATTACH 'other.db'",
    "INSTALL httpfs",
    "PRAGMA database_list",
    "SELECT * FROM read_csv('C:/secrets.csv')",
    "SELECT getenv('OPENAI_API_KEY')",
    "SELECT * FROM duckdb_settings()",
    "SELECT * FROM meta",
    "SELECT * FROM main.transactions",
    "SELECT t.txn_id FROM transactions t, banks b",
    "SELECT nonexistent_col FROM transactions",
]


@pytest.mark.parametrize("sql", MALICIOUS)
def test_malicious_sql_blocked(pl, sql):
    svc = QueryService(pl.ex, "admin", mode="test")
    with pytest.raises(QueryBlocked):
        svc.run(sql, "test")
    assert svc.records[-1].status == "BLOCKED"


def test_safe_join_allowed(pl):
    svc = QueryService(pl.ex, "business_analyst", mode="test")
    df, rec = svc.run("SELECT b.bank_name, COUNT(*) AS n FROM transactions t JOIN banks b ON t.bank_id = b.bank_id GROUP BY 1", "t")
    assert rec.status == "OK" and len(df) == 4


@pytest.mark.parametrize("sql", ["SELECT merchant_id, settlement_account FROM merchants",
                                 "SELECT contact_email FROM merchants",
                                 "SELECT * FROM merchants"])
def test_restricted_columns_blocked_for_analyst(pl, sql):
    with pytest.raises(QueryBlocked):
        QueryService(pl.ex, "business_analyst", mode="test").run(sql, "t")


def test_restricted_columns_allowed_for_admin(pl):
    df, rec = QueryService(pl.ex, "admin", mode="test").run("SELECT merchant_id, settlement_account FROM merchants", "t")
    assert len(df) == 100


def test_row_scope_rewrite_limits_regional_analyst(pl):
    sql = "SELECT region, COUNT(*) AS n FROM transactions GROUP BY 1"
    admin, _ = QueryService(pl.ex, "admin", mode="test").run(sql, "t")
    north, rec = QueryService(pl.ex, "regional_analyst_north", mode="test").run(sql, "t")
    assert set(admin.region) == {"North", "South", "West"}
    assert set(north.region) == {"North"}
    assert int(north.n.iloc[0]) == int(admin[admin.region == "North"].n.iloc[0])
    assert "region = 'North'" in rec.executed_sql


def test_row_scope_applies_to_settlements(pl):
    sql = "SELECT COUNT(*) AS n FROM settlements"
    admin, _ = QueryService(pl.ex, "admin", mode="test").run(sql, "t")
    north, _ = QueryService(pl.ex, "regional_analyst_north", mode="test").run(sql, "t")
    assert 0 < int(north.n.iloc[0]) < int(admin.n.iloc[0])


def test_engine_is_read_only_even_without_guard(pl):
    """Extra safety: even without the guard, the database itself refuses writes and file access."""
    for sql in ["CREATE TABLE z AS SELECT 1", "SELECT * FROM read_csv('x.csv')"]:
        with pytest.raises(Exception):
            pl.ex.con.execute(sql)
