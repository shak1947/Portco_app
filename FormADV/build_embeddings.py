"""
Build embeddings from PDFs on demand (for Railway deployment).
This script generates Chroma embeddings from Form ADV PDFs at runtime.
"""

import os
import sys
import json
from pathlib import Path
import PyPDF2
import chromadb
from openai import OpenAI

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
        print(f"Error processing {pdf_path}: {e}", file=sys.stderr)

    return chunks

def build_embeddings(pdf_dir: str = "Data/adv", output_dir: str = "Data/chroma_openai"):
    """Build embeddings from all PDFs in directory."""

    # Check if embeddings already exist
    chroma_db_path = Path(output_dir) / "chroma.sqlite3"
    if chroma_db_path.exists():
        print(f"Vector store already exists at {output_dir}, skipping rebuild")
        return True

    # Initialize clients
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        print("ERROR: OPENAI_API_KEY not set", file=sys.stderr)
        return False

    openai_client = OpenAI(api_key=openai_api_key)
    chroma_client = chromadb.PersistentClient(path=output_dir)

    # Delete existing collection if it exists
    try:
        chroma_client.delete_collection(name="form_adv")
    except:
        pass

    collection = chroma_client.get_or_create_collection(name="form_adv")

    # Process all PDFs
    pdf_files = list(Path(pdf_dir).glob("*.pdf"))
    if not pdf_files:
        print(f"No PDFs found in {pdf_dir}", file=sys.stderr)
        return False

    print(f"Processing {len(pdf_files)} PDFs...")
    total_chunks = 0

    for pdf_path in pdf_files:
        print(f"  Chunking {pdf_path.name}...")
        chunks = chunk_pdf_text(str(pdf_path))
        print(f"    {len(chunks)} chunks created")

        # Embed chunks in batches (OpenAI limit: 300K tokens per request)
        chunk_texts = [c["text"] for c in chunks]
        firm_name = pdf_path.stem.replace(" ADV", "").replace(" Form", "")
        batch_size = 100  # Process 100 chunks at a time (~80K tokens)

        for batch_start in range(0, len(chunk_texts), batch_size):
            batch_end = min(batch_start + batch_size, len(chunk_texts))
            batch_texts = chunk_texts[batch_start:batch_end]

            embeddings_response = openai_client.embeddings.create(
                model="text-embedding-3-small",
                input=batch_texts
            )

            # Add to Chroma with metadata
            for i, embedding in enumerate(embeddings_response.data):
                chunk_idx = batch_start + i
                chunk = chunks[chunk_idx]
                collection.add(
                    ids=[f"{pdf_path.stem}_{chunk['chunk_id']}"],
                    embeddings=[embedding.embedding],
                    documents=[chunk["text"]],
                    metadatas=[{
                        "firm_name": firm_name,
                        "source_file": pdf_path.name,
                        "page_number": 1  # TODO: extract from chunk text
                    }]
                )

        total_chunks += len(chunks)
        print(f"    Embedded {len(chunks)} chunks")

    print(f"\nSuccess! Total chunks embedded: {total_chunks}")
    print(f"Vector store saved to: {output_dir}")
    return True

if __name__ == "__main__":
    success = build_embeddings()
    sys.exit(0 if success else 1)
