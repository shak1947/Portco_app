"""
Migrate embeddings from local Chroma to Supabase pgvector.
"""

import os
import sys
from pathlib import Path
import chromadb
from supabase import create_client, Client

# Supabase connection
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

def setup_supabase():
    """Initialize Supabase client and create pgvector table."""
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    print("Setting up Supabase pgvector table...")

    # Enable pgvector extension
    try:
        supabase.rpc("enable_pgvector").execute()
        print("✓ pgvector extension enabled")
    except:
        print("  pgvector may already be enabled")

    # Create table with vector column
    sql = """
    CREATE TABLE IF NOT EXISTS form_adv_embeddings (
        id TEXT PRIMARY KEY,
        firm_name TEXT,
        source_file TEXT,
        page_number INTEGER,
        text TEXT,
        embedding vector(1536),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS embedding_index ON form_adv_embeddings USING ivfflat (embedding vector_cosine_ops);
    """

    try:
        # Execute raw SQL
        response = supabase.postgrest.rpc("exec_sql", {"sql": sql}).execute()
        print("✓ Table created")
    except Exception as e:
        print(f"  Table may already exist: {e}")

    return supabase

def extract_from_chroma(chroma_path: str = "Data/chroma_openai"):
    """Extract all embeddings and metadata from local Chroma."""
    print(f"\nExtracting from Chroma: {chroma_path}")

    chroma_client = chromadb.PersistentClient(path=chroma_path)
    collection = chroma_client.get_collection(name="form_adv")

    # Get all data
    all_data = collection.get(include=["embeddings", "documents", "metadatas"])

    embeddings_to_upload = []
    for i, (chunk_id, embedding, text, metadata) in enumerate(zip(
        all_data["ids"],
        all_data["embeddings"],
        all_data["documents"],
        all_data["metadatas"]
    )):
        embeddings_to_upload.append({
            "id": chunk_id,
            "firm_name": metadata.get("firm_name", "Unknown"),
            "source_file": metadata.get("source_file", "Unknown"),
            "page_number": metadata.get("page_number", 0),
            "text": text,
            "embedding": embedding
        })

        if (i + 1) % 1000 == 0:
            print(f"  Extracted {i + 1} chunks...")

    print(f"✓ Extracted {len(embeddings_to_upload)} total chunks")
    return embeddings_to_upload

def upload_to_supabase(supabase: Client, embeddings: list):
    """Upload embeddings to Supabase in batches."""
    print(f"\nUploading {len(embeddings)} embeddings to Supabase...")

    # Upload in batches (Supabase has limits)
    batch_size = 100
    for i in range(0, len(embeddings), batch_size):
        batch = embeddings[i:i + batch_size]

        try:
            supabase.table("form_adv_embeddings").insert(batch).execute()
            print(f"  Uploaded {min(i + batch_size, len(embeddings))}/{len(embeddings)}")
        except Exception as e:
            print(f"  Error uploading batch {i//batch_size}: {e}")
            # Continue with next batch

    print("✓ Upload complete")

def verify_supabase(supabase: Client):
    """Verify the data in Supabase."""
    print("\nVerifying Supabase...")

    response = supabase.table("form_adv_embeddings").select("COUNT(*)").execute()
    count = response.data[0]["count"] if response.data else 0

    print(f"✓ Supabase contains {count} embeddings")
    return count > 0

if __name__ == "__main__":
    print("=" * 60)
    print("Migrating Form ADV embeddings to Supabase")
    print("=" * 60)

    try:
        # Setup Supabase
        supabase = setup_supabase()

        # Extract from Chroma
        embeddings = extract_from_chroma()

        if not embeddings:
            print("ERROR: No embeddings found in Chroma")
            sys.exit(1)

        # Upload to Supabase
        upload_to_supabase(supabase, embeddings)

        # Verify
        success = verify_supabase(supabase)

        if success:
            print("\n✓ Migration successful!")
            print("You can now update app.py to use Supabase")
        else:
            print("\nERROR: Verification failed")
            sys.exit(1)

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
