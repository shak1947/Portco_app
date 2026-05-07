"""
Batch ingestion - process PDFs one at a time, appending to same Chroma collection.
"""
import sys
from pathlib import Path
import logging
import pdfplumber
from llama_index.core.text_splitter import SentenceSplitter
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
import chromadb

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

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

def ingest_batch(data_dir="data/adv", chroma_path="data/chroma_fresh"):
    """Process all PDFs one at a time, appending to same collection."""
    
    data_path = Path(data_dir)
    chroma_path = Path(chroma_path)
    chroma_path.mkdir(parents=True, exist_ok=True)
    
    pdf_files = sorted(data_path.glob("*.pdf"))
    if not pdf_files:
        logger.error(f"No PDFs found in {data_dir}")
        return
    
    logger.info(f"Found {len(pdf_files)} PDFs. Starting batch ingestion...")
    
    # Load embedder and splitter once
    logger.info("Loading embedding model...")
    embedder = HuggingFaceEmbedding(
        model_name="BAAI/bge-small-en-v1.5",
        cache_folder="./.cache"
    )
    splitter = SentenceSplitter(chunk_size=800, chunk_overlap=100)
    
    # Initialize Chroma once
    logger.info("Initializing Chroma collection...")
    client = chromadb.PersistentClient(path=str(chroma_path))
    try:
        collection = client.delete_collection(name="form_adv")
    except:
        pass
    collection = client.create_collection(name="form_adv", metadata={"hnsw:space": "cosine"})
    
    total_chunks = 0
    
    # Process each PDF
    for pdf_num, pdf_file in enumerate(pdf_files, 1):
        logger.info(f"\n[{pdf_num}/{len(pdf_files)}] Processing {pdf_file.name}...")
        
        firm_name = FIRM_MAPPING.get(pdf_file.name, pdf_file.stem)
        
        try:
            # Extract text
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
            
            # Embed in batches
            batch_size = 32
            ids = []
            documents = []
            embeddings = []
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

            # Batch embed
            logger.info(f"  Embedding {len(chunks)} chunks in batches of {batch_size}...")
            for i in range(0, len(documents), batch_size):
                batch_docs = documents[i:i+batch_size]
                batch_embeddings = embedder.get_text_embedding_batch(batch_docs)
                embeddings.extend(batch_embeddings)
                if (i + batch_size) % (batch_size * 4) == 0:
                    logger.info(f"    Embedded {min(i+batch_size, len(documents))}/{len(documents)}")

            # Add all at once
            collection.add(
                ids=ids,
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas
            )

            total_chunks += len(chunks)
            logger.info(f"  ✓ {firm_name}: {len(chunks)} chunks added (total: {total_chunks})")
            
        except Exception as e:
            logger.error(f"  ✗ Error processing {pdf_file.name}: {e}")
            continue
    
    logger.info(f"\n{'='*60}")
    logger.info(f"Batch ingestion complete!")
    logger.info(f"Total chunks indexed: {total_chunks}")
    logger.info(f"Vector store: {chroma_path}")
    logger.info(f"{'='*60}")

if __name__ == "__main__":
    ingest_batch()
