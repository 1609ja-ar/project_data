"""Validation of user SQL for the SQL Workbench (layer 1 and 2 of the hardening; see README Security).

Accepts exactly one statement whose root is a SELECT (CTEs, UNION, joins, window functions and
subqueries are fine). Every table reference must be a registered name or a CTE alias; table
functions, file/URL access, catalogs and schema-qualified names are rejected.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

MAX_SQL_CHARS = 20_000
DENY_FUNC_RE = re.compile(
    r"^(read_\w+|\w+_scan|scan_\w+|glob|query|query_table|sniff_csv|getenv|current_setting|duckdb_\w+|pragma_\w+|"
    r"load|install|attach|detach|checkpoint|export_database|import_database|sqlite_\w+|postgres_\w+|mysql_\w+|"
    r"iceberg_\w+|delta_\w+|http\w*|s3\w*|parquet_\w+|which_secret|load_\w+|test_\w+|enable_\w+|disable_\w+)$",
    re.IGNORECASE)
DENY_NODES = (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Alter, exp.Command, exp.Pragma, exp.Set,
              exp.Copy, exp.Use, exp.Transaction, exp.Commit, exp.Rollback, exp.Merge, exp.Describe, exp.Into)
for _name in ("Attach", "Detach", "Install", "Load", "Summarize", "Export", "Import"):
    if hasattr(exp, _name):
        DENY_NODES = DENY_NODES + (getattr(exp, _name),)


@dataclass
class SqlCheck:
    ok: bool
    message: str = ""
    line: int | None = None
    col: int | None = None
    tables: list[str] = field(default_factory=list)


def _fail(message: str, line=None, col=None) -> SqlCheck:
    return SqlCheck(False, message, line, col)


def validate_sql(sql: str, allowed_tables: set[str]) -> SqlCheck:
    if not sql or not sql.strip():
        return _fail("Write a SELECT query.")
    if len(sql) > MAX_SQL_CHARS:
        return _fail(f"Queries are limited to {MAX_SQL_CHARS:,} characters.")
    try:
        statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except ParseError as e:
        err = (e.errors or [{}])[0]
        msg = str(err.get("description") or "The query could not be parsed")
        return _fail(f"Syntax error: {msg}", err.get("line"), err.get("col"))
    except TokenError as e:
        return _fail(f"Syntax error: {e}")
    if len(statements) != 1:
        return _fail("Run one statement at a time (no semicolon-separated statements).")
    root = statements[0]
    if not isinstance(root, (exp.Select, exp.SetOperation, exp.Subquery)):
        return _fail(f"Only SELECT queries are allowed (got {root.key.upper()}). The workbench is read-only.")
    for node in root.walk():
        if isinstance(node, DENY_NODES):
            return _fail(f"{node.key.upper()} is not allowed. The workbench is read-only.")
        if isinstance(node, exp.Func):
            fname = node.name if isinstance(node, exp.Anonymous) else (node.sql_name() if hasattr(node, "sql_name") else node.key)
            if type(node).__name__.startswith("Read") or DENY_FUNC_RE.match(str(fname)):
                return _fail(f"The function {str(fname).lower()}() is not allowed (no file, network, system or settings access).")

    cte_names = {cte.alias_or_name.lower() for cte in root.find_all(exp.CTE)}
    used: list[str] = []
    for t in root.find_all(exp.Table):
        if not isinstance(t.this, exp.Identifier):
            return _fail("Table functions are not allowed. Query the tables listed in the schema browser.")
        if t.args.get("db") or t.args.get("catalog"):
            return _fail(f"Use the table name only (got {t.sql(dialect='duckdb')}). System catalogs are not available.")
        name = t.name.lower()
        if name in cte_names:
            continue
        if name not in allowed_tables:
            return _fail(f"Unknown table '{t.name}'. Available tables: {', '.join(sorted(allowed_tables))}.")
        if name not in used:
            used.append(name)
    return SqlCheck(True, "Query is valid.", tables=used)


def wrap_with_limit(sql: str, max_rows: int) -> str:
    """The exact SQL that runs: the validated query wrapped with a row cap (+1 row to detect truncation)."""
    body = sql.strip().rstrip(";").strip()
    return f"SELECT * FROM (\n{body}\n) AS q LIMIT {int(max_rows) + 1}"
