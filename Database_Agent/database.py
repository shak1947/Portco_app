"""
database.py — SQLAlchemy connection layer.
Handles portfolio company tables AND public market comp tables.
"""

import os
import json
import pandas as pd
from sqlalchemy import create_engine, text, inspect, MetaData, Table, Column
from sqlalchemy import Integer, String, Float, BigInteger
from sqlalchemy.exc import SQLAlchemyError
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///portfolio.db")
connect_args = {"sslmode": "require"} if any(x in DATABASE_URL for x in ["supabase","neon","sslmode"]) else {}
engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)


def execute_query(sql: str, limit: int = 500) -> dict:
    sql = sql.strip()
    first_word = sql.split()[0].upper() if sql.split() else ""
    if first_word not in ("SELECT", "WITH", "EXPLAIN"):
        return {"success": False, "error": f"Only SELECT queries allowed. Got: {first_word}",
                "columns": [], "rows": [], "row_count": 0}
    try:
        with engine.connect() as conn:
            df = pd.read_sql(text(sql), conn)
            truncated = len(df) > limit
            if truncated:
                df = df.head(limit)
            for col in df.columns:
                if df[col].dtype == "object":
                    df[col] = df[col].astype(str)
            return {"success": True, "columns": df.columns.tolist(), "rows": df.values.tolist(),
                    "row_count": len(df), "truncated": truncated, "error": None}
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
    metadata.create_all(engine, checkfirst=True)


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
