"""
fetch_comps.py — Fetch and store 5 years of public market comp data.

Run this once to populate historical data, then on a schedule (weekly/monthly)
to keep it current. All data stored in Supabase via SQLAlchemy.

Usage: py fetch_comps.py
"""

import os
import time
import yfinance as yf
from datetime import datetime, timedelta
from sqlalchemy import text
from dotenv import load_dotenv
from database import engine, create_all_tables

load_dotenv()

# ── Sector comp universe ───────────────────────────────────────────────────────
SECTOR_COMPS = {
    "medtech":        ["MDT", "SYK", "BSX", "EW",   "HOLX"],
    "construction":   ["VMC", "MLM", "URI", "PWR",   "MTZ"],
    "saas":           ["CRM", "NOW", "HUBS","ZM",    "DDOG"],
    "retail":         ["TJX", "ROST","DG",  "DLTR",  "FIVE"],
    "industrial":     ["EMR", "ITT", "ROP", "AME",   "PNR"],
    "food_bev":       ["SYY", "USFD","PFGC","CHEF",  "UNFI"],
    "logistics":      ["XPO", "SAIA","ODFL","CHRW",  "JBHT"],
    "healthcare_svc": ["HCA", "UHS", "THC", "ENSG",  "AMED"],
    "energy_svc":     ["HAL", "SLB", "BKR", "OIS",   "DNOW"],
    "consumer":       ["EL",  "CHD", "CLX", "SPB",   "CENT"],
}

ALL_TICKERS = list({t for tickers in SECTOR_COMPS.values() for t in tickers})
TICKER_TO_SECTOR = {t: s for s, tickers in SECTOR_COMPS.items() for t in tickers}


