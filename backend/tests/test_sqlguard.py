import pytest

from app.sqlguard import QueryEngine, SQLRejected, check


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO suppliers (supplier_id) VALUES ('x')",
        "UPDATE suppliers SET total_risk_index = 0",
        "DELETE FROM suppliers",
        "DROP TABLE suppliers",
        "CREATE TABLE x AS SELECT * FROM suppliers",
        "SELECT 1; SELECT 2",
        "SELECT * FROM suppliers; DROP TABLE suppliers",
        "SELECT * FROM meta",
        "SELECT * FROM information_schema.tables",
        "SELECT s.* FROM suppliers s JOIN other_table o ON true",
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT * FROM '/etc/passwd'",
        "SELECT getenv('HOME')",
        "COPY suppliers TO '/tmp/out.csv'",
        "ATTACH '/tmp/x.db' AS x",
        "PRAGMA table_info('suppliers')",
        "SELECT * INTO new_table FROM suppliers",
        "",
    ],
)
def test_rejects(sql):
    with pytest.raises(SQLRejected):
        check(sql)


def test_limit_is_enforced():
    assert check("SELECT * FROM suppliers").endswith("LIMIT 200")
    assert check("SELECT * FROM suppliers LIMIT 5000").endswith("LIMIT 200")
    assert check("SELECT * FROM suppliers LIMIT 10").endswith("LIMIT 10")


def test_ctes_over_suppliers_are_allowed():
    check("WITH crit AS (SELECT * FROM suppliers WHERE total_risk_index >= 75) SELECT count(*) FROM crit")


def test_engine_runs_and_is_sandboxed(ds):
    eng = QueryEngine(str(ds.db_path))
    res = eng.run("SELECT count(*) AS n FROM suppliers WHERE total_risk_index >= 75")
    assert res["rows"] == [[384]]
    res = eng.run("SELECT supplier_id FROM suppliers")
    assert res["row_count"] == 200
    with pytest.raises(Exception):
        eng.con.execute("SELECT * FROM read_csv('/etc/hosts')").fetchall()
