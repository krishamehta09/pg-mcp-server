"""
Database access layer with safety guardrails.

This module is the "production-grade" part of the project — it's what
separates a real MCP server from a thin wrapper around psycopg2. Every
query that reaches Postgres passes through validation here first.
"""

import os
import re
import time
import psycopg2
import psycopg2.extras
from contextlib import contextmanager
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

DATABASE_URL = os.environ["DATABASE_URL"]
ROW_LIMIT = int(os.environ.get("QUERY_ROW_LIMIT", 200))
QUERY_TIMEOUT_SECONDS = int(os.environ.get("QUERY_TIMEOUT_SECONDS", 5))

# Statements we never allow, regardless of who is asking or why.
# This is a blocklist on top of the fact that we also open the connection
# in read-only mode below — defense in depth, not just one check.
FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|GRANT|REVOKE|CREATE)\b",
    re.IGNORECASE,
)


class UnsafeQueryError(Exception):
    """Raised when a query fails validation before ever reaching Postgres."""
    pass


def validate_query(sql: str) -> None:
    """Reject anything that isn't a read-only SELECT/EXPLAIN.

    This runs BEFORE the query touches the database. It's intentionally
    strict (blocklist + shape check) rather than trying to be clever —
    a false rejection is annoying, a false approval is a real incident.
    """
    stripped = sql.strip().rstrip(";")

    if not stripped:
        raise UnsafeQueryError("Empty query is not allowed.")

    if FORBIDDEN_KEYWORDS.search(stripped):
        raise UnsafeQueryError(
            "Only read-only queries are allowed. Detected a write/DDL keyword."
        )

    if not re.match(r"^\s*(SELECT|EXPLAIN|WITH)\b", stripped, re.IGNORECASE):
        raise UnsafeQueryError(
            "Query must start with SELECT, WITH, or EXPLAIN."
        )

    # Block stacked queries (e.g. "SELECT 1; DROP TABLE users;")
    if ";" in stripped:
        raise UnsafeQueryError("Stacked/multiple statements are not allowed.")


@contextmanager
def get_connection():
    """Open a connection in read-only mode as a second line of defense.

    Even if validate_query() somehow missed something, the database
    session itself refuses to execute a write.
    """
    conn = psycopg2.connect(DATABASE_URL)
    try:
        conn.set_session(readonly=True, autocommit=True)
        yield conn
    finally:
        conn.close()


def run_safe_query(sql: str) -> dict:
    """Validate, execute with a timeout, and cap returned rows."""
    validate_query(sql)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"SET statement_timeout = {QUERY_TIMEOUT_SECONDS * 1000}")
            start = time.time()
            cur.execute(sql)
            elapsed = time.time() - start

            rows = cur.fetchmany(ROW_LIMIT)
            truncated = cur.rowcount > ROW_LIMIT if cur.rowcount != -1 else False

            return {
                "rows": rows,
                "row_count_returned": len(rows),
                "truncated": truncated,
                "elapsed_seconds": round(elapsed, 4),
            }


def list_schemas() -> list:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name NOT IN ('pg_catalog', 'information_schema') "
                "ORDER BY schema_name;"
            )
            return [r[0] for r in cur.fetchall()]


def list_tables(schema: str = "public") -> list:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = %s ORDER BY table_name;",
                (schema,),
            )
            return [r[0] for r in cur.fetchall()]


def explain_query(sql: str) -> dict:
    """Run EXPLAIN ANALYZE and flag if the query looks slow."""
    validate_query(sql)
    # Only allow EXPLAIN on SELECT/WITH bodies — never on arbitrary input.
    if re.match(r"^\s*EXPLAIN\b", sql.strip(), re.IGNORECASE):
        explain_sql = sql
    else:
        explain_sql = f"EXPLAIN (ANALYZE, FORMAT JSON) {sql}"

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SET statement_timeout = {QUERY_TIMEOUT_SECONDS * 1000}")
            cur.execute(explain_sql)
            plan = cur.fetchall()

    plan_text = str(plan)
    total_time_match = re.search(r"Actual Total Time[\"']?:\s*([\d.]+)", plan_text)
    total_time = float(total_time_match.group(1)) if total_time_match else None

    return {
        "plan": plan,
        "flagged_slow": bool(total_time and total_time > 100),  # >100ms
        "actual_total_time_ms": total_time,
    }


def get_table_stats(table: str, schema: str = "public") -> dict:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT relname AS table_name, n_live_tup AS estimated_row_count, "
                "seq_scan, idx_scan "
                "FROM pg_stat_user_tables "
                "WHERE schemaname = %s AND relname = %s;",
                (schema, table),
            )
            row = cur.fetchone()
            return dict(row) if row else {"error": f"Table {schema}.{table} not found"}
