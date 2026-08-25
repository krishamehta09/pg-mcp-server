"""
Postgres MCP Server

Exposes a small, guarded set of read-only Postgres operations as MCP tools,
so any MCP client (Claude Desktop, Cursor, etc.) can safely inspect and
query a database on the user's behalf.

Design decisions (worth remembering for interviews):
- Read-only by default: no tool in this server can write, alter, or drop
  anything. The DB connection itself is opened in read-only mode as a
  second line of defense, in addition to query text validation.
- Row limits + timeouts: prevents a single query (from a user or a
  confused AI-generated query) from returning huge result sets or
  hanging the server.
- Audit log: every call is recorded before and after execution.
- Auth: the API key lives only in the server process's own environment
  (set via the MCP client's config, e.g. claude_desktop_config.json ->
  mcpServers -> env). It is never a tool parameter, so it never has to
  pass through the model's context or the chat transcript.
"""

import os
from dotenv import load_dotenv
from pathlib import Path
from mcp.server.fastmcp import FastMCP

from server import db
from server.audit import log_call

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

# The key must be present in the server process's environment. If it's
# missing, we fail loudly at startup rather than silently running unguarded.
API_KEY = os.environ.get("MCP_API_KEY")
if not API_KEY:
    raise RuntimeError(
        "MCP_API_KEY is not set in the environment. Set it in .env "
        "(local runs) or in the MCP client's server config (e.g. "
        "claude_desktop_config.json -> mcpServers -> env)."
    )

mcp = FastMCP("postgres-analytics-server")


@mcp.tool()
def list_schemas() -> dict:
    """List all non-system schemas in the connected database."""
    try:
        result = db.list_schemas()
        log_call("client", "list_schemas", {}, True)
        return {"schemas": result}
    except Exception as e:
        log_call("client", "list_schemas", {}, False, str(e))
        return {"error": str(e)}


@mcp.tool()
def list_tables(db_schema: str = "public") -> dict:
    """List all tables in the given schema (defaults to 'public')."""
    try:
        result = db.list_tables(db_schema)
        log_call("client", "list_tables", {"schema": db_schema}, True)
        return {"schema": db_schema, "tables": result}
    except Exception as e:
        log_call("client", "list_tables", {"schema": db_schema}, False, str(e))
        return {"error": str(e)}


@mcp.tool()
def run_query(sql: str) -> dict:
    """Run a read-only SQL query (SELECT/WITH only) and return up to
    QUERY_ROW_LIMIT rows. Write/DDL statements are rejected before
    execution."""
    try:
        result = db.run_safe_query(sql)
        log_call("client", "run_query", {"sql": sql}, True,
                  f"returned {result['row_count_returned']} rows")
        return result
    except Exception as e:
        log_call("client", "run_query", {"sql": sql}, False, str(e))
        return {"error": str(e)}


@mcp.tool()
def explain_query(sql: str) -> dict:
    """Return the query plan for a read-only query, and flag it if it
    looks slow (>100ms actual execution time)."""
    try:
        result = db.explain_query(sql)
        log_call("client", "explain_query", {"sql": sql}, True)
        return result
    except Exception as e:
        log_call("client", "explain_query", {"sql": sql}, False, str(e))
        return {"error": str(e)}


@mcp.tool()
def get_table_stats(table: str, db_schema: str = "public") -> dict:
    """Return row count estimate and scan stats for a table — useful for
    spotting tables that are missing indexes (high seq_scan, low idx_scan)."""
    try:
        result = db.get_table_stats(table, db_schema)
        log_call("client", "get_table_stats", {"table": table, "schema": db_schema}, True)
        return result
    except Exception as e:
        log_call("client", "get_table_stats", {"table": table, "schema": db_schema}, False, str(e))
        return {"error": str(e)}


if __name__ == "__main__":
    mcp.run()