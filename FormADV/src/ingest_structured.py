"""
Structured ingestion that respects Form ADV document structure.
- Extracts content by Item/Section
- Chunks each section independently (400 tokens instead of 800)
- Preserves field relationships
Time: 10-15 minutes
Cost: ~$0.30
"""
import os
import sys
from pathlib import Path
from multiprocessing import Pool
from dotenv import load_dotenv
import logging
import pdfplumber
from llama_index.core.text_splitter import SentenceSplitter
import chromadb
from openai import OpenAI

# Load environment variables
load_dotenv(Path(__file__).parent.parent / ".env")

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

# Form ADV Item headers to chunk by
ITEM_PATTERN = [
    "Item 1",
    "Item 2",
    "Item 3",
    "Item 4",
    "Item 5",
    "Item 6",
    "Item 7",
    "Item 8",
    "Item 9",
    "Item 10",
    "Item 11",
    "Item 12",
    "Item 13",
    "Item 14",
    "Item 15",
    "Item 16",
    "Item 17",
    "Item 18",
]

def extract_pdf_worker(pdf_file_path):
    """Extract PDF and split by Items."""
    pdf_file = Path(pdf_file_path)
    firm_name = FIRM_MAPPING.get(pdf_file.name, pdf_file.stem)

    try:
        logger.info(f"  [EXTRACT] {pdf_file.name}...")
        sections = []

        with pdfplumber.open(str(pdf_file)) as pdf:
            full_text = ""
            page_map = {}  # Track which page each character is on

            for page_num, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                page_map[len(full_text)] = page_num
                full_text += f"\n[Page {page_num}]\n{text}"

        # Split by Item
        sections = []
        current_item = "Preamble"
        current_text = ""

        lines = full_text.split("\n")
        current_page = 1

        for line in lines:
            # Track page number
            if "[Page" in line:
                try:
                    current_page = int(line.split("[Page ")[1].split("]")[0])
                except:
                    pass

            # Check if this line starts a new Item
            is_new_item = False
            for item in ITEM_PATTERN:
                if line.strip().startswith(item) and (line.strip() == item or line.strip()[len(item):len(item)+1].isspace()):
                    if current_text.strip():
                        sections.append({
                            "item": current_item,
                            "text": current_text,
                            "page": current_page
                        })
                    current_item = item
                    current_text = line + "\n"
                    is_new_item = True
                    break

            if not is_new_item:
                current_text += line + "\n"

        # Don't forget last section
        if current_text.strip():
            sections.append({
                "item": current_item,
                "text": current_text,
                "page": current_page
            })

        logger.info(f"  [EXTRACT] {pdf_file.name}: {len(sections)} sections")

        return {
            "pdf_file": pdf_file,
            "firm_name": firm_name,
            "sections": sections,
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

def ingest_structured(data_dir="data/adv", chroma_path="data/chroma_openai", num_workers=4):
    """Ingest with structured chunking."""

    data_path = Path(data_dir)
    chroma_path = Path(chroma_path)
    chroma_path.mkdir(parents=True, exist_ok=True)

    pdf_files = sorted(data_path.glob("*.pdf"))
    if not pdf_files:
        logger.error(f"No PDFs found in {data_dir}")
        return

    logger.info(f"Found {len(pdf_files)} PDFs. Starting structured ingestion...")

    # Parallel extraction
    with Pool(num_workers) as pool:
        extracted_data = pool.map(extract_pdf_worker, pdf_files)

    # Initialize splitter (smaller chunks for structure)
    splitter = SentenceSplitter(chunk_size=400, chunk_overlap=50)

    # Clear and recreate Chroma
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
        sections = result["sections"]

        logger.info(f"\n[{pdf_num}/{len(extracted_data)}] Processing {pdf_file.name} ({len(sections)} sections)...")

        try:
            # Chunk each section independently
            ids = []
            documents = []
            metadatas = []

            for section_idx, section in enumerate(sections):
                item = section["item"]
                text = section["text"]
                page = section.get("page", 1)

                chunks = splitter.split_text(text)

                for chunk_idx, chunk in enumerate(chunks):
                    ids.append(f"{pdf_file.stem}_item{section_idx}_chunk{chunk_idx}")
                    documents.append(chunk)
                    metadatas.append({
                        "firm_name": firm_name,
                        "item": item,
                        "page_number": str(page),
                        "source_file": pdf_file.name,
                    })

            logger.info(f"  Created {len(documents)} chunks from {len(sections)} sections")

            # Embed with OpenAI
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

                batch_tokens = len(batch_docs) * 400
                batch_cost = (batch_tokens / 1_000_000) * 0.02
                total_cost += batch_cost

            # Add to Chroma
            collection.add(
                ids=ids,
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas
            )

            total_chunks += len(documents)
            logger.info(f"  ✓ {firm_name}: {len(documents)} chunks (total: {total_chunks})")
            logger.info(f"    Running cost: ${total_cost:.4f}")

        except Exception as e:
            logger.error(f"  ✗ Error processing {pdf_file.name}: {e}")
            raise

    logger.info(f"\n{'='*60}")
    logger.info(f"✓ Structured ingestion complete!")
    logger.info(f"Total chunks indexed: {total_chunks}")
    logger.info(f"Total cost: ${total_cost:.2f}")
    logger.info(f"Vector store: {chroma_path}")
    logger.info(f"{'='*60}")

if __name__ == "__main__":
    ingest_structured()
