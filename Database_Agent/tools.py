"""
tools.py — Tool definitions using OpenAI-compatible JSON schema.
LiteLLM translates these for Claude, Gemini, GPT automatically.
"""

import json
from database import execute_query, get_schema

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "execute_sql_query",
            "description": (
                "Execute a read-only SQL SELECT query against the portfolio database. "
                "Tables available: companies, quarterly_financials, kpis, "
                "market_comps (public peer data), comp_price_history (5yr monthly prices), "
                "comp_quarterly_metrics (quarterly financials for public comps). "
                "Only SELECT statements are permitted."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "A valid SQL SELECT statement."},
                    "rationale": {"type": "string", "description": "Why you are running this query."},
                },
                "required": ["sql", "rationale"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_database_schema",
            "description": "Return all table names and columns. Call this first when unsure what's available.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_results",
            "description": "Format query results into a structured Markdown analysis for the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "findings": {"type": "string", "description": "Structured analysis in Markdown."},
                    "data_quality_notes": {"type": "string", "description": "Caveats about missing or null data."},
                },
                "required": ["findings"],
            },
        },
    },
]


def execute_tool(tool_name: str, tool_args: dict) -> str:
    if tool_name == "execute_sql_query":
        sql = tool_args.get("sql", "")
        rationale = tool_args.get("rationale", "")
        print(f"\n  [DB] {rationale}")
        print(f"  [SQL] {sql[:120]}{'...' if len(sql)>120 else ''}")
        result = execute_query(sql)
        if result["success"]:
            print(f"  [rows] {result['row_count']} returned")
        else:
            print(f"  [error] {result['error']}")
        return json.dumps(result)

    elif tool_name == "get_database_schema":
        print("\n  [schema] Fetching schema")
        return json.dumps(get_schema())

    elif tool_name == "summarize_results":
        findings = tool_args.get("findings", "")
        notes    = tool_args.get("data_quality_notes", "")
        return findings + (f"\n\n**Data Quality Notes:** {notes}" if notes else "")

    return json.dumps({"error": f"Unknown tool: {tool_name}"})
