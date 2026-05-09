"""
database.py — SQLAlchemy connection layer.
Handles portfolio company tables AND public market comp tables.
"""

import os
import json
from datetime import datetime, date, time
from decimal import Decimal
from sqlalchemy import create_engine, text, inspect, MetaData, Table, Column, UniqueConstraint
from sqlalchemy import Integer, String, Float, BigInteger
from sqlalchemy.exc import SQLAlchemyError
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///portfolio.db")
connect_args = {"sslmode": "require"} if any(x in DATABASE_URL for x in ["supabase","neon","sslmode"]) else {}
engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)


def serialize_value(value):
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", "ignore")
    if isinstance(value, Decimal):
        return float(value)
    return value


def execute_query(sql: str, limit: int = 500) -> dict:
    sql = sql.strip()
    first_word = sql.split()[0].upper() if sql.split() else ""
    if first_word not in ("SELECT", "WITH", "EXPLAIN"):
        return {"success": False, "error": f"Only SELECT queries allowed. Got: {first_word}",
                "columns": [], "rows": [], "row_count": 0}
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql))
            columns = list(result.keys())
            rows = []
            for row in result:
                rows.append([serialize_value(value) for value in row])
                if len(rows) >= limit:
                    break
            truncated = result.rowcount is not None and result.rowcount > limit
            return {"success": True, "columns": columns, "rows": rows,
                    "row_count": len(rows), "truncated": truncated, "error": None}
    except SQLAlchemyError as e:
        return {"success": False, "error": str(e), "columns": [], "rows": [], "row_count": 0}


def get_schema() -> dict:
    try:
        inspector = inspect(engine)
        schema = {}
        for table_name in inspector.get_table_names():
            cols = inspector.get_columns(table_name)
            schema[table_name] = [{"name": c["name"], "type": str(c["type"])} for c in cols]
        return {"success": True, "schema": schema}
    except Exception as e:
        return {"success": False, "error": str(e), "schema": {}}


def create_all_tables():
    metadata = MetaData()
    Table("companies", metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(100)), Column("sector", String(50)),
        Column("entry_year", Integer), Column("entry_ev_mm", Float),
        Column("ownership_pct", Float))
    Table("financial_metrics", metadata,
        Column("id", Integer, primary_key=True), Column("company_id", Integer),
        Column("period", String(20)), Column("metric_name", String(50)),
        Column("raw_label", String(200)), Column("value", Float),
        Column("unit", String(20)), Column("period_type", String(20)),
        Column("source_file", String(100)),
        UniqueConstraint("company_id", "period", "metric_name"))
    Table("company_kpis", metadata,
        Column("id", Integer, primary_key=True), Column("company_id", Integer),
        Column("period", String(20)), Column("kpi_name", String(100)),
        Column("kpi_value", Float), Column("kpi_unit", String(20)),
        Column("source_file", String(100)),
        UniqueConstraint("company_id", "period", "kpi_name"))
    Table("dcf_assumptions", metadata,
        Column("id", Integer, primary_key=True), Column("company_id", Integer),
        Column("assumption_name", String(50)), Column("raw_label", String(200)),
        Column("value", Float), Column("source_file", String(100)),
        UniqueConstraint("company_id", "assumption_name"))
    Table("quarterly_financials", metadata,
        Column("id", Integer, primary_key=True), Column("company_id", Integer),
        Column("period", String(10)), Column("revenue_mm", Float),
        Column("ebitda_mm", Float), Column("ebitda_margin", Float),
        Column("yoy_growth", Float))
    Table("kpis", metadata,
        Column("id", Integer, primary_key=True), Column("company_id", Integer),
        Column("period", String(10)), Column("kpi_name", String(100)),
        Column("kpi_value", Float), Column("kpi_unit", String(20)))
    Table("market_comps", metadata,
        Column("id", Integer, primary_key=True),
        Column("ticker", String(20)), Column("name", String(200)),
        Column("sector_key", String(50)), Column("market_cap_mm", Float),
        Column("ev_ebitda", Float), Column("ev_revenue", Float),
        Column("revenue_growth", Float), Column("ebitda_margin", Float),
        Column("gross_margin", Float), Column("last_updated", String(30)))
    Table("comp_price_history", metadata,
        Column("id", Integer, primary_key=True),
        Column("ticker", String(20)), Column("date", String(20)),
        Column("close", Float), Column("volume", BigInteger),
        Column("adj_close", Float))
    Table("comp_quarterly_metrics", metadata,
        Column("id", Integer, primary_key=True),
        Column("ticker", String(20)), Column("period", String(10)),
        Column("revenue_mm", Float), Column("gross_margin", Float),
        Column("ebitda_margin", Float), Column("fetched_date", String(30)))
    Table("investment_thesis", metadata,
        Column("id", Integer, primary_key=True),
        Column("company_id", Integer),
        Column("hypothesis", String),
        Column("key_assumptions", String),
        Column("target_exit_year", Integer),
        Column("target_revenue_mm", Float),
        Column("target_ebitda_margin", Float),
        Column("target_exit_multiple", Float),
        Column("status", String(20)),
        Column("created_date", String(30)),
        Column("updated_date", String(30)))
    Table("thesis_milestones", metadata,
        Column("id", Integer, primary_key=True),
        Column("thesis_id", Integer),
        Column("milestone_text", String),
        Column("target_date", String(20)),
        Column("achieved", Integer))
    Table("investment_notes", metadata,
        Column("id", Integer, primary_key=True),
        Column("company_id", Integer),
        Column("note_key", String(200)),
        Column("note_value", String),
        Column("source", String(100)),
        Column("created_date", String(30)))
    metadata.create_all(engine, checkfirst=True)


