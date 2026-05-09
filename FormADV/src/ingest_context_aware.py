"""
Context-aware chunking that respects Form ADV structure.
- Chunks at field/question level (Item 1.A, Item 1.F, etc.)
- Splits on paragraph boundaries, not mid-sentence
- Logical chunks with overlap
- Much smaller but semantically coherent
Time: 10-15 minutes
Cost: ~$0.20
"""
import os
import sys
import re
from pathlib import Path
from multiprocessing import Pool
from dotenv import load_dotenv
import logging
import pdfplumber
import chromadb
from openai import OpenAI

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

def smart_chunk_by_fields(text: str, max_chunk_size: int = 300, overlap_size: int = 50) -> list[dict]:
    """
    Chunk text at field/question boundaries with paragraph awareness.

    Strategy:
    1. Detect field headers (lines that are labels/questions)
    2. Group content between field headers
    3. If a field is too long, split at paragraph breaks
    4. Create overlapping chunks
    """
    lines = text.split('\n')
    chunks = []
    current_field = None
    current_content = []

    for line in lines:
        stripped = line.strip()

        # Field header heuristics:
        # - Starts with "Item" followed by digit
        # - Starts with capital letter followed by "." and has substantial text (not just "City:" etc)
        # - Starts with "(" followed by digit/letter ")" AND contains more than 15 chars
        # Exclude: short form field labels like "City:", "State:", "Address:"
        is_field_header = (
            re.match(r'^Item\s+\d+', stripped) or
            (re.match(r'^[A-Z]\.\s+', stripped) and len(stripped) > 15) or
            (re.match(r'^\([A-Z0-9]+\)\s+', stripped) and len(stripped) > 20) or
            (len(stripped) < 120 and len(stripped) > 20 and stripped and stripped[-1] == ':')
        )

        if is_field_header and current_field and current_content:
            # Save previous field before starting new one
            field_text = '\n'.join(current_content).strip()
            if field_text:
                field_chunks = split_by_paragraphs(current_field, field_text, max_chunk_size, overlap_size)
                chunks.extend(field_chunks)
            current_field = stripped
            current_content = []
        elif is_field_header:
            current_field = stripped
            current_content = []
        elif current_field and stripped:  # Add non-empty lines to current field
            current_content.append(line)

    # Don't forget the last field
    if current_field and current_content:
        field_text = '\n'.join(current_content).strip()
        if field_text:
            field_chunks = split_by_paragraphs(current_field, field_text, max_chunk_size, overlap_size)
            chunks.extend(field_chunks)

    return chunks

def split_by_paragraphs(field_header: str, content: str, max_chunk_size: int, overlap_size: int) -> list[dict]:
    """
    Split a field's content at paragraph boundaries if too long.
    Paragraph = lines separated by blank lines.
    """
    # Split by blank lines to get paragraphs
    paragraphs = re.split(r'\n\s*\n', content)

    # If total is small, return as one chunk
    total_tokens = estimate_tokens(field_header + "\n" + content)
    if total_tokens < max_chunk_size:
        return [{
            "header": field_header,
            "content": content,
            "tokens": total_tokens
        }]

    # Otherwise, group paragraphs into chunks
    result = []
    current_chunk = field_header + "\n"
    current_tokens = estimate_tokens(current_chunk)

    for para in paragraphs:
        para_tokens = estimate_tokens(para)

        # If adding this paragraph exceeds limit and we have content, save chunk
        if current_tokens + para_tokens > max_chunk_size and len(current_chunk.split('\n')) > 1:
            result.append({
                "header": field_header,
                "content": current_chunk.strip(),
                "tokens": current_tokens
            })
            # Start new chunk with field header + last paragraph (overlap)
            current_chunk = field_header + "\n" + para
            current_tokens = estimate_tokens(current_chunk)
        else:
            current_chunk += para + "\n\n"
            current_tokens = estimate_tokens(current_chunk)

    # Add final chunk
    if current_chunk.strip() != field_header:
        result.append({
            "header": field_header,
            "content": current_chunk.strip(),
            "tokens": current_tokens
        })

    return result if result else [{
        "header": field_header,
        "content": content,
        "tokens": total_tokens
    }]

def estimate_tokens(text: str) -> int:
    """Rough estimate: ~4 chars per token"""
    return len(text) // 4

def extract_pdf_worker(pdf_file_path):
    """Extract PDF with context-aware chunking."""
    pdf_file = Path(pdf_file_path)
    firm_name = FIRM_MAPPING.get(pdf_file.name, pdf_file.stem)

    try:
        logger.info(f"  [EXTRACT] {pdf_file.name}...")
        all_chunks = []

        with pdfplumber.open(str(pdf_file)) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                if text.strip():
                    # Smart chunk this page
                    page_chunks = smart_chunk_by_fields(text)
                    for chunk_dict in page_chunks:
                        all_chunks.append({
                            "page": page_num,
                            "field": chunk_dict["header"],
                            "content": chunk_dict["content"],
                            "tokens": chunk_dict["tokens"]
                        })

        logger.info(f"  [EXTRACT] {pdf_file.name}: {len(all_chunks)} logical chunks")

        return {
            "pdf_file": pdf_file,
            "firm_name": firm_name,
            "chunks": all_chunks,
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

def ingest_context_aware(data_dir="data/adv", chroma_path="data/chroma_openai", num_workers=4):
    """Ingest with context-aware chunking."""

    data_path = Path(data_dir)
    chroma_path = Path(chroma_path)
    chroma_path.mkdir(parents=True, exist_ok=True)

    pdf_files = sorted(data_path.glob("*.pdf"))
    if not pdf_files:
        logger.error(f"No PDFs found in {data_dir}")
        return

    logger.info(f"Found {len(pdf_files)} PDFs. Starting context-aware ingestion...")

    # Parallel extraction
    with Pool(num_workers) as pool:
        extracted_data = pool.map(extract_pdf_worker, pdf_files)

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
        chunks = result["chunks"]

        logger.info(f"\n[{pdf_num}/{len(extracted_data)}] Processing {pdf_file.name} ({len(chunks)} chunks)...")

        try:
            # Prepare for embedding
            ids = []
            documents = []
            metadatas = []

            for chunk_idx, chunk in enumerate(chunks):
                ids.append(f"{pdf_file.stem}_field_{chunk_idx}")
                documents.append(chunk["content"])
                metadatas.append({
                    "firm_name": firm_name,
                    "field": chunk["field"],
                    "page_number": str(chunk["page"]),
                    "source_file": pdf_file.name,
                })

            logger.info(f"  Embedding {len(documents)} chunks...")

            # Embed with OpenAI (batch)
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

                # Cost calculation (rough)
                batch_tokens = len(batch_docs) * 200  # avg 200 tokens per chunk
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
    logger.info(f"✓ Context-aware ingestion complete!")
    logger.info(f"Total chunks indexed: {total_chunks}")
    logger.info(f"Total cost: ${total_cost:.2f}")
    logger.info(f"Vector store: {chroma_path}")
    logger.info(f"{'='*60}")

if __name__ == "__main__":
    ingest_context_aware()
