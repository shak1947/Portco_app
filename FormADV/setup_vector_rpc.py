"""
Setup vector similarity search RPC function in Supabase.
Run this once to enable optimized vector search.
"""

import os
import sys
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: SUPABASE_URL and SUPABASE_KEY environment variables required")
    sys.exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Read the SQL from file
with open("setup_vector_search_rpc.sql", "r") as f:
    sql_commands = f.read()

print("Setting up vector similarity search RPC...")

try:
    # Note: Supabase doesn't expose raw SQL execution via the Python client
    # You need to run this SQL directly in the Supabase SQL Editor or via psql
    print("\nTo complete setup, run this SQL in your Supabase SQL Editor:")
    print("=" * 60)
    print(sql_commands)
    print("=" * 60)
    print("\nSteps:")
    print("1. Go to: https://supabase.com/dashboard/project/YOUR_PROJECT/sql/new")
    print("2. Copy and paste the SQL above")
    print("3. Click 'Run'")
    print("\nAlternatively, use psql or the Supabase CLI to execute the SQL.")

except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)
