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
                "Tables available: companies, financial_metrics (multi-period P&L data with metric_name: revenue/ebitda/ebitdax/gross_profit), "
                "company_kpis (operational KPIs), dcf_assumptions (valuation assumptions), "
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
    {
        "type": "function",
        "function": {
            "name": "fetch_market_comparables",
            "description": (
                "Fetch market comparable companies (public peers) for a portfolio company by sector. "
                "Retrieves the latest market data from Yahoo Finance for benchmarking. "
                "Returns sector peers with metrics like EV/EBITDA, revenue growth, margins."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "company_id": {"type": "integer", "description": "The portfolio company ID to find comparables for."},
                    "refresh": {"type": "boolean", "description": "Refresh data from Yahoo Finance (default: false).", "default": False}
                },
                "required": ["company_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_company_metrics_analysis",
            "description": (
                "Get comprehensive metrics and KPIs for a portfolio company with historical trends. "
                "Returns all financial metrics (revenue, EBITDA) across all periods, all operational KPIs, "
                "value creation analysis, and market peer comparisons for benchmarking."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "company_id": {"type": "integer", "description": "The portfolio company ID to analyze."}
                },
                "required": ["company_id"],
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

    elif tool_name == "fetch_market_comparables":
        from database import get_company_detail, get_company_comps
        company_id = tool_args.get("company_id")
        refresh = tool_args.get("refresh", False)

        print(f"\n  [Comps] Fetching market comparables for company {company_id}")

        # Get company details to find sector
        company_detail = get_company_detail(company_id)
        if not company_detail.get("success"):
            return json.dumps({"success": False, "error": f"Company {company_id} not found"})

        company_name = company_detail["company"].get("name", "Unknown")
        sector = company_detail["company"].get("sector", "")

        if not sector:
            return json.dumps({"success": False, "error": f"Company {company_name} has no sector specified"})

        # If refresh requested, fetch from Yahoo Finance
        if refresh:
            try:
                from fetch_comps import fetch_all_comps
                print(f"  [Comps] Refreshing data from Yahoo Finance for sector: {sector}")
                fetch_all_comps(refresh=True)
            except Exception as e:
                print(f"  [Comps] Warning: Could not refresh from Yahoo: {e}")

        # Get comparables by sector
        comps_result = get_company_comps(sector)

        if not comps_result.get("success"):
            return json.dumps({"success": False, "error": comps_result.get("error", "Failed to fetch comparables")})

        comps_list = comps_result.get("comps", [])
        print(f"  [Comps] Found {len(comps_list)} comparables in {sector} sector")

        return json.dumps({
            "success": True,
            "company_name": company_name,
            "sector": sector,
            "comparable_count": len(comps_list),
            "comparables": comps_list,
            "message": f"Found {len(comps_list)} public companies comparable to {company_name} in {sector} sector"
        })

    elif tool_name == "get_company_metrics_analysis":
        company_id = tool_args.get("company_id")
        print(f"\n  [Metrics] Analyzing metrics for company {company_id}")

        try:
            import requests
            from database import engine
            response = requests.get(f"http://localhost:5000/api/comps/{company_id}")
            if response.status_code != 200:
                return json.dumps({"success": False, "error": f"Failed to fetch company {company_id}"})

            data = response.json()
            if not data.get("success"):
                return json.dumps(data)

            # Extract key insights
            company_name = data.get("company_name")
            snapshot = data.get("current_snapshot", {})
            vc = data.get("value_creation", {})
            kpis = data.get("kpis", {})
            fin_metrics = data.get("financial_metrics", {})
            comps = data.get("comparables", [])

            insights = {
                "success": True,
                "company_name": company_name,
                "sector": data.get("sector"),
                "summary": {
                    "latest_revenue_mm": snapshot.get("revenue_mm"),
                    "ebitda_margin_pct": snapshot.get("ebitda_margin_pct"),
                    "periods_analyzed": len(fin_metrics.get("periods", [])),
                    "kpi_metrics_count": kpis.get("total_kpi_count"),
                    "kpi_names": kpis.get("all_kpi_names", [])
                },
                "value_creation": {
                    "entry_ev_mm": vc.get("entry_ev_mm"),
                    "current_ev_mm": vc.get("current_implied_ev"),
                    "value_created_mm": vc.get("value_created_mm"),
                    "value_created_pct": vc.get("value_created_pct"),
                    "gross_moic": vc.get("gross_moic"),
                    "entry_multiple": vc.get("entry_multiple"),
                    "current_multiple": vc.get("current_multiple")
                } if vc else None,
                "market_benchmark": {
                    "comparable_count": len(comps),
                    "top_comps": [{"name": c.get("name"), "ticker": c.get("ticker"),
                                  "ev_ebitda": c.get("ev_ebitda"), "ebitda_margin": c.get("ebitda_margin")}
                                 for c in comps[:5]]
                },
                "financial_metrics": {
                    "periods": fin_metrics.get("periods", []),
                    "metrics_by_period": fin_metrics.get("by_period", {})
                }
            }

            print(f"  [Metrics] Analyzed {len(fin_metrics.get('periods', []))} periods and {kpis.get('total_kpi_count')} KPI records")
            return json.dumps(insights)

        except Exception as e:
            return json.dumps({"success": False, "error": f"Analysis error: {str(e)}"})

    return json.dumps({"error": f"Unknown tool: {tool_name}"})
