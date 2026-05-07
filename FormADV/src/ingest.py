"""
Form ADV PDF ingestion pipeline.
Extracts text, chunks, embeds, and persists to Chroma.
"""

import os
import sys
from pathlib import Path
from typing import Dict
import logging

import pdfplumber
from llama_index.core.text_splitter import SentenceSplitter
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
import chromadb

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Filename to firm name mapping
FIRM_MAPPING: Dict[str, str] = {
    "Bain ADV.pdf": "Bain & Company",
    "CD&R Form ADV.pdf": "Clayton Dubilier & Rice",
    "CVC ADV.pdf": "CVC Capital Partners",
    "EQT ADV.pdf": "EQT Partners",
    "Hellman ADV.pdf": "Hellman & Friedman",
    "Kelso ADV.pdf": "Kelso & Company",
    "TA Associate ADV.pdf": "TA Associates",
    "Thoma ADV.pdf": "Thoma Bravo",
    "Visa ADV.pdf": "Visa Inc.",
    "Warburg Form ADV.pdf": "Warburg Pincus",
}

def extract_pdf_text(pdf_path: str) -> Dict[int, str]:
    """Extract text from PDF preserving page numbers."""
    text_by_page = {}
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                text_by_page[page_num] = text
    return text_by_page


def ingest_documents(data_dir: str = "data/adv", chroma_path: str = "data/chroma") -> None:
    """Ingest all PDFs from data_dir into Chroma vector store."""

    data_path = Path(data_dir)
    if not data_path.exists():
        logger.error(f"Data directory not found: {data_dir}")
        sys.exit(1)

    pdf_files = sorted(data_path.glob("*.pdf"))
    if not pdf_files:
        logger.error(f"No PDF files found in {data_dir}")
        sys.exit(1)

    logger.info(f"Found {len(pdf_files)} PDF files")

    # Initialize embedder (BAAI/bge-small-en-v1.5)
    logger.info("Loading embedding model BAAI/bge-small-en-v1.5...")
    embedder = HuggingFaceEmbedding(
        model_name="BAAI/bge-small-en-v1.5",
        cache_folder="./.cache"
    )

    # Initialize text splitter
    splitter = SentenceSplitter(chunk_size=800, chunk_overlap=100)

    # Initialize Chroma client
    chroma_path = Path(chroma_path)
    chroma_path.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=str(chroma_path))

    # Delete existing collection if it exists (rebuild from scratch)
    try:
        client.delete_collection(name="form_adv")
    except (ValueError, Exception):
        pass

    collection = client.create_collection(
        name="form_adv",
        metadata={"hnsw:space": "cosine"}
    )

    total_chunks = 0

    # Process each PDF
    for pdf_file in pdf_files:
        logger.info(f"Processing {pdf_file.name}...")

        firm_name = FIRM_MAPPING.get(pdf_file.name, pdf_file.stem)

        # Extract text by page
        text_by_page = extract_pdf_text(str(pdf_file))

        # Combine text from all pages and create chunks
        full_text = "\n\n".join(
            [f"[Page {page_num}]\n{text}" for page_num, text in text_by_page.items()]
        )

        chunks = splitter.split_text(full_text)
        logger.info(f"  Created {len(chunks)} chunks from {len(text_by_page)} pages")

        # Embed and add to collection
        for chunk_idx, chunk in enumerate(chunks):
            # Find which page this chunk came from by looking for [Page N] markers
            page_num = None
            for page_num_candidate in sorted(text_by_page.keys()):
                if f"[Page {page_num_candidate}]" in chunk:
                    page_num = page_num_candidate
            if page_num is None:
                page_num = 1  # Default to first page if unclear

            embedding = embedder.get_text_embedding(chunk)

            collection.add(
                ids=[f"{pdf_file.stem}_chunk_{chunk_idx}"],
                documents=[chunk],
                embeddings=[embedding],
                metadatas=[{
                    "firm_name": firm_name,
                    "page_number": str(page_num),
                    "source_file": pdf_file.name,
                    "chunk_index": str(chunk_idx)
                }]
            )
            total_chunks += 1

    logger.info(f"\nIngestion complete. Total chunks indexed: {total_chunks}")
    logger.info(f"Vector store persisted to {chroma_path}")


if __name__ == "__main__":
    ingest_documents()
