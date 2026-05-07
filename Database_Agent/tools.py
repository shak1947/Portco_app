"""
tools.py — Tool definitions using OpenAI-compatible JSON schema.
LiteLLM translates these for Claude, Gemini, GPT automatically.
"""

import json
import os
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
    {
        "type": "function",
        "function": {
            "name": "calculate_value_creation",
            "description": (
                "Calculate the value creation bridge for a company from entry to current. "
                "Decomposes value into EBITDA Growth, Multiple Expansion, and Debt Paydown."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "company_id": {"type": "integer", "description": "The ID of the portfolio company."},
                },
                "required": ["company_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_meeting_intelligence",
            "description": (
                "Search through processed meeting summaries for specific companies, decisions, or action items. "
                "Use this to find qualitative context for financial trends."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keyword or company name to search for."}
                },
                "required": ["query"],
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

    elif tool_name == "calculate_value_creation":
        from database import get_value_creation
        company_id = tool_args.get("company_id")
        print(f"\n  [Analysis] Calculating Value Creation for ID: {company_id}")
        result = get_value_creation(company_id)
        return json.dumps(result)

    elif tool_name == "search_meeting_intelligence":
        query = tool_args.get("query", "").lower()
        # Summaries are stored in c:\AI\summaries relative to this project structure
        summaries_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "summaries"))
        
        results = []
        if os.path.exists(summaries_dir):
            for filename in os.listdir(summaries_dir):
                if filename.endswith(".md"):
                    path = os.path.join(summaries_dir, filename)
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read()
                        if query in content.lower() or query in filename.lower():
                            results.append(f"### Source: {filename}\n{content}")
        
        return "\n\n".join(results) if results else f"No meeting intelligence found for '{query}'."

    return json.dumps({"error": f"Unknown tool: {tool_name}"})