def upsert_company(name: str, sector: str, entry_year: int, entry_ev_mm: float, ownership_pct: float) -> dict:
    try:
        with engine.begin() as conn:
            existing = conn.execute(text("SELECT id FROM companies WHERE name = :name"),
                                   {"name": name}).scalar()
            if existing:
                conn.execute(text("UPDATE companies SET sector=:sector, entry_year=:entry_year, "
                                 "entry_ev_mm=:entry_ev_mm, ownership_pct=:ownership_pct WHERE id=:id"),
                            {"sector": sector, "entry_year": entry_year, "entry_ev_mm": entry_ev_mm,
                             "ownership_pct": ownership_pct, "id": existing})
                return {"success": True, "company_id": existing, "action": "updated"}
            else:
                result = conn.execute(text("INSERT INTO companies(name, sector, entry_year, entry_ev_mm, ownership_pct) "
                                          "VALUES(:name, :sector, :entry_year, :entry_ev_mm, :ownership_pct) "
                                          "RETURNING id"),
                                     {"name": name, "sector": sector, "entry_year": entry_year,
                                      "entry_ev_mm": entry_ev_mm, "ownership_pct": ownership_pct})
                company_id = result.scalar()
                return {"success": True, "company_id": company_id, "action": "created"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def upsert_financials(company_id: int, period: str, revenue_mm: float, ebitda_mm: float,
                     ebitda_margin: float, yoy_growth: float = None) -> dict:
    try:
        with engine.begin() as conn:
            existing = conn.execute(text("SELECT id FROM quarterly_financials WHERE company_id = :company_id AND period = :period"),
                                   {"company_id": company_id, "period": period}).scalar()
            if existing:
                conn.execute(text("UPDATE quarterly_financials SET revenue_mm=:revenue_mm, ebitda_mm=:ebitda_mm, "
                                 "ebitda_margin=:ebitda_margin, yoy_growth=:yoy_growth WHERE id=:id"),
                            {"revenue_mm": revenue_mm, "ebitda_mm": ebitda_mm, "ebitda_margin": ebitda_margin,
                             "yoy_growth": yoy_growth, "id": existing})
                return {"success": True, "financial_id": existing, "action": "updated"}
            else:
                result = conn.execute(text("INSERT INTO quarterly_financials(company_id, period, revenue_mm, ebitda_mm, ebitda_margin, yoy_growth) "
                                          "VALUES(:company_id, :period, :revenue_mm, :ebitda_mm, :ebitda_margin, :yoy_growth) "
                                          "RETURNING id"),
                                     {"company_id": company_id, "period": period, "revenue_mm": revenue_mm,
                                      "ebitda_mm": ebitda_mm, "ebitda_margin": ebitda_margin, "yoy_growth": yoy_growth})
                financial_id = result.scalar()
                return {"success": True, "financial_id": financial_id, "action": "created"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def upsert_financial_metric(company_id: int, period: str, metric_name: str, value: float,
                           unit: str = "mm_usd", period_type: str = None, raw_label: str = None,
                           source_file: str = None) -> dict:
    try:
        with engine.begin() as conn:
            existing = conn.execute(text("SELECT id FROM financial_metrics WHERE company_id = :company_id AND period = :period AND metric_name = :metric_name"),
                                   {"company_id": company_id, "period": period, "metric_name": metric_name}).scalar()
            if existing:
                conn.execute(text("UPDATE financial_metrics SET value=:value, unit=:unit, period_type=:period_type, raw_label=:raw_label, source_file=:source_file WHERE id=:id"),
                            {"value": value, "unit": unit, "period_type": period_type, "raw_label": raw_label, "source_file": source_file, "id": existing})
                return {"success": True, "metric_id": existing, "action": "updated"}
            else:
                result = conn.execute(text("INSERT INTO financial_metrics(company_id, period, metric_name, value, unit, period_type, raw_label, source_file) "
                                          "VALUES(:company_id, :period, :metric_name, :value, :unit, :period_type, :raw_label, :source_file) "
                                          "RETURNING id"),
                                     {"company_id": company_id, "period": period, "metric_name": metric_name,
                                      "value": value, "unit": unit, "period_type": period_type,
                                      "raw_label": raw_label, "source_file": source_file})
                metric_id = result.scalar()
                return {"success": True, "metric_id": metric_id, "action": "created"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def upsert_company_kpi(company_id: int, period: str, kpi_name: str, kpi_value: float, kpi_unit: str = None,
                      source_file: str = None) -> dict:
    try:
        with engine.begin() as conn:
            existing = conn.execute(text("SELECT id FROM company_kpis WHERE company_id = :company_id AND period = :period AND kpi_name = :kpi_name"),
                                   {"company_id": company_id, "period": period, "kpi_name": kpi_name}).scalar()
            if existing:
                conn.execute(text("UPDATE company_kpis SET kpi_value=:kpi_value, kpi_unit=:kpi_unit, source_file=:source_file WHERE id=:id"),
                            {"kpi_value": kpi_value, "kpi_unit": kpi_unit, "source_file": source_file, "id": existing})
                return {"success": True, "kpi_id": existing, "action": "updated"}
            else:
                result = conn.execute(text("INSERT INTO company_kpis(company_id, period, kpi_name, kpi_value, kpi_unit, source_file) "
                                          "VALUES(:company_id, :period, :kpi_name, :kpi_value, :kpi_unit, :source_file) "
                                          "RETURNING id"),
                                     {"company_id": company_id, "period": period, "kpi_name": kpi_name,
                                      "kpi_value": kpi_value, "kpi_unit": kpi_unit, "source_file": source_file})
                kpi_id = result.scalar()
                return {"success": True, "kpi_id": kpi_id, "action": "created"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def upsert_dcf_assumption(company_id: int, assumption_name: str, value: float,
                         raw_label: str = None, source_file: str = None) -> dict:
    try:
        with engine.begin() as conn:
            existing = conn.execute(text("SELECT id FROM dcf_assumptions WHERE company_id = :company_id AND assumption_name = :assumption_name"),
                                   {"company_id": company_id, "assumption_name": assumption_name}).scalar()
            if existing:
                conn.execute(text("UPDATE dcf_assumptions SET value=:value, raw_label=:raw_label, source_file=:source_file WHERE id=:id"),
                            {"value": value, "raw_label": raw_label, "source_file": source_file, "id": existing})
                return {"success": True, "assumption_id": existing, "action": "updated"}
            else:
                result = conn.execute(text("INSERT INTO dcf_assumptions(company_id, assumption_name, value, raw_label, source_file) "
                                          "VALUES(:company_id, :assumption_name, :value, :raw_label, :source_file) "
                                          "RETURNING id"),
                                     {"company_id": company_id, "assumption_name": assumption_name,
                                      "value": value, "raw_label": raw_label, "source_file": source_file})
                assumption_id = result.scalar()
                return {"success": True, "assumption_id": assumption_id, "action": "created"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def upsert_kpi(company_id: int, period: str, kpi_name: str, kpi_value: float, kpi_unit: str) -> dict:
    try:
        with engine.begin() as conn:
            existing = conn.execute(text("SELECT id FROM kpis WHERE company_id = :company_id AND period = :period AND kpi_name = :kpi_name"),
                                   {"company_id": company_id, "period": period, "kpi_name": kpi_name}).scalar()
            if existing:
                conn.execute(text("UPDATE kpis SET kpi_value=:kpi_value, kpi_unit=:kpi_unit WHERE id=:id"),
                            {"kpi_value": kpi_value, "kpi_unit": kpi_unit, "id": existing})
                return {"success": True, "kpi_id": existing, "action": "updated"}
            else:
                result = conn.execute(text("INSERT INTO kpis(company_id, period, kpi_name, kpi_value, kpi_unit) "
                                          "VALUES(:company_id, :period, :kpi_name, :kpi_value, :kpi_unit) "
                                          "RETURNING id"),
                                     {"company_id": company_id, "period": period, "kpi_name": kpi_name,
                                      "kpi_value": kpi_value, "kpi_unit": kpi_unit})
                kpi_id = result.scalar()
                return {"success": True, "kpi_id": kpi_id, "action": "created"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_company_detail(company_id: int) -> dict:
    try:
        with engine.connect() as conn:
            company = conn.execute(text("SELECT id, name, sector, entry_year, entry_ev_mm, ownership_pct FROM companies WHERE id = :id"),
                                  {"id": company_id}).mappings().first()
            if not company:
                return {"success": False, "error": f"Company {company_id} not found"}

            financials = conn.execute(text("SELECT period, metric_name, value, unit, period_type, raw_label FROM financial_metrics WHERE company_id = :id ORDER BY period, metric_name"),
                                     {"id": company_id}).mappings().all()

            kpis = conn.execute(text("SELECT period, kpi_name, kpi_value, kpi_unit FROM company_kpis WHERE company_id = :id ORDER BY period, kpi_name"),
                               {"id": company_id}).mappings().all()

            notes = conn.execute(text("SELECT id, note_key, note_value, source, created_date FROM investment_notes WHERE company_id = :id ORDER BY created_date DESC"),
                                {"id": company_id}).mappings().all()

            dcf = conn.execute(text("SELECT assumption_name, value FROM dcf_assumptions WHERE company_id = :id ORDER BY assumption_name"),
                              {"id": company_id}).mappings().all()

            return {
                "success": True,
                "company": dict(company),
                "financials": [dict(f) for f in financials],
                "kpis": [dict(k) for k in kpis],
                "notes": [dict(n) for n in notes],
                "dcf_assumptions": [dict(d) for d in dcf]
            }
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_company_comps(sector: str) -> dict:
    try:
        # Map portfolio sectors to market sectors
        sector_map = {
            "healthcare": ["healthcare_svc", "medtech"],
            "technology": ["saas"],
            "energy": ["energy_svc"],
            "food & beverage": ["food_bev"],
            "consumer": ["consumer"],
            "retail": ["retail"],
            "construction": ["construction"],
            "industrial": ["industrial"],
            "logistics": ["logistics"],
        }

        # Get market sectors to search (use provided sector or map it)
        market_sectors = sector_map.get(sector.lower(), [sector.lower()])

        with engine.connect() as conn:
            comps = conn.execute(
                text("SELECT ticker, name, sector_key, market_cap_mm, ev_ebitda, revenue_growth, ebitda_margin, gross_margin "
                     "FROM market_comps WHERE sector_key IN ({}) ORDER BY market_cap_mm DESC NULLS LAST".format(
                         ",".join(["'" + s + "'" for s in market_sectors])
                     ))
            ).mappings().all()

            if not comps:
                return {"success": True, "comps": []}

            return {
                "success": True,
                "comps": [dict(c) for c in comps],
                "sector": sector,
                "market_sectors": market_sectors,
                "count": len(comps)
            }
    except Exception as e:
        return {"success": False, "error": str(e)}


def upsert_thesis(company_id: int, hypothesis: str, key_assumptions: str, target_exit_year: int,
                 target_revenue_mm: float, target_ebitda_margin: float, target_exit_multiple: float,
                 status: str) -> dict:
    try:
        from datetime import datetime
        now = datetime.utcnow().isoformat()
        with engine.begin() as conn:
            existing = conn.execute(text("SELECT id FROM investment_thesis WHERE company_id = :company_id"),
                                   {"company_id": company_id}).scalar()
            if existing:
                conn.execute(text("UPDATE investment_thesis SET hypothesis=:hypothesis, key_assumptions=:key_assumptions, "
                                 "target_exit_year=:target_exit_year, target_revenue_mm=:target_revenue_mm, "
                                 "target_ebitda_margin=:target_ebitda_margin, target_exit_multiple=:target_exit_multiple, "
                                 "status=:status, updated_date=:updated_date WHERE id=:id"),
                            {"hypothesis": hypothesis, "key_assumptions": key_assumptions, "target_exit_year": target_exit_year,
                             "target_revenue_mm": target_revenue_mm, "target_ebitda_margin": target_ebitda_margin,
                             "target_exit_multiple": target_exit_multiple, "status": status, "updated_date": now, "id": existing})
                return {"success": True, "thesis_id": existing, "action": "updated"}
            else:
                result = conn.execute(text("INSERT INTO investment_thesis(company_id, hypothesis, key_assumptions, "
                                          "target_exit_year, target_revenue_mm, target_ebitda_margin, target_exit_multiple, "
                                          "status, created_date, updated_date) "
                                          "VALUES(:company_id, :hypothesis, :key_assumptions, :target_exit_year, "
                                          ":target_revenue_mm, :target_ebitda_margin, :target_exit_multiple, :status, :created_date, :updated_date) "
                                          "RETURNING id"),
                                     {"company_id": company_id, "hypothesis": hypothesis, "key_assumptions": key_assumptions,
                                      "target_exit_year": target_exit_year, "target_revenue_mm": target_revenue_mm,
                                      "target_ebitda_margin": target_ebitda_margin, "target_exit_multiple": target_exit_multiple,
                                      "status": status, "created_date": now, "updated_date": now})
                thesis_id = result.scalar()
                return {"success": True, "thesis_id": thesis_id, "action": "created"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_thesis(company_id: int) -> dict:
    try:
        with engine.connect() as conn:
            thesis = conn.execute(text("SELECT id, company_id, hypothesis, key_assumptions, target_exit_year, "
                                      "target_revenue_mm, target_ebitda_margin, target_exit_multiple, status, "
                                      "created_date, updated_date FROM investment_thesis WHERE company_id = :company_id"),
                                 {"company_id": company_id}).mappings().first()
            milestones = []
            if thesis:
                milestones = conn.execute(text("SELECT id, thesis_id, milestone_text, target_date, achieved "
                                              "FROM thesis_milestones WHERE thesis_id = :thesis_id ORDER BY target_date"),
                                         {"thesis_id": thesis['id']}).mappings().all()
            return {"success": True, "thesis": dict(thesis) if thesis else None,
                    "milestones": [dict(m) for m in milestones]}
    except Exception as e:
        return {"success": False, "error": str(e)}


def upsert_milestone(thesis_id: int, milestone_text: str, target_date: str, achieved: int = 0) -> dict:
    try:
        with engine.begin() as conn:
            existing = conn.execute(text("SELECT id FROM thesis_milestones WHERE thesis_id = :thesis_id AND milestone_text = :milestone_text"),
                                   {"thesis_id": thesis_id, "milestone_text": milestone_text}).scalar()
            if existing:
                conn.execute(text("UPDATE thesis_milestones SET target_date=:target_date, achieved=:achieved WHERE id=:id"),
                            {"target_date": target_date, "achieved": achieved, "id": existing})
                return {"success": True, "milestone_id": existing, "action": "updated"}
            else:
                result = conn.execute(text("INSERT INTO thesis_milestones(thesis_id, milestone_text, target_date, achieved) "
                                          "VALUES(:thesis_id, :milestone_text, :target_date, :achieved) RETURNING id"),
                                     {"thesis_id": thesis_id, "milestone_text": milestone_text, "target_date": target_date,
                                      "achieved": achieved})
                milestone_id = result.scalar()
                return {"success": True, "milestone_id": milestone_id, "action": "created"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def delete_milestone(milestone_id: int) -> dict:
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM thesis_milestones WHERE id = :id"), {"id": milestone_id})
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_all_thesis_statuses() -> dict:
    try:
        with engine.connect() as conn:
            companies = conn.execute(text("SELECT c.id, c.name, c.sector, "
                                         "t.status, t.target_exit_year, t.target_revenue_mm, "
                                         "t.target_ebitda_margin, t.target_exit_multiple "
                                         "FROM companies c LEFT JOIN investment_thesis t ON c.id = t.company_id "
                                         "ORDER BY c.name")).mappings().all()
            return {"success": True, "companies": [dict(c) for c in companies]}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_value_creation(company_id: int, current_multiple: float = None) -> dict:
    try:
        with engine.connect() as conn:
            # Get company entry data
            company = conn.execute(text("SELECT entry_ev_mm, entry_year FROM companies WHERE id = :id"),
                                  {"id": company_id}).mappings().first()
            if not company:
                return {"success": False, "error": "Company not found"}

            # Get first-period revenue for entry baseline
            entry_rev_row = conn.execute(text("SELECT value FROM financial_metrics "
                                             "WHERE company_id = :company_id AND metric_name = 'revenue' "
                                             "ORDER BY period ASC LIMIT 1"),
                                        {"company_id": company_id}).mappings().first()
            if not entry_rev_row:
                return {"success": False, "error": "No financial data found"}

            # Get latest financial data (assume most recent period has both revenue and ebitda)
            latest_period = conn.execute(text("SELECT DISTINCT period FROM financial_metrics "
                                             "WHERE company_id = :company_id "
                                             "ORDER BY period DESC LIMIT 1"),
                                        {"company_id": company_id}).scalar()
            if not latest_period:
                return {"success": False, "error": "No financial data found"}

            current_rev_row = conn.execute(text("SELECT value FROM financial_metrics "
                                               "WHERE company_id = :company_id AND period = :period AND metric_name = 'revenue'"),
                                          {"company_id": company_id, "period": latest_period}).mappings().first()
            current_ebitda_row = conn.execute(text("SELECT value FROM financial_metrics "
                                                   "WHERE company_id = :company_id AND period = :period AND metric_name = 'ebitda'"),
                                              {"company_id": company_id, "period": latest_period}).mappings().first()

            if not current_rev_row or not current_ebitda_row:
                return {"success": False, "error": f"Incomplete financial data for {latest_period}"}

            # Get thesis multiple (if exists)
            thesis = conn.execute(text("SELECT target_exit_multiple FROM investment_thesis WHERE company_id = :company_id"),
                                 {"company_id": company_id}).mappings().first()

        # Computations
        entry_rev = float(entry_rev_row['value'])
        entry_ev = float(company['entry_ev_mm'])
        current_rev = float(current_rev_row['value'])
        current_ebitda = float(current_ebitda_row['value'])

        # Assume entry margin = current margin if we only have one ebitda value
        entry_margin = current_ebitda / current_rev if current_rev > 0 else 0.25
        current_margin = current_ebitda / current_rev if current_rev > 0 else 0.25

        entry_ebitda = entry_rev * entry_margin
        implied_entry_multiple = entry_ev / entry_ebitda if entry_ebitda > 0 else 1.0

        # Determine exit multiple
        if current_multiple:
            exit_multiple = float(current_multiple)
        elif thesis and thesis.get('target_exit_multiple'):
            exit_multiple = float(thesis['target_exit_multiple'])
        else:
            exit_multiple = implied_entry_multiple

        current_ev = current_ebitda * exit_multiple

        # Contribution calculations
        rev_growth_contrib = (current_rev - entry_rev) * entry_margin * implied_entry_multiple
        margin_contrib = (current_margin - entry_margin) * current_rev * implied_entry_multiple
        multiple_contrib = (exit_multiple - implied_entry_multiple) * current_ebitda

        value_created = current_ev - entry_ev
        value_created_pct = value_created / entry_ev if entry_ev > 0 else 0
        gross_moic = current_ev / entry_ev if entry_ev > 0 else 0

        return {
            "success": True,
            "company_id": company_id,
            "entry_ev_mm": entry_ev,
            "current_implied_ev": current_ev,
            "value_created_mm": value_created,
            "value_created_pct": value_created_pct,
            "gross_moic": gross_moic,
            "rev_growth_contrib": rev_growth_contrib,
            "margin_contrib": margin_contrib,
            "multiple_contrib": multiple_contrib,
            "entry_multiple": implied_entry_multiple,
            "current_multiple": exit_multiple,
            "entry_rev": entry_rev,
            "current_rev": current_rev,
            "entry_margin": entry_margin,
            "current_margin": current_margin
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_portfolio_value_creation() -> dict:
    try:
        with engine.connect() as conn:
            companies = conn.execute(text("SELECT id, name FROM companies")).mappings().all()

        results = []
        for company in companies:
            company_id = company['id']
            vc = get_value_creation(company_id)
            if vc.get("success"):
                result = {
                    "company_id": company_id,
                    "name": company['name'],
                    **{k: v for k, v in vc.items() if k != "success"}
                }
                results.append(result)

        # Sort by value created descending
        results.sort(key=lambda x: x.get('value_created_mm', 0), reverse=True)
        return {"success": True, "companies": results}
    except Exception as e:
        return {"success": False, "error": str(e)}


def upsert_note(company_id: int, note_key: str, note_value: str, source: str) -> dict:
    try:
        from datetime import datetime
        now = datetime.utcnow().isoformat()
        with engine.begin() as conn:
            result = conn.execute(text("INSERT INTO investment_notes(company_id, note_key, note_value, source, created_date) "
                                      "VALUES(:company_id, :note_key, :note_value, :source, :created_date) RETURNING id"),
                                 {"company_id": company_id, "note_key": note_key, "note_value": note_value,
                                  "source": source, "created_date": now})
            note_id = result.scalar()
            return {"success": True, "note_id": note_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_notes(company_id: int) -> dict:
    try:
        with engine.connect() as conn:
            notes = conn.execute(text("SELECT id, note_key, note_value, source, created_date FROM investment_notes "
                                     "WHERE company_id = :company_id ORDER BY created_date DESC"),
                                {"company_id": company_id}).mappings().all()
            return {"success": True, "notes": [dict(n) for n in notes]}
    except Exception as e:
        return {"success": False, "error": str(e)}


def delete_note(note_id: int) -> dict:
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM investment_notes WHERE id = :id"), {"id": note_id})
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def update_company_and_financials(company_id: int, fields_dict: dict) -> dict:
    try:
        with engine.begin() as conn:
            # Build dynamic SET clause for companies table
            company_fields = {"id": company_id}
            company_set_parts = []
            for field in ["name", "sector", "entry_year", "entry_ev_mm", "ownership_pct"]:
                if field in fields_dict:
                    company_set_parts.append(f"{field}=:{field}")
                    company_fields[field] = fields_dict[field]

            if company_set_parts:
                update_sql = f"UPDATE companies SET {', '.join(company_set_parts)} WHERE id = :id"
                conn.execute(text(update_sql), company_fields)

            # Update financial_metrics: revenue, ebitda by latest period
            latest_period = conn.execute(text("SELECT DISTINCT period FROM financial_metrics "
                                             "WHERE company_id = :company_id "
                                             "ORDER BY period DESC LIMIT 1"),
                                        {"company_id": company_id}).scalar()
            if latest_period:
                if "revenue_mm" in fields_dict:
                    conn.execute(text("UPDATE financial_metrics SET value = :val WHERE company_id = :cid AND period = :p AND metric_name = 'revenue'"),
                                {"val": fields_dict["revenue_mm"], "cid": company_id, "p": latest_period})
                if "ebitda_mm" in fields_dict:
                    conn.execute(text("UPDATE financial_metrics SET value = :val WHERE company_id = :cid AND period = :p AND metric_name = 'ebitda'"),
                                {"val": fields_dict["ebitda_mm"], "cid": company_id, "p": latest_period})

        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def seed_sample_data():
    create_all_tables()
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM companies")).scalar()
        if count > 0:
            print(f"  Portfolio data already seeded ({count} companies).")
            return

    import random
    random.seed(42)
    co_data = [
        (1,"MedTech Solutions Inc.","Healthcare",2021,142.0,0.80),
        (2,"BuildRight Construction","Construction",2020,98.0,0.75),
        (3,"CloudSync SaaS Platform","Technology",2022,210.0,0.65),
        (4,"Premier Retail Holdings","Retail",2019,185.0,0.90),
        (5,"Apex Industrial Manufacturing","Industrial",2021,168.0,0.70),
        (6,"NatFresh Food & Beverage","Consumer",2020,88.0,0.85),
        (7,"FastTrack Logistics","Logistics",2022,124.0,0.80),
        (8,"CareFirst Healthcare Services","Healthcare",2021,198.0,0.75),
        (9,"Permian Energy Services","Energy",2020,145.0,0.60),
        (10,"Vitality Consumer Brands","Consumer",2022,176.0,0.70),
    ]
    quarters = ["2023-Q1","2023-Q2","2023-Q3","2023-Q4",
                "2024-Q1","2024-Q2","2024-Q3","2024-Q4"]
    base_revenues = [13.2,33.5,9.0,55.4,32.3,23.5,23.3,24.3,66.8,34.0]
    base_margins  = [0.27,0.12,0.24,0.12,0.24,0.07,0.22,0.22,0.30,0.23]
    fin_rows, kpi_rows = [], []
    fid = kid = 1
    for co_id in range(1,11):
        rev = base_revenues[co_id-1]; margin = base_margins[co_id-1]
        for i, period in enumerate(quarters):
            growth = random.uniform(0.04,0.14); rev = round(rev*(1+growth/4),2)
            m = round(margin+random.uniform(-0.02,0.02),4)
            fin_rows.append({"id":fid,"company_id":co_id,"period":period,
                "revenue_mm":rev,"ebitda_mm":round(rev*m,2),"ebitda_margin":m,
                "yoy_growth":round(growth+random.uniform(-0.02,0.04),4) if i>=4 else None})
            fid += 1
    kpi_templates = {
        1:[("Patient Visits",26400,"count"),("Days in AR",41,"days")],
        2:[("Backlog $MM",53.7,"$MM"),("On-Time Delivery",0.946,"pct")],
        3:[("ARR $MM",41.2,"$MM"),("NRR",1.125,"pct")],
        4:[("Comp Store Growth",0.041,"pct"),("Sales per Sq Ft",431,"$")],
        5:[("OEE",0.831,"pct"),("Inventory Turns",7.4,"x")],
        6:[("Gross Margin $MM",7.8,"$MM"),("Category Mix Chg",0.09,"pct")],
        7:[("Fleet Utilization",0.862,"pct"),("Cost per Mile",2.31,"$")],
        8:[("Provider FTE",402,"count"),("Collections Rate",0.956,"pct")],
        9:[("Active Rigs",64,"count"),("Rig Utilization",0.871,"pct")],
        10:[("Active Customers K",694,"000s"),("DTC CAC $",23.1,"$")],
    }
    for co_id, kpis_list in kpi_templates.items():
        for name, val, unit in kpis_list:
            kpi_rows.append({"id":kid,"company_id":co_id,"period":"2024-Q4",
                "kpi_name":name,"kpi_value":val,"kpi_unit":unit}); kid+=1
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO companies(id,name,sector,entry_year,entry_ev_mm,ownership_pct) "
            "VALUES(:id,:name,:sector,:entry_year,:entry_ev_mm,:ownership_pct)"),
            [{"id":r[0],"name":r[1],"sector":r[2],"entry_year":r[3],
              "entry_ev_mm":r[4],"ownership_pct":r[5]} for r in co_data])
        conn.execute(text("INSERT INTO quarterly_financials(id,company_id,period,revenue_mm,ebitda_mm,ebitda_margin,yoy_growth) "
            "VALUES(:id,:company_id,:period,:revenue_mm,:ebitda_mm,:ebitda_margin,:yoy_growth)"), fin_rows)
        conn.execute(text("INSERT INTO kpis(id,company_id,period,kpi_name,kpi_value,kpi_unit) "
            "VALUES(:id,:company_id,:period,:kpi_name,:kpi_value,:kpi_unit)"), kpi_rows)
    print(f"  Seeded: {len(co_data)} companies, {len(fin_rows)} financials, {len(kpi_rows)} KPIs")
