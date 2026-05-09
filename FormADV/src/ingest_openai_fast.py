"""
Fast parallel ingestion with PyMuPDF (5-10x faster extraction).
- 8 parallel PDF extractions
- PyMuPDF instead of pdfplumber
- OpenAI embeddings batched
Time: 5-10 minutes total
Cost: ~$0.50
"""
import os
from pathlib import Path
from multiprocessing import Pool
import logging
import fitz  # PyMuPDF
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

def extract_pdf_fast(pdf_path):
    """Fast PDF extraction using PyMuPDF (fitz)."""
    pdf_file = Path(pdf_path)
    firm_name = FIRM_MAPPING.get(pdf_file.name, pdf_file.stem)

    try:
        logger.info(f"  [EXTRACT] {pdf_file.name}...")
        text_by_page = {}

        doc = fitz.open(str(pdf_file))
        for page_num, page in enumerate(doc, start=1):
            text = page.get_text()
            if text.strip():
                text_by_page[page_num] = text

        doc.close()

        logger.info(f"  [EXTRACT] {pdf_file.name}: {len(text_by_page)} pages ✓")

        return {
            "pdf_file": pdf_file,
            "firm_name": firm_name,
            "text_by_page": text_by_page,
            "success": True
        }
    except Exception as e:
        logger.error(f"  [EXTRACT] {pdf_file.name}: {e}")
        return {
            "pdf_file": pdf_file,
            "firm_name": firm_name,
            "error": str(e),
            "success": False
        }

def ingest_fast(data_dir="data/adv", chroma_path="data/chroma_openai"):
    """Fast parallel extraction + OpenAI embeddings."""

    data_path = Path(data_dir)
    chroma_path = Path(chroma_path)
    chroma_path.mkdir(parents=True, exist_ok=True)

    pdf_files = sorted(data_path.glob("*.pdf"))
    if not pdf_files:
        logger.error(f"No PDFs found in {data_dir}")
        return

    logger.info(f"Found {len(pdf_files)} PDFs")
    logger.info(f"Starting 8-worker parallel extraction...")

    # Parallel extraction with 8 workers
    with Pool(8) as pool:
        extracted = pool.map(extract_pdf_fast, pdf_files)

    # Init
    splitter = SentenceSplitter(chunk_size=800, chunk_overlap=100)
    client_chroma = chromadb.PersistentClient(path=str(chroma_path))
    try:
        client_chroma.delete_collection(name="form_adv")
    except:
        pass
    collection = client_chroma.create_collection(name="form_adv", metadata={"hnsw:space": "cosine"})

    logger.info("\nExtractions complete. Now embedding & storing...\n")

    total_chunks = 0
    total_cost = 0

    for idx, result in enumerate(extracted, 1):
        if not result["success"]:
            logger.error(f"[{idx}/{len(extracted)}] Failed: {result['error']}")
            continue

        pdf_file = result["pdf_file"]
        firm_name = result["firm_name"]
        text_by_page = result["text_by_page"]

        logger.info(f"[{idx}/{len(extracted)}] {firm_name}...")

        try:
            # Chunk
            full_text = "\n\n".join([f"[Page {pn}]\n{txt}" for pn, txt in text_by_page.items()])
            chunks = splitter.split_text(full_text)
            logger.info(f"  {len(chunks)} chunks")

            # Prepare
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

            # Embed via OpenAI
            batch_size = 100
            embeddings = []

            for i in range(0, len(documents), batch_size):
                batch_docs = documents[i:i+batch_size]

                response = client.embeddings.create(
                    model="text-embedding-3-small",
                    input=batch_docs
                )

                embeddings.extend([item.embedding for item in response.data])

                batch_tokens = len(batch_docs) * 800
                batch_cost = (batch_tokens / 1_000_000) * 0.02
                total_cost += batch_cost

            # Store
            collection.add(
                ids=ids,
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas
            )

            total_chunks += len(chunks)
            logger.info(f"  ✓ {len(chunks)} chunks added | Cost so far: ${total_cost:.3f}")

        except Exception as e:
            logger.error(f"  ✗ {e}")
            raise

    logger.info(f"\n{'='*60}")
    logger.info(f"✓ Complete!")
    logger.info(f"Total chunks: {total_chunks}")
    logger.info(f"Total cost: ${total_cost:.2f}")
    logger.info(f"Location: {chroma_path}")
    logger.info(f"{'='*60}")

if __name__ == "__main__":
    ingest_fast()
