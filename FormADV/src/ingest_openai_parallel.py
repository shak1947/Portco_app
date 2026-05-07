"""
Fast parallel batch ingestion using OpenAI embeddings.
- Extracts 4 PDFs in parallel (4-8x faster)
- Batches embeddings to OpenAI
Cost: ~$0.50
Time: ~10-15 minutes (vs 70 minutes sequential)
"""
import os
import sys
from pathlib import Path
from multiprocessing import Pool, Manager
import logging
import pdfplumber
from llama_index.core.text_splitter import SentenceSplitter
import chromadb
from openai import OpenAI

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

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

def extract_pdf_worker(pdf_file_path):
    """Worker function to extract a single PDF in parallel."""
    pdf_file = Path(pdf_file_path)
    firm_name = FIRM_MAPPING.get(pdf_file.name, pdf_file.stem)

    try:
        logger.info(f"  [WORKER] Extracting {pdf_file.name}...")
        text_by_page = {}

        with pdfplumber.open(str(pdf_file)) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                if text.strip():
                    text_by_page[page_num] = text

        logger.info(f"  [WORKER] {pdf_file.name}: {len(text_by_page)} pages extracted")

        return {
            "pdf_file": pdf_file,
            "firm_name": firm_name,
            "text_by_page": text_by_page,
            "success": True
        }
    except Exception as e:
        logger.error(f"  [WORKER] Error extracting {pdf_file.name}: {e}")
        return {
            "pdf_file": pdf_file,
            "firm_name": firm_name,
            "error": str(e),
            "success": False
        }

def ingest_with_openai_parallel(data_dir="data/adv", chroma_path="data/chroma_openai", num_workers=4):
    """Process PDFs in parallel extraction, then embed with OpenAI."""

    data_path = Path(data_dir)
    chroma_path = Path(chroma_path)
    chroma_path.mkdir(parents=True, exist_ok=True)

    pdf_files = sorted(data_path.glob("*.pdf"))
    if not pdf_files:
        logger.error(f"No PDFs found in {data_dir}")
        return

    logger.info(f"Found {len(pdf_files)} PDFs. Starting parallel ingestion...")
    logger.info(f"Extracting with {num_workers} parallel workers...")

    # Parallel extraction
    extracted_data = []
    with Pool(num_workers) as pool:
        extracted_data = pool.map(extract_pdf_worker, pdf_files)

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

    # Process extracted data
    for pdf_num, result in enumerate(extracted_data, 1):
        if not result["success"]:
            logger.error(f"[{pdf_num}/{len(extracted_data)}] Failed: {result['error']}")
            continue

        pdf_file = result["pdf_file"]
        firm_name = result["firm_name"]
        text_by_page = result["text_by_page"]

        logger.info(f"\n[{pdf_num}/{len(extracted_data)}] Processing {pdf_file.name}...")

        try:
            # Chunk
            full_text = "\n\n".join([f"[Page {pn}]\n{txt}" for pn, txt in text_by_page.items()])
            chunks = splitter.split_text(full_text)
            logger.info(f"  Created {len(chunks)} chunks")

            # Prepare data
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

            # Embed with OpenAI
            logger.info(f"  Embedding {len(chunks)} chunks...")
            batch_size = 100
            embeddings = []

            for i in range(0, len(documents), batch_size):
                batch_docs = documents[i:i+batch_size]
                batch_num = i // batch_size + 1
                total_batches = (len(documents) + batch_size - 1) // batch_size

                logger.info(f"    Batch {batch_num}/{total_batches}...")

                response = client.embeddings.create(
                    model="text-embedding-3-small",
                    input=batch_docs
                )

                batch_embeddings = [item.embedding for item in response.data]
                embeddings.extend(batch_embeddings)

                batch_tokens = len(batch_docs) * 800
                batch_cost = (batch_tokens / 1_000_000) * 0.02
                total_cost += batch_cost
                logger.info(f"      Cost: ${batch_cost:.4f}")

            # Add to Chroma
            logger.info(f"  Adding to Chroma...")
            collection.add(
                ids=ids,
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas
            )

            total_chunks += len(chunks)
            logger.info(f"  ✓ {firm_name}: {len(chunks)} chunks (total: {total_chunks})")
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
    ingest_with_openai_parallel(num_workers=4)  # 4 PDFs extracted in parallel
