"""
Fast batch ingestion using OpenAI embeddings API.
Cost: ~$0.50 for 10 firms
Time: ~5 minutes total
"""
import os
import sys
from pathlib import Path
from collections import Counter
import logging
import pdfplumber
from llama_index.core.text_splitter import SentenceSplitter
import chromadb
from openai import OpenAI

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

FIRM_MAPPING = {
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

def ingest_with_openai(data_dir="data/adv", chroma_path="data/chroma_openai"):
    """Process all PDFs and embed with OpenAI API."""

    data_path = Path(data_dir)
    chroma_path = Path(chroma_path)
    chroma_path.mkdir(parents=True, exist_ok=True)

    pdf_files = sorted(data_path.glob("*.pdf"))
    if not pdf_files:
        logger.error(f"No PDFs found in {data_dir}")
        return

    logger.info(f"Found {len(pdf_files)} PDFs. Starting ingestion with OpenAI embeddings...")

    # Initialize splitter
    splitter = SentenceSplitter(chunk_size=800, chunk_overlap=100)

    # Initialize Chroma
    logger.info("Initializing Chroma collection...")
    client_chroma = chromadb.PersistentClient(path=str(chroma_path))
    try:
        client_chroma.delete_collection(name="form_adv")
    except:
        pass
    collection = client_chroma.create_collection(name="form_adv", metadata={"hnsw:space": "cosine"})

    total_chunks = 0
    total_cost = 0

    # Process each PDF
    for pdf_num, pdf_file in enumerate(pdf_files, 1):
        logger.info(f"\n[{pdf_num}/{len(pdf_files)}] Processing {pdf_file.name}...")

        firm_name = FIRM_MAPPING.get(pdf_file.name, pdf_file.stem)

        try:
            # Extract text
            logger.info(f"  Extracting text...")
            text_by_page = {}
            with pdfplumber.open(str(pdf_file)) as pdf:
                for page_num, page in enumerate(pdf.pages, start=1):
                    text = page.extract_text() or ""
                    if text.strip():
                        text_by_page[page_num] = text

            if not text_by_page:
                logger.warning(f"  No text extracted from {pdf_file.name}")
                continue

            logger.info(f"  Extracted {len(text_by_page)} pages")

            # Chunk
            full_text = "\n\n".join([f"[Page {pn}]\n{txt}" for pn, txt in text_by_page.items()])
            chunks = splitter.split_text(full_text)
            logger.info(f"  Created {len(chunks)} chunks")

            # Prepare data for OpenAI API
            ids = []
            documents = []
            metadatas = []

            for chunk_idx, chunk in enumerate(chunks):
                page_num = 1
                for pn in sorted(text_by_page.keys()):
                    if f"[Page {pn}]" in chunk:
                        page_num = pn

                ids.append(f"{pdf_file.stem}_chunk_{chunk_idx}")
                documents.append(chunk)
                metadatas.append({
                    "firm_name": firm_name,
                    "page_number": str(page_num),
                    "source_file": pdf_file.name,
                    "chunk_index": str(chunk_idx)
                })

            # Embed with OpenAI in batches
            logger.info(f"  Embedding {len(chunks)} chunks with OpenAI...")
            batch_size = 100  # OpenAI can handle larger batches
            embeddings = []

            for i in range(0, len(documents), batch_size):
                batch_docs = documents[i:i+batch_size]
                batch_num = i // batch_size + 1
                total_batches = (len(documents) + batch_size - 1) // batch_size

                logger.info(f"    Batch {batch_num}/{total_batches}...")

                # Call OpenAI Embeddings API
                response = client.embeddings.create(
                    model="text-embedding-3-small",
                    input=batch_docs
                )

                # Extract embeddings
                batch_embeddings = [item.embedding for item in response.data]
                embeddings.extend(batch_embeddings)

                # Track cost (token counting from OpenAI response)
                # text-embedding-3-small: $0.02 per 1M tokens
                # Average: ~800 tokens per chunk
                batch_tokens = len(batch_docs) * 800
                batch_cost = (batch_tokens / 1_000_000) * 0.02
                total_cost += batch_cost
                logger.info(f"      Cost for this batch: ${batch_cost:.4f}")

            # Add all to Chroma
            logger.info(f"  Adding {len(chunks)} chunks to Chroma...")
            collection.add(
                ids=ids,
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas
            )

            total_chunks += len(chunks)
            logger.info(f"  ✓ {firm_name}: {len(chunks)} chunks added (total: {total_chunks})")
            logger.info(f"    Running cost: ${total_cost:.4f}")

        except Exception as e:
            logger.error(f"  ✗ Error processing {pdf_file.name}: {e}")
            raise

    logger.info(f"\n{'='*60}")
    logger.info(f"Ingestion complete!")
    logger.info(f"Total chunks indexed: {total_chunks}")
    logger.info(f"Total cost: ${total_cost:.2f}")
    logger.info(f"Vector store: {chroma_path}")
    logger.info(f"{'='*60}")

if __name__ == "__main__":
    ingest_with_openai()
