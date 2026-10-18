"""Read-only SQL for the chatbot: one SELECT against `suppliers`, LIMIT ≤ 200, 2 s timeout.

Two layers: the statement is parsed and checked with sqlglot, and it runs on a private in-memory
DuckDB connection that holds only a copy of `suppliers`, with external file and network access off.
"""

from __future__ import annotations

import threading

import duckdb
import sqlglot
from sqlglot import exp

from .config import settings

ALLOWED_TABLE = "suppliers"
BLOCKED_FUNCTIONS = {
    "read_csv", "read_csv_auto", "read_parquet", "read_json", "read_json_auto", "read_ndjson", "read_text",
    "read_blob", "glob", "parquet_scan", "csv_scan", "sqlite_scan", "postgres_scan", "mysql_scan",
    "query", "query_table", "getenv", "current_setting", "duckdb_settings", "duckdb_tables",
    "duckdb_columns", "duckdb_databases", "duckdb_functions", "pragma_table_info", "range", "generate_series",
    "repeat", "read_xlsx", "iceberg_scan", "delta_scan", "load", "install",
}


class SQLRejected(ValueError):
    pass


def check(sql: str, limit: int | None = None) -> str:
    """Return the statement rewritten with an enforced LIMIT, or raise SQLRejected."""
    limit = limit or settings.sql_row_limit
    sql = (sql or "").strip()
    if not sql:
        raise SQLRejected("Empty query.")
    try:
        statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except sqlglot.errors.ParseError as exc:
        raise SQLRejected(f"Could not parse the query: {str(exc).splitlines()[0]}") from exc
    if len(statements) != 1:
        raise SQLRejected("Exactly one statement is allowed.")
    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise SQLRejected(f"Only SELECT is allowed, not {tree.key.upper()}.")
    for node in tree.walk():
        if isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Alter, exp.Command,
                             exp.Copy, exp.Pragma, exp.Set, exp.Attach, exp.Detach, exp.Use)):
            raise SQLRejected(f"{node.key.upper()} is not allowed.")
        if isinstance(node, exp.Into):
            raise SQLRejected("SELECT … INTO is not allowed.")
    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            raise SQLRejected("Table functions are not allowed; query the suppliers table.")
        name = table.name.lower()
        if table.args.get("db") or table.args.get("catalog"):
            raise SQLRejected("Only the suppliers table may be queried.")
        if name != ALLOWED_TABLE and name not in cte_names:
            raise SQLRejected(f"Only the suppliers table may be queried (found {table.name}).")
    for fn in tree.find_all(exp.Func):
        fname = (fn.name if isinstance(fn, exp.Anonymous) else fn.sql_name()).lower()
        if fname in BLOCKED_FUNCTIONS or fname.startswith(("duckdb_", "pragma_", "read_")):
            raise SQLRejected(f"Function {fname} is not allowed.")

    existing = tree.args.get("limit")
    if existing is not None:
        try:
            n = int(existing.expression.this) if existing.expression is not None else limit
        except (TypeError, ValueError):
            n = limit
        tree = tree.limit(min(n, limit), copy=True)
    else:
        tree = tree.limit(limit, copy=True)
    return tree.sql(dialect="duckdb")


class QueryEngine:
    """A private, sandboxed copy of one user's suppliers table."""

    def __init__(self, db_path: str):
        self.con = duckdb.connect(":memory:")
        # The path is server-generated (DATA_DIR/<validated user>/dataset.duckdb), never user text.
        literal = "'" + str(db_path).replace("'", "''") + "'"
        self.con.execute(f"ATTACH {literal} AS src (READ_ONLY)")
        self.con.execute("CREATE TABLE suppliers AS SELECT * FROM src.suppliers")
        self.con.execute("DETACH src")
        self.con.execute("SET enable_external_access = false")
        self.con.execute("SET lock_configuration = true")
        self.lock = threading.Lock()

    def run(self, sql: str) -> dict:
        safe = check(sql)
        with self.lock:
            cur = self.con.cursor()
            timer = threading.Timer(settings.sql_timeout_s, cur.interrupt)
            timer.start()
            try:
                cur.execute(safe)
                cols = [d[0] for d in cur.description]
                rows = cur.fetchall()
            except duckdb.InterruptException as exc:
                raise SQLRejected(f"Query took longer than {settings.sql_timeout_s:.0f} s and was stopped.") from exc
            except duckdb.Error as exc:
                raise SQLRejected(f"Query failed: {str(exc).splitlines()[0]}") from exc
            finally:
                timer.cancel()
                cur.close()
        return {"sql": safe, "columns": cols, "rows": [list(map(_plain, r)) for r in rows], "row_count": len(rows)}

    def schema(self) -> list[tuple[str, str]]:
        return [(r[0], r[1]) for r in self.con.execute("DESCRIBE suppliers").fetchall()]


def _plain(v):
    if isinstance(v, float):
        return round(v, 4)
    if isinstance(v, (int, str)) or v is None:
        return v
    return str(v)