def fetch_all_comps(refresh=False):
    """
    Main entry point. Fetches:
    1. Current metrics for all comps (market_comps table)
    2. 5 years of monthly price history (comp_price_history table)
    3. Available quarterly financials (comp_quarterly_metrics table)
    """
    create_all_tables()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    today   = datetime.now().strftime("%Y-%m-%d")

    print(f"\nFetching comp data for {len(ALL_TICKERS)} tickers...")
    print(f"Timestamp: {now_str}\n")

    fetched = skipped = errors = 0

    for i, ticker in enumerate(ALL_TICKERS):
        sector = TICKER_TO_SECTOR.get(ticker, "unknown")
        print(f"[{i+1}/{len(ALL_TICKERS)}] {ticker} ({sector})")

        # Check if already fetched today (skip unless refresh=True)
        if not refresh:
            with engine.connect() as conn:
                result = conn.execute(
                    text("SELECT last_updated FROM market_comps WHERE ticker = :t"),
                    {"t": ticker}
                ).fetchone()
                if result and result[0] and result[0][:10] == today:
                    print(f"  Already fetched today. Skipping.")
                    skipped += 1
                    continue

        try:
            t = yf.Ticker(ticker)
            info = t.info

            # ── 1. Current metrics ─────────────────────────────────────────────
            comp_data = {
                "ticker":         ticker,
                "name":           info.get("longName") or info.get("shortName", ticker),
                "sector_key":     sector,
                "market_cap_mm":  round(info["marketCap"]/1e6, 1) if info.get("marketCap") else None,
                "ev_ebitda":      round(info["enterpriseToEbitda"], 2) if info.get("enterpriseToEbitda") else None,
                "ev_revenue":     round(info["enterpriseToRevenue"], 2) if info.get("enterpriseToRevenue") else None,
                "revenue_growth": round(info["revenueGrowth"], 4) if info.get("revenueGrowth") else None,
                "ebitda_margin":  round(info["ebitdaMargins"], 4) if info.get("ebitdaMargins") else None,
                "gross_margin":   round(info["grossMargins"], 4) if info.get("grossMargins") else None,
                "last_updated":   now_str,
            }

            with engine.begin() as conn:
                # Upsert: delete then insert
                conn.execute(text("DELETE FROM market_comps WHERE ticker = :t"), {"t": ticker})
                conn.execute(text("""
                    INSERT INTO market_comps
                        (ticker, name, sector_key, market_cap_mm, ev_ebitda, ev_revenue,
                         revenue_growth, ebitda_margin, gross_margin, last_updated)
                    VALUES
                        (:ticker, :name, :sector_key, :market_cap_mm, :ev_ebitda, :ev_revenue,
                         :revenue_growth, :ebitda_margin, :gross_margin, :last_updated)
                """), comp_data)

            ev_str = f"EV/EBITDA={comp_data.get('ev_ebitda','N/A')}x" if comp_data.get('ev_ebitda') else "EV/EBITDA=N/A"
            print(f"  Current: {ev_str}, Mkt Cap=${comp_data.get('market_cap_mm','N/A')}M")

            # ── 2. 5-year monthly price history ───────────────────────────────
            hist = t.history(period="5y", interval="1mo")
            if not hist.empty:
                # Remove any existing history for this ticker
                with engine.begin() as conn:
                    conn.execute(text("DELETE FROM comp_price_history WHERE ticker = :t"), {"t": ticker})

                price_rows = []
                for date_idx, row in hist.iterrows():
                    date_str = str(date_idx)[:10]
                    price_rows.append({
                        "ticker":    ticker,
                        "date":      date_str,
                        "close":     round(float(row.get("Close", 0) or 0), 4),
                        "volume":    int(row.get("Volume", 0) or 0),
                        "adj_close": round(float(row.get("Close", 0) or 0), 4),
                    })

                if price_rows:
                    with engine.begin() as conn:
                        conn.execute(text("""
                            INSERT INTO comp_price_history (ticker, date, close, volume, adj_close)
                            VALUES (:ticker, :date, :close, :volume, :adj_close)
                        """), price_rows)
                    print(f"  Price history: {len(price_rows)} monthly records (5yr)")

            # ── 3. Quarterly financial metrics ─────────────────────────────────
            try:
                qf = t.quarterly_income_stmt
                if qf is not None and not qf.empty:
                    with engine.begin() as conn:
                        conn.execute(
                            text("DELETE FROM comp_quarterly_metrics WHERE ticker = :t"),
                            {"t": ticker}
                        )

                    q_rows = []
                    for col in qf.columns:
                        try:
                            # Map to quarter string e.g. "2024-Q1"
                            period_str = f"{col.year}-Q{(col.month-1)//3+1}"
                            total_rev  = qf.loc["Total Revenue", col] if "Total Revenue" in qf.index else None
                            gross_prof = qf.loc["Gross Profit", col] if "Gross Profit" in qf.index else None
                            ebitda_val = qf.loc["EBITDA", col] if "EBITDA" in qf.index else None

                            rev_mm      = round(float(total_rev)/1e6, 2) if total_rev and total_rev == total_rev else None
                            gross_mg    = round(float(gross_prof)/float(total_rev), 4) if gross_prof and total_rev and total_rev != 0 else None
                            ebitda_mg   = round(float(ebitda_val)/float(total_rev), 4) if ebitda_val and total_rev and total_rev != 0 else None

                            q_rows.append({
                                "ticker":       ticker,
                                "period":       period_str,
                                "revenue_mm":   rev_mm,
                                "gross_margin": gross_mg,
                                "ebitda_margin":ebitda_mg,
                                "fetched_date": today,
                            })
                        except Exception:
                            continue

                    if q_rows:
                        with engine.begin() as conn:
                            conn.execute(text("""
                                INSERT INTO comp_quarterly_metrics
                                    (ticker, period, revenue_mm, gross_margin, ebitda_margin, fetched_date)
                                VALUES
                                    (:ticker, :period, :revenue_mm, :gross_margin, :ebitda_margin, :fetched_date)
                            """), q_rows)
                        print(f"  Quarterly financials: {len(q_rows)} periods")
            except Exception as qe:
                print(f"  Quarterly financials: N/A ({str(qe)[:60]})")

            fetched += 1
            time.sleep(0.5)  # be respectful to Yahoo Finance rate limits

        except Exception as e:
            print(f"  ERROR: {str(e)[:100]}")
            errors += 1
            time.sleep(1)

    print(f"\n{'='*50}")
    print(f"Complete: {fetched} fetched, {skipped} skipped, {errors} errors")
    print(f"Tables: market_comps, comp_price_history, comp_quarterly_metrics")
    print(f"{'='*50}")


def get_comp_summary() -> dict:
    """Quick summary of what's stored in the comp tables."""
    queries = {
        "total_comps":    "SELECT COUNT(DISTINCT ticker) FROM market_comps",
        "price_records":  "SELECT COUNT(*) FROM comp_price_history",
        "quarterly_recs": "SELECT COUNT(*) FROM comp_quarterly_metrics",
        "sectors":        "SELECT DISTINCT sector_key FROM market_comps ORDER BY sector_key",
        "last_updated":   "SELECT MAX(last_updated) FROM market_comps",
    }
    results = {}
    with engine.connect() as conn:
        for key, sql in queries.items():
            try:
                rows = conn.execute(text(sql)).fetchall()
                results[key] = rows[0][0] if len(rows) == 1 else [r[0] for r in rows]
            except Exception as e:
                results[key] = f"Error: {e}"
    return results


if __name__ == "__main__":
    import sys
    refresh = "--refresh" in sys.argv
    if refresh:
        print("Force refresh mode — re-fetching all tickers.")
    fetch_all_comps(refresh=refresh)
    print("\nDatabase summary:")
    summary = get_comp_summary()
    for k, v in summary.items():
        print(f"  {k}: {v}")
