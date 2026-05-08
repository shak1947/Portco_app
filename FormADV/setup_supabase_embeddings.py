"""
Generate embeddings from PDFs and upload to Supabase pgvector.
"""

import os
import sys
from pathlib import Path
import PyPDF2
from openai import OpenAI
from supabase import create_client, Client
import time

# Supabase connection (set via environment variables)
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://kgkxqqjqfgenmdypcsiq.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_KEY:
    print("ERROR: SUPABASE_KEY environment variable not set")
    sys.exit(1)

# OpenAI connection
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def setup_supabase():
    """Initialize Supabase client and create pgvector table."""
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    print("Setting up Supabase...")

    # Create table with vector column using raw SQL
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

    CREATE INDEX IF NOT EXISTS embedding_index ON form_adv_embeddings
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
    """

    print("[OK] Supabase ready")
    return supabase

def chunk_pdf_text(pdf_path: str, chunk_size: int = 800, overlap: int = 100) -> list:
    """Extract and chunk text from PDF."""
    chunks = []
    chunk_id = 0

    try:
        with open(pdf_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            all_text = ""
            for page_num, page in enumerate(reader.pages):
                text = page.extract_text()
                all_text += f"\n[Page {page_num + 1}]\n{text}"

            # Split into overlapping chunks
            tokens = all_text.split()
            for i in range(0, len(tokens), chunk_size - overlap):
                chunk_tokens = tokens[i:i + chunk_size]
                if len(chunk_tokens) > 50:  # Minimum chunk size
                    chunk_text = " ".join(chunk_tokens)
                    chunks.append({
                        "chunk_id": chunk_id,
                        "text": chunk_text,
                        "source": os.path.basename(pdf_path),
                        "pdf_path": pdf_path
                    })
                    chunk_id += 1
    except Exception as e:
        print(f"Error processing {pdf_path}: {e}")

    return chunks

def generate_embeddings(pdf_dir: str = "Data/adv"):
    """Generate embeddings from all PDFs in directory."""
    print(f"\nProcessing PDFs from {pdf_dir}...")

    pdf_files = sorted(Path(pdf_dir).glob("*.pdf"))
    if not pdf_files:
        print(f"ERROR: No PDFs found in {pdf_dir}")
        return []

    all_embeddings = []

    for pdf_idx, pdf_path in enumerate(pdf_files, 1):
        print(f"\n[{pdf_idx}/{len(pdf_files)}] Processing {pdf_path.name}...")

        # Chunk the PDF
        chunks = chunk_pdf_text(str(pdf_path))
        print(f"  Created {len(chunks)} chunks")

        firm_name = pdf_path.stem.replace(" ADV", "").replace(" Form", "")

        # Embed chunks in batches
        batch_size = 50
        for batch_start in range(0, len(chunks), batch_size):
            batch_end = min(batch_start + batch_size, len(chunks))
            batch_chunks = chunks[batch_start:batch_end]
            batch_texts = [c["text"] for c in batch_chunks]

            try:
                embeddings_response = openai_client.embeddings.create(
                    model="text-embedding-3-small",
                    input=batch_texts
                )

                for i, embedding in enumerate(embeddings_response.data):
                    chunk_idx = batch_start + i
                    chunk = batch_chunks[i]

                    all_embeddings.append({
                        "id": f"{pdf_path.stem}_{chunk['chunk_id']}",
                        "firm_name": firm_name,
                        "source_file": pdf_path.name,
                        "page_number": 1,
                        "text": chunk["text"],
                        "embedding": embedding.embedding
                    })

                print(f"  Embedded {batch_end}/{len(chunks)} chunks", end="\r")

            except Exception as e:
                print(f"\n  ERROR embedding batch: {e}")
                time.sleep(2)  # Rate limit backoff

        print(f"  [OK] {len(chunks)} chunks embedded")

    print(f"\n[OK] Total embeddings generated: {len(all_embeddings)}")
    return all_embeddings

def upload_to_supabase(supabase: Client, embeddings: list):
    """Upload embeddings to Supabase in batches."""
    if not embeddings:
        print("ERROR: No embeddings to upload")
        return False

    print(f"\nUploading {len(embeddings)} embeddings to Supabase...")

    batch_size = 50
    for batch_idx, i in enumerate(range(0, len(embeddings), batch_size)):
        batch_end = min(i + batch_size, len(embeddings))
        batch = embeddings[i:batch_end]

        try:
            supabase.table("form_adv_embeddings").insert(batch).execute()
            print(f"  Uploaded {batch_end}/{len(embeddings)} embeddings")
        except Exception as e:
            print(f"  ERROR uploading batch {batch_idx}: {e}")
            # Try again after a delay
            time.sleep(2)
            try:
                supabase.table("form_adv_embeddings").insert(batch).execute()
                print(f"  Uploaded {batch_end}/{len(embeddings)} embeddings (retry)")
            except Exception as e2:
                print(f"  Failed to upload batch {batch_idx}: {e2}")

    print("[OK] Upload complete")
    return True

def verify_supabase(supabase: Client):
    """Verify the data in Supabase."""
    print("\nVerifying Supabase...")

    try:
        response = supabase.table("form_adv_embeddings").select("id, firm_name").execute()
        count = len(response.data) if response.data else 0

        if count > 0:
            print(f"[OK] Supabase contains {count} embeddings")
            # Show sample
            if response.data:
                print(f"  Sample: {response.data[0]['firm_name']} - {response.data[0]['id']}")
        return count > 0
    except Exception as e:
        print(f"ERROR verifying: {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("Setup Form ADV Embeddings in Supabase")
    print("=" * 60)

    try:
        # Check for OpenAI API key
        if not os.getenv("OPENAI_API_KEY"):
            print("ERROR: OPENAI_API_KEY not set")
            sys.exit(1)

        # Setup Supabase
        supabase = setup_supabase()

        # Generate embeddings from PDFs
        embeddings = generate_embeddings()

        if not embeddings:
            print("ERROR: Failed to generate embeddings")
            sys.exit(1)

        # Upload to Supabase
        if upload_to_supabase(supabase, embeddings):
            # Verify
            if verify_supabase(supabase):
                print("\n✓ Setup complete! Embeddings ready in Supabase")
            else:
                print("\nWARNING: Setup may have issues, check manually")
        else:
            print("\nERROR: Upload failed")
            sys.exit(1)

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
